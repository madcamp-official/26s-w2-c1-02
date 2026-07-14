"""발표 녹음 업로드 + STT 잡 (작업 4-1, api-spec §4.3 · infra 제약 2).

업로드는 파일 저장 + recordings(ready)·transcripts(queued) 행 생성 + 세션을
transcribing으로 전이한 뒤 **즉시 202**. 실제 STT는 백그라운드에서 실행되고
transcripts.status 폴링으로 확인한다 (queued → processing → ready|failed).

⚠️ STT 서버는 직렬 처리(infra 제약 2)이므로 STT 잡은 세션마다 동시에 돌면 안 된다.
지금은 BackgroundTasks로 연결하지만, 작업 4-2에서 **단일 워커 직렬 큐**로 교체한다
(enqueue 지점만 바뀌고 _run_stt 잡 자체는 그대로 재사용).
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import require_session_member, require_session_owner
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus, SessionStatus
from app.db.session import get_db
from app.schemas.session import ErrorInfo, TranscriptDetail, TranscriptSegmentOut
from app.services import stt_queue
from app.services.session_state import advance_status
from app.services.stt import seconds_to_ts

router = APIRouter(tags=["recordings"])

_MAX_BYTES = 200 * 1024 * 1024  # §1.3: 200MB
_MAX_DURATION = 3600            # §1.3: 60분
# mime → 확장자 (recordings.mime_type 저장값 · storage_key 확장자)
_ALLOWED_AUDIO = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a",
}
_EXT_BY_NAME = {".mp3": "mp3", ".wav": "wav", ".m4a": "m4a", ".mp4": "m4a"}

# 녹음 업로드를 받아들이는 세션 상태 (질의응답 단계 이후엔 거부)
_UPLOADABLE = {SessionStatus.draft, SessionStatus.recording_in_progress,
               SessionStatus.transcribing, SessionStatus.failed}
# 실시간 녹음 청크를 받아들이는 세션 상태 (첫 청크가 draft를 recording_in_progress로 전이)
_CHUNK_ALLOWED = {SessionStatus.draft, SessionStatus.recording_in_progress}


def _audio_ext(file: UploadFile) -> str | None:
    """허용된 오디오면 확장자, 아니면 None. mime 우선, 없으면 파일명 확장자."""
    if file.content_type in _ALLOWED_AUDIO:
        return _ALLOWED_AUDIO[file.content_type]
    if file.filename:
        return _EXT_BY_NAME.get(Path(file.filename).suffix.lower())
    return None


def _store_full_recording(
    db: Session,
    session: models.RehearsalSession,
    *,
    file: UploadFile,
    data: bytes,
    ext: str,
    duration_seconds: int,
    started_at: datetime | None,
    ended_at: datetime | None,
    total_chunks: int | None,
) -> str | None:
    """전체 녹음 파일 저장 + recordings/transcripts 업서트 + transcribing 전이.

    일괄 업로드(§4.3)와 실시간 complete(§4.3.1)가 공유. 반환값은 확장자 변경
    재업로드로 고아가 된 옛 storage_key(정리 대상) 또는 None. **커밋은 호출자**가 한다.
    total_chunks는 청크 complete만 값을 넣고 일괄 경로는 None(비청크 의미)."""
    key = storage.recording_key(session.id, ext)
    storage.save(key, data)

    # 동시 업로드 직렬화 (material과 동일 — 1:1 행 PK 충돌 방지)
    db.refresh(session, with_for_update=True)

    recording = db.get(models.Recording, session.id)
    # 재업로드로 확장자가 바뀌면 옛 파일이 고아로 남으므로 키를 기억해뒀다 정리한다.
    old_key = recording.storage_key if recording is not None else None
    if recording is None:
        recording = models.Recording(session_id=session.id, storage_key=key)
        db.add(recording)
    recording.status = AsyncStatus.ready
    recording.file_name = file.filename or f"recording.{ext}"
    recording.file_size_bytes = len(data)
    recording.mime_type = file.content_type or f"audio/{ext}"
    recording.duration_seconds = duration_seconds
    recording.storage_key = key
    recording.started_at = started_at
    recording.ended_at = ended_at
    recording.total_chunks = total_chunks

    transcript = db.get(models.Transcript, session.id)
    if transcript is None:
        transcript = models.Transcript(session_id=session.id)
        db.add(transcript)
    transcript.status = AsyncStatus.queued
    transcript.segments = None
    transcript.error_code = None
    transcript.error_message = None

    # 세션 상태 → transcribing (이미 transcribing이면 유지; failed면 재시도 경로)
    if session.status != SessionStatus.transcribing:
        advance_status(session, SessionStatus.transcribing)

    return old_key if (old_key and old_key != key) else None


@router.post("/sessions/{session_id}/recording/start", status_code=202)
def start_recording(
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """실시간 녹음 시작 표시(api-spec §4.3, 선택) → draft를 recording_in_progress로 전이.

    이어하기(resume) 감지용. **멱등** — 이미 recording_in_progress면 전이 없이 202.
    started_at은 스키마상 오디오 파일과 함께 오므로 여기서 저장하지 않고
    `/recording/complete`(또는 `/recording`)에서 확정한다. 첫 청크(`/recording/chunks`)도
    같은 전이를 수행하므로 이 호출은 선택이다(미호출 시 첫 청크가 대체)."""
    if session.status == SessionStatus.recording_in_progress:
        return {"status": SessionStatus.recording_in_progress.value}  # 멱등 no-op
    if session.status != SessionStatus.draft:
        raise ApiError(409, "RECORDING_NOT_ALLOWED", "지금은 녹음을 시작할 수 없어요.")
    advance_status(session, SessionStatus.recording_in_progress)
    db.commit()
    return {"status": SessionStatus.recording_in_progress.value}


@router.post("/sessions/{session_id}/recording", status_code=202)
def upload_recording(
    file: UploadFile = File(...),
    duration_seconds: int = Form(...),
    started_at: datetime | None = Form(None),
    ended_at: datetime | None = Form(None),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """녹음 업로드 → 저장 + transcribing 전이 + STT 큐 → 202. 재업로드는 덮어쓰기."""
    ext = _audio_ext(file)
    if ext is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "mp3 · wav · m4a 파일만 업로드할 수 있어요.")
    if duration_seconds < 0 or duration_seconds > _MAX_DURATION:
        raise ApiError(400, "RECORDING_TOO_LONG", "녹음은 60분 이하만 가능해요.")

    data = file.file.read()
    if len(data) == 0:
        raise ApiError(400, "EMPTY_FILE", "빈 파일이에요.")
    if len(data) > _MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "녹음은 200MB 이하만 업로드할 수 있어요.")

    if session.status not in _UPLOADABLE:
        raise ApiError(409, "RECORDING_NOT_ALLOWED",
                       "이미 질의응답이 시작돼 녹음을 올릴 수 없어요.")

    old_key = _store_full_recording(
        db, session, file=file, data=data, ext=ext, duration_seconds=duration_seconds,
        started_at=started_at, ended_at=ended_at, total_chunks=None,
    )
    db.commit()

    if old_key:  # 확장자 변경 재업로드 → 옛 파일 정리
        storage.delete(old_key)
    stt_queue.enqueue(session.id)  # STT 직렬 큐 (워커가 한 번에 하나씩 처리)
    return {"status": AsyncStatus.queued.value}


@router.post("/sessions/{session_id}/recording/chunks", status_code=202)
def upload_recording_chunk(
    file: UploadFile = File(...),
    seq: int = Form(...),
    offset_seconds: float = Form(...),
    overlap_seconds: float = Form(0.0),
    duration_seconds: float = Form(...),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """실시간 녹음 청크 업로드(api-spec §4.3.1) → 청크 STT 잡 큐 → 202 {received_seq}.

    같은 seq 재전송은 멱등하게 덮어쓴다(①). 청크 STT 결과는 recording_chunks에
    청크-로컬 타임스탬프로 쌓이고, /recording/complete에서 병합된다(④).
    청크가 전부 유실돼도 complete의 전체 파일이 안전망이다(②)."""
    ext = _audio_ext(file)
    if ext is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "wav · mp3 · m4a 청크만 업로드할 수 있어요.")
    if seq < 0:
        raise ApiError(400, "VALIDATION", "seq는 0 이상이어야 해요.")
    if offset_seconds < 0 or overlap_seconds < 0 or duration_seconds <= 0:
        raise ApiError(400, "VALIDATION", "청크 시간 메타데이터가 올바르지 않아요.")

    data = file.file.read()
    if len(data) == 0:
        raise ApiError(400, "EMPTY_FILE", "빈 청크예요.")
    if len(data) > _MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "청크가 너무 커요.")

    if session.status not in _CHUNK_ALLOWED:
        raise ApiError(409, "RECORDING_NOT_ALLOWED", "지금은 녹음 청크를 받을 수 없어요.")

    key = storage.recording_chunk_key(session.id, seq, ext)
    storage.save(key, data)  # 같은 seq 재전송 → 같은 키 덮어쓰기

    # 첫 청크가 draft를 recording_in_progress로 전이 (recording/start 미호출 대비)
    if session.status == SessionStatus.draft:
        advance_status(session, SessionStatus.recording_in_progress)

    # 멱등 upsert(①): 같은 (session_id, seq) 재전송은 덮어쓰고 status를 queued로 되돌려 재큐잉
    vals = dict(
        session_id=session.id, seq=seq,
        offset_seconds=offset_seconds, overlap_seconds=overlap_seconds,
        duration_seconds=duration_seconds, storage_key=key,
        status=AsyncStatus.queued, segments=None, error_code=None, error_message=None,
    )
    reset = {k: v for k, v in vals.items() if k not in ("session_id", "seq")}
    db.execute(
        pg_insert(models.RecordingChunk).values(**vals)
        .on_conflict_do_update(index_elements=["session_id", "seq"], set_=reset)
    )

    # 청크 수신 중 transcript는 processing (세션은 recording_in_progress 유지)
    transcript = db.get(models.Transcript, session.id)
    if transcript is None:
        transcript = models.Transcript(session_id=session.id, status=AsyncStatus.processing)
        db.add(transcript)
    else:
        transcript.status = AsyncStatus.processing
        transcript.error_code = None
        transcript.error_message = None

    db.commit()
    stt_queue.enqueue_chunk(session.id, seq)  # 직렬 워커 공유
    return {"received_seq": seq}


@router.post("/sessions/{session_id}/recording/complete", status_code=202)
def complete_recording(
    file: UploadFile = File(...),
    total_chunks: int = Form(...),
    duration_seconds: float = Form(...),
    started_at: datetime | None = Form(None),
    ended_at: datetime | None = Form(None),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """실시간 녹음 종료(api-spec §4.3.1): 재생용 전체 파일 저장 + 병합 트리거 → 202.

    청크가 전부 도착했으면 저장된 청크 세그먼트를 병합, 누락/실패가 있으면 이 전체
    파일로 재전사한다(안전망 ②) — 즉 청크가 전부 유실돼도 일괄 업로드와 동일 결과."""
    ext = _audio_ext(file)
    if ext is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "mp3 · wav · m4a 파일만 업로드할 수 있어요.")
    if duration_seconds < 0 or duration_seconds > _MAX_DURATION:
        raise ApiError(400, "RECORDING_TOO_LONG", "녹음은 60분 이하만 가능해요.")
    if total_chunks < 0:
        raise ApiError(400, "VALIDATION", "total_chunks는 0 이상이어야 해요.")

    data = file.file.read()
    if len(data) == 0:
        raise ApiError(400, "EMPTY_FILE", "빈 파일이에요.")
    if len(data) > _MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "녹음은 200MB 이하만 업로드할 수 있어요.")

    if session.status not in _UPLOADABLE:
        raise ApiError(409, "RECORDING_NOT_ALLOWED",
                       "이미 질의응답이 시작돼 녹음을 올릴 수 없어요.")

    old_key = _store_full_recording(
        db, session, file=file, data=data, ext=ext, duration_seconds=round(duration_seconds),
        started_at=started_at, ended_at=ended_at, total_chunks=total_chunks,
    )
    db.commit()

    if old_key:
        storage.delete(old_key)
    stt_queue.enqueue_complete(session.id)  # 병합 잡(청크 잡 뒤에 직렬 실행)
    return {"status": AsyncStatus.queued.value}


@router.get("/sessions/{session_id}/transcript", response_model=TranscriptDetail)
def get_transcript(
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> TranscriptDetail:
    """전사 상태 + 세그먼트 (멤버). 저장은 초 float, 응답은 ts:"MM:SS" (§4.3)."""
    transcript = db.get(models.Transcript, session.id)
    if transcript is None:
        raise ApiError(404, "TRANSCRIPT_NOT_FOUND", "전사가 아직 없어요. (녹음 업로드 필요)")

    segments = None
    if transcript.segments is not None:
        segments = [
            TranscriptSegmentOut(ts=seconds_to_ts(s["start"]), text=s["text"])
            for s in transcript.segments
        ]
    error = None
    if transcript.error_code:
        error = ErrorInfo(code=transcript.error_code, message=transcript.error_message or "")
    return TranscriptDetail(status=transcript.status, segments=segments, error=error)


@router.post("/sessions/{session_id}/transcript/retry", status_code=202)
def retry_transcript(
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """전사 재시도 (owner). 실패한 전사를 queued로 되돌리고 STT 큐 재투입.

    녹음 파일은 storage에 남아 있으므로 재전사만 하면 된다. failed일 때만 의미가 있어
    ready/processing 중 재시도는 409로 막는다."""
    transcript = db.get(models.Transcript, session.id)
    if transcript is None:
        raise ApiError(404, "TRANSCRIPT_NOT_FOUND", "전사가 아직 없어요.")
    if transcript.status != AsyncStatus.failed:
        raise ApiError(409, "TRANSCRIPT_NOT_RETRYABLE", "실패한 전사만 다시 시도할 수 있어요.")

    transcript.status = AsyncStatus.queued
    transcript.error_code = None
    transcript.error_message = None
    if session.status == SessionStatus.failed:  # STT 실패로 failed였다면 transcribing 복귀
        advance_status(session, SessionStatus.transcribing)
    db.commit()

    stt_queue.enqueue(session.id)
    return {"status": AsyncStatus.queued.value}
