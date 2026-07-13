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
from sqlalchemy.orm import Session

from app.api.deps import require_session_owner
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus, SessionStatus
from app.db.session import get_db
from app.services import stt_queue
from app.services.session_state import advance_status

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


def _audio_ext(file: UploadFile) -> str | None:
    """허용된 오디오면 확장자, 아니면 None. mime 우선, 없으면 파일명 확장자."""
    if file.content_type in _ALLOWED_AUDIO:
        return _ALLOWED_AUDIO[file.content_type]
    if file.filename:
        return _EXT_BY_NAME.get(Path(file.filename).suffix.lower())
    return None


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

    db.commit()

    if old_key and old_key != key:  # 확장자 변경 재업로드 → 옛 파일 정리
        storage.delete(old_key)
    stt_queue.enqueue(session.id)  # STT 직렬 큐 (워커가 한 번에 하나씩 처리)
    return {"status": AsyncStatus.queued.value}
