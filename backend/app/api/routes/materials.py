"""발표 자료(PDF·PPTX) 업로드 + 백그라운드 파싱 (작업 3-1·3-2, api-spec §4.2).

업로드는 파일을 저장하고 materials 행을 queued로 만든 뒤 **즉시 202**를 반환한다.
실제 파싱(PyMuPDF·python-pptx)은 BackgroundTasks로 응답 후 실행되고, 결과는
materials.status 폴링으로 확인한다 (queued → processing → ready|failed).

파싱 잡은 요청 bytes가 아니라 storage_key에서 파일을 다시 읽는다 — 그래야 retry(3-3)가
같은 잡(_run_parse)을 재사용할 수 있다.
"""

import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_session_member, require_session_owner
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus
from app.db.session import SessionLocal, get_db
from app.schemas.session import ErrorInfo, MaterialDetail
from app.services.material import UnprocessableMaterialError, parse_material_to_slides

router = APIRouter(tags=["materials"])
logger = logging.getLogger("rehearsal.material")

_MAX_BYTES = 20 * 1024 * 1024  # §1.3: 20MB (materials.file_size_bytes CHECK와 동일)


# 형식별 에러 코드 (unprocessable, parse_error) — api-spec §9 에러 코드 표와 동일.
_ERROR_CODES = {
    "pdf": ("UNPROCESSABLE_PDF", "PDF_PARSE_ERROR"),
    "pptx": ("UNPROCESSABLE_PPTX", "PPTX_PARSE_ERROR"),
}


def _run_parse(session_id: str) -> None:
    """백그라운드 자료 파싱 잡. 응답 후 실행되므로 자기 DB 세션을 연다.

    storage_key에서 파일을 읽어 확장자에 맞는 파서로 파싱하고 materials를 갱신.
    예외는 status=failed + error_code로 흡수한다(잡은 절대 던지지 않음 — 던지면
    조용히 사라진다).
    """
    with SessionLocal() as db:
        material = db.get(models.Material, session_id)
        if material is None:  # 업로드 후 세션이 삭제된 경우 등
            return
        material.status = AsyncStatus.processing
        db.commit()

        ext = material.storage_key.rsplit(".", 1)[-1].lower()
        unprocessable_code, parse_error_code = _ERROR_CODES.get(ext, _ERROR_CODES["pdf"])
        try:
            data = storage.load(material.storage_key)
            slides = parse_material_to_slides(data, ext)
        except UnprocessableMaterialError as e:
            _fail(db, material, unprocessable_code, str(e))
            return
        except Exception as e:
            # MaterialParseError 외의 예상 못한 예외도 전부 흡수 — 던지면 잡이 조용히
            # 죽고 status가 processing에 영원히 갇힌다(retry는 failed만 받는다).
            logger.exception("자료 파싱 잡 실패: %s", session_id)
            _fail(db, material, parse_error_code, str(e))  # retry 대상
            return

        material.slides = slides
        material.page_count = len(slides)
        material.progress = 1.0
        material.status = AsyncStatus.ready
        material.error_code = None
        material.error_message = None
        db.commit()


def _fail(db: Session, material: models.Material, code: str, message: str) -> None:
    material.status = AsyncStatus.failed
    material.error_code = code
    material.error_message = message[:500]
    db.commit()


def recover() -> None:
    """서버 재시작으로 유실된 자료 파싱 잡 복구 (stt_queue/report_jobs.recover와 동일 성격).

    파싱은 BackgroundTasks(인메모리)라 재시작하면 queued/processing이 영원히 갇히고,
    retry는 failed만 받으므로 사용자가 복구할 방법이 없다 — 배포(update.sh)마다 백엔드가
    재시작되니 반드시 여기서 되살린다. 앱 시작 훅(main.py lifespan)에서 호출."""
    with SessionLocal() as db:
        ids = db.scalars(
            select(models.Material.session_id).where(
                models.Material.status.in_([AsyncStatus.queued, AsyncStatus.processing])
            )
        ).all()
    if not ids:
        return
    logger.info("미완료 자료 파싱 %d건 복구", len(ids))

    def _run_all() -> None:
        for sid in ids:
            _run_parse(sid)

    threading.Thread(target=_run_all, name="material-recover", daemon=True).start()


_MIME_EXT = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


