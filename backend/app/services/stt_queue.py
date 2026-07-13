"""STT 직렬 큐 (작업 4-2, infra 제약 2).

STT 서버(GPU)는 한 번에 하나만 처리한다. 여러 세션이 동시에 STT를 돌리면 서로 막히거나
실패하므로, 백엔드에서 **단일 워커 스레드**가 큐에서 세션을 하나씩 꺼내 직렬 처리한다.

계획서는 asyncio.Queue + lifespan을 제안하지만 여기서는 스레드 큐 + 데몬 워커로 구현한다:
같은 '단일 워커 직렬' 보장을 주면서 lifespan 없이도(module-level TestClient 포함) 동작하고,
전사 함수가 동기(ffmpeg·httpx 블로킹)라 스레드 모델이 자연스럽다.

    recordings 업로드 라우터:  stt_queue.enqueue(session_id)   # 즉시 반환
    워커 스레드:               큐에서 하나씩 꺼내 _run_stt 실행 (한 번에 하나)
    테스트:                    stt_queue.join()  # 큐가 빌 때까지 대기
"""

import logging
import os
import queue as _queue_mod
import tempfile
import threading
from pathlib import Path

from sqlalchemy import select

from app.core import storage
from app.db import models
from app.db.enums import AsyncStatus, SessionStatus
from app.db.session import SessionLocal
from app.services.stt import UnsupportedMediaError, transcribe_recording

logger = logging.getLogger("rehearsal.stt_queue")

_queue: "_queue_mod.Queue[str]" = _queue_mod.Queue()
_worker: threading.Thread | None = None
_start_lock = threading.Lock()


# ── STT 잡 (워커가 한 번에 하나씩 실행) ───────────────────────────────

def _run_stt(session_id: str) -> None:
    """세션 녹음을 전사해 transcript를 갱신한다. 별도 DB 세션 사용.

    예외는 절대 밖으로 던지지 않는다(워커 루프를 죽이지 않도록) — 전부 failed로 흡수."""
    with SessionLocal() as db:
        transcript = db.get(models.Transcript, session_id)
        recording = db.get(models.Recording, session_id)
        if transcript is None or recording is None:  # 업로드 후 삭제된 경우
            return
        transcript.status = AsyncStatus.processing
        db.commit()

        tmp_path: str | None = None
        try:
            data = storage.load(recording.storage_key)
            suffix = Path(recording.storage_key).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(data)
                tmp_path = f.name
            segments = transcribe_recording(tmp_path)
        except UnsupportedMediaError as e:
            _fail(db, transcript, session_id, "UNSUPPORTED_MEDIA", str(e))
            return
        except Exception as e:
            # SttError·StorageError·예상못한 버그까지 전부 failed로 흡수한다.
            # 좁게 잡으면 그 외 예외에서 transcript가 processing에 영원히 stuck된다(재검증에서 발견).
            _fail(db, transcript, session_id, "STT_FAILED", str(e))  # retry 대상
            return
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        transcript.segments = segments
        transcript.status = AsyncStatus.ready
        transcript.error_code = None
        transcript.error_message = None
        db.commit()


def _fail(db, transcript: models.Transcript, session_id: str, code: str, message: str) -> None:
    transcript.status = AsyncStatus.failed
    transcript.error_code = code
    transcript.error_message = message[:500]
    # 세션도 failed로 (transcribing → failed). 이미 다른 상태로 옮겨졌으면 건드리지 않음.
    session = db.get(models.RehearsalSession, session_id)
    if session is not None and session.status == SessionStatus.transcribing:
        session.status = SessionStatus.failed
    db.commit()


# ── 큐 · 워커 ─────────────────────────────────────────────────────────

def _worker_loop() -> None:
    while True:
        session_id = _queue.get()
        try:
            _run_stt(session_id)
        except Exception:  # _run_stt가 흡수하지만 최후 방어 — 워커는 죽지 않는다
            logger.exception("STT 잡 처리 중 예외: %s", session_id)
        finally:
            _queue.task_done()


def start() -> None:
    """워커 스레드를 (없거나 죽었으면) 시작한다. enqueue가 자동 호출."""
    global _worker
    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="stt-worker", daemon=True)
            _worker.start()


def enqueue(session_id: str) -> None:
    """세션의 STT 잡을 큐에 넣는다. 워커가 직렬로 하나씩 처리."""
    start()
    _queue.put(session_id)


def join() -> None:
    """큐의 모든 잡이 처리될 때까지 대기 (테스트 동기화용)."""
    _queue.join()


def recover() -> None:
    """서버 재시작 시 미완료(queued/processing) 전사를 다시 큐에 넣는다.

    인메모리 큐는 재시작 시 비므로, 처리 중이던 잡이 영원히 멈추지 않게 한다.
    앱 시작 훅(main.py lifespan)에서 호출."""
    with SessionLocal() as db:
        ids = db.scalars(
            select(models.Transcript.session_id).where(
                models.Transcript.status.in_([AsyncStatus.queued, AsyncStatus.processing])
            )
        ).all()
    for sid in ids:
        enqueue(sid)
    if ids:
        logger.info("STT 큐 복구: 미완료 %d건 재등록", len(ids))
