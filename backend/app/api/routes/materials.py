"""발표 자료 PDF 업로드 + 백그라운드 파싱 (작업 3-1·3-2, api-spec §4.2).

업로드는 파일을 저장하고 materials 행을 queued로 만든 뒤 **즉시 202**를 반환한다.
실제 파싱(PyMuPDF)은 BackgroundTasks로 응답 후 실행되고, 결과는 materials.status
폴링으로 확인한다 (queued → processing → ready|failed).

파싱 잡은 요청 bytes가 아니라 storage_key에서 파일을 다시 읽는다 — 그래야 retry(3-3)가
같은 잡(_run_parse)을 재사용할 수 있다.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import require_session_member, require_session_owner
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus
from app.db.session import SessionLocal, get_db
from app.schemas.session import ErrorInfo, MaterialDetail
from app.services.material import (
    PdfParseError,
    UnprocessablePdfError,
    parse_pdf_to_slides,
)

router = APIRouter(tags=["materials"])
logger = logging.getLogger("rehearsal.material")

_MAX_BYTES = 20 * 1024 * 1024  # §1.3: 20MB (materials.file_size_bytes CHECK와 동일)


def _run_parse(session_id: str) -> None:
    """백그라운드 PDF 파싱 잡. 응답 후 실행되므로 자기 DB 세션을 연다.

    storage_key에서 파일을 읽어 파싱하고 materials를 갱신. 예외는 status=failed +
    error_code로 흡수한다(잡은 절대 던지지 않음 — 던지면 조용히 사라진다).
    """
    with SessionLocal() as db:
        material = db.get(models.Material, session_id)
        if material is None:  # 업로드 후 세션이 삭제된 경우 등
            return
        material.status = AsyncStatus.processing
        db.commit()

        try:
            pdf_bytes = storage.load(material.storage_key)
            slides = parse_pdf_to_slides(pdf_bytes)
        except UnprocessablePdfError as e:
            _fail(db, material, "UNPROCESSABLE_PDF", str(e))
            return
        except (PdfParseError, FileNotFoundError, OSError) as e:
            _fail(db, material, "PDF_PARSE_ERROR", str(e))  # retry 대상
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


def _looks_like_pdf(file: UploadFile) -> bool:
    if file.content_type in ("application/pdf", "application/x-pdf"):
        return True
    return bool(file.filename and file.filename.lower().endswith(".pdf"))


@router.post("/sessions/{session_id}/material", status_code=202)
def upload_material(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """PDF 업로드 → 저장 + queued → 202. 파싱은 백그라운드. 재업로드는 덮어쓰기."""
    if not _looks_like_pdf(file):
        raise ApiError(415, "UNSUPPORTED_MEDIA", "PDF 파일만 업로드할 수 있어요.")

    data = file.file.read()
    if len(data) == 0:
        raise ApiError(400, "EMPTY_FILE", "빈 파일이에요.")
    if len(data) > _MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "자료는 20MB 이하만 업로드할 수 있어요.")

    key = storage.material_key(session.id)
    storage.save(key, data)

    # 같은 세션 동시 업로드 직렬화 — 세션 행 잠금. 없으면 첫 업로드 시 두 요청이
    # 동시에 materials INSERT → PK(session_id) 충돌로 500 (재검증에서 실측).
    db.refresh(session, with_for_update=True)
    material = db.get(models.Material, session.id)
    if material is None:
        material = models.Material(session_id=session.id, file_name=file.filename or "material.pdf",
                                   file_size_bytes=len(data), storage_key=key)
        db.add(material)
    else:  # 재업로드 — 같은 key 덮어쓰기 + 상태 초기화
        material.file_name = file.filename or "material.pdf"
        material.file_size_bytes = len(data)
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