def _material_ext(file: UploadFile) -> str | None:
    """업로드 파일의 자료 형식("pdf"|"pptx"). 미지원이면 None → 415.

    MIME이 우선, 아니면(octet-stream 등) 확장자로 판별. 레거시 .ppt(바이너리
    포맷)는 python-pptx가 못 읽어 미지원 — .pptx 재저장을 안내한다.
    """
    ext = _MIME_EXT.get(file.content_type or "")
    if ext:
        return ext
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".pptx"):
        return "pptx"
    return None


@router.post("/sessions/{session_id}/material", status_code=202)
def upload_material(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """자료(PDF·PPTX) 업로드 → 저장 + queued → 202. 파싱은 백그라운드. 재업로드는 덮어쓰기."""
    ext = _material_ext(file)
    if ext is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA",
                       "PDF·PPTX 파일만 업로드할 수 있어요. (.ppt는 .pptx로 다시 저장해 주세요)")

    key = storage.material_key(session.id, ext)
    try:
        # 스트리밍 저장 — 업로드를 통째로 메모리에 올리지 않는다 (녹음 업로드와 동일)
        size = storage.save_stream(key, file.file, max_bytes=_MAX_BYTES)
    except storage.EmptyUploadError:
        raise ApiError(400, "EMPTY_FILE", "빈 파일이에요.")
    except storage.FileTooLargeError:
        raise ApiError(413, "FILE_TOO_LARGE", "자료는 20MB 이하만 업로드할 수 있어요.")

    # 같은 세션 동시 업로드 직렬화 — 세션 행 잠금. 없으면 첫 업로드 시 두 요청이
    # 동시에 materials INSERT → PK(session_id) 충돌로 500 (재검증에서 실측).
    db.refresh(session, with_for_update=True)
    material = db.get(models.Material, session.id)
    if material is None:
        material = models.Material(session_id=session.id, file_name=file.filename or f"material.{ext}",
                                   file_size_bytes=size, storage_key=key)
        db.add(material)
    else:  # 재업로드 — 같은 key 덮어쓰기 + 상태 초기화
        if material.storage_key != key:
            # 형식이 바뀐 재업로드(pdf↔pptx) — 이전 확장자 파일이 고아로 남지 않게 제거
            storage.delete(material.storage_key)
        material.file_name = file.filename or f"material.{ext}"
        material.file_size_bytes = size
        material.storage_key = key
    material.status = AsyncStatus.queued
    material.progress = 0.0
    material.page_count = None
    material.slides = None
    material.error_code = None
    material.error_message = None
    db.commit()

    background.add_task(_run_parse, session.id)
    return {"status": AsyncStatus.queued.value}


def _require_material(session_id: str, db: Session) -> models.Material:
    material = db.get(models.Material, session_id)
    if material is None:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "업로드된 자료가 없어요.")
    return material


@router.get("/sessions/{session_id}/material", response_model=MaterialDetail)
def get_material(
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> MaterialDetail:
    """자료 파싱 상태 + 슬라이드 (멤버). 폴링으로 queued→processing→ready|failed 확인."""
    material = _require_material(session.id, db)
    error = None
    if material.error_code:
        error = ErrorInfo(code=material.error_code, message=material.error_message or "")
    return MaterialDetail(
        status=material.status, progress=material.progress,
        file_name=material.file_name, page_count=material.page_count,
        slides=material.slides, error=error,
    )


@router.post("/sessions/{session_id}/material/retry", status_code=202)
def retry_material(
    background: BackgroundTasks,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """파싱 재시도 (owner). 실패한 자료를 queued로 되돌리고 잡 재등록.

    파일은 storage에 남아 있으므로 재파싱만 하면 된다. failed일 때만 의미가 있어
    ready/processing 중 재시도는 409로 막는다 (중복 잡 방지)."""
    material = _require_material(session.id, db)
    if material.status not in (AsyncStatus.failed,):
        raise ApiError(409, "MATERIAL_NOT_RETRYABLE",
                       "실패한 자료만 다시 시도할 수 있어요.")
    material.status = AsyncStatus.queued
    material.progress = 0.0
    material.error_code = None
    material.error_message = None
    db.commit()
    background.add_task(_run_parse, session.id)
    return {"status": AsyncStatus.queued.value}


@router.delete("/sessions/{session_id}/material", status_code=204)
def delete_material(
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> None:
    """자료 삭제 (owner). 자료 없이도 발표 진행 가능. storage 파일도 제거."""
    material = _require_material(session.id, db)
    key = material.storage_key
    db.delete(material)
    db.commit()
    storage.delete(key)
