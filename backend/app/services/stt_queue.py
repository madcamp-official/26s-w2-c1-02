"""STT 직렬 큐 (작업 4-2 · Step 3 작업 0, infra 제약 2).

STT 서버(GPU)는 한 번에 하나만 처리한다. 여러 세션이 동시에 STT를 돌리면 서로 막히거나
실패하므로, 백엔드에서 **단일 워커 스레드**가 큐에서 잡을 하나씩 꺼내 직렬 처리한다.

계획서는 asyncio.Queue + lifespan을 제안하지만 여기서는 스레드 큐 + 데몬 워커로 구현한다:
같은 '단일 워커 직렬' 보장을 주면서 lifespan 없이도(module-level TestClient 포함) 동작하고,
전사 함수가 동기(ffmpeg·httpx 블로킹)라 스레드 모델이 자연스럽다.

**Step 3 작업 0:** 발표 전사와 답변 전사는 **같은 워커 하나**를 공유해야 GPU에서 겹치지
않는다. 그래서 큐 항목을 `(kind, id)`로 확장하고 워커가 kind로 분기한다:
    ("recording", session_id) → _run_stt        (발표 전사, 이 모듈)
    ("answer",    question_id) → qna_jobs.run_answer_stt  (답변 전사 + 꼬리질문, 지연 임포트)

    발표 녹음 라우터:  stt_queue.enqueue(session_id)          # = enqueue_recording (호환)
    답변 라우터:       stt_queue.enqueue_answer(question_id)
    워커 스레드:       큐에서 하나씩 꺼내 kind별 잡 실행 (한 번에 하나)
    테스트:            stt_queue.join()  # 큐가 빌 때까지 대기
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
from app.db.enums import AnswerStatus, AsyncStatus, SessionStatus
from app.db.session import SessionLocal
from app.services.stt import (
    UnsupportedMediaError,
    merge_chunk_segments,
    transcribe_recording,
)

logger = logging.getLogger("rehearsal.stt_queue")

# 큐 항목: (kind, id) — kind ∈ {"recording", "answer"}
_queue: "_queue_mod.Queue[tuple[str, str]]" = _queue_mod.Queue()
_worker: threading.Thread | None = None
_start_lock = threading.Lock()


# ── STT 잡 (워커가 한 번에 하나씩 실행) ───────────────────────────────

def _transcribe_key(storage_key: str) -> list[dict]:
    """storage_key의 오디오를 임시파일로 받아 전사한다(청크 병합 아님).

    발표 전체·청크 하나·complete 폴백이 공유하는 temp-file + ffmpeg 경로.
    예외(UnsupportedMediaError·SttError·StorageError)는 그대로 올린다 — 호출자가 흡수."""
    data = storage.load(storage_key)
    suffix = Path(storage_key).suffix or ".bin"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            tmp_path = f.name
        return transcribe_recording(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


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

        try:
            segments = _transcribe_key(recording.storage_key)
        except UnsupportedMediaError as e:
            _fail(db, transcript, session_id, "UNSUPPORTED_MEDIA", str(e))
            return
        except Exception as e:
            # SttError·StorageError·예상못한 버그까지 전부 failed로 흡수한다.
            # 좁게 잡으면 그 외 예외에서 transcript가 processing에 영원히 stuck된다(재검증에서 발견).
            _fail(db, transcript, session_id, "STT_FAILED", str(e))  # retry 대상
            return

        transcript.segments = segments
        transcript.status = AsyncStatus.ready
        transcript.error_code = None
        transcript.error_message = None
        db.commit()


def _run_chunk_stt(session_id: str, seq: int) -> None:
    """실시간 녹음 청크 하나를 전사해 recording_chunks.segments(청크-로컬)에 저장한다.

    청크 실패는 세션·transcript를 failed로 만들지 않는다 — /recording/complete의
    전체 파일이 안전망이므로 누락 청크는 거기서 재전사된다(api-spec §4.3.1 ②).
    예외는 밖으로 던지지 않는다(워커 보호)."""
    with SessionLocal() as db:
        chunk = db.get(models.RecordingChunk, (session_id, seq))
        if chunk is None:  # 세션/청크 삭제됨
            return
        chunk.status = AsyncStatus.processing
        db.commit()

        try:
            # 청크는 ≤64초라 transcribe_recording 내부에서 재분할되지 않는다
            # → 청크-로컬 타임스탬프(offset 0) 그대로 반환. 병합은 /complete에서.
            segments = _transcribe_key(chunk.storage_key)
        except UnsupportedMediaError as e:
            _fail_chunk(db, chunk, "UNSUPPORTED_MEDIA", str(e))
            return
        except Exception as e:  # SttError·StorageError·기타 — 청크만 failed로 흡수
            _fail_chunk(db, chunk, "STT_FAILED", str(e))
            return

        chunk.segments = segments
        chunk.status = AsyncStatus.ready
        chunk.error_code = None
        chunk.error_message = None
        db.commit()


def _fail_chunk(db, chunk: "models.RecordingChunk", code: str, message: str) -> None:
    """청크 하나만 failed로 표시. 세션·transcript는 건드리지 않는다(전체 파일이 안전망)."""
    chunk.status = AsyncStatus.failed
    chunk.error_code = code
    chunk.error_message = message[:500]
    db.commit()


def _run_complete(session_id: str) -> None:
    """실시간 녹음 종료 병합(api-spec §4.3.1). 별도 DB 세션 사용.

    청크가 total_chunks만큼 모두 ready면 저장된 청크 세그먼트를 앞겹침 병합(③),
    하나라도 누락/실패면 complete의 전체 파일을 재전사한다(안전망 ②).
    예외는 밖으로 던지지 않는다 — 전부 failed로 흡수."""
    with SessionLocal() as db:
        transcript = db.get(models.Transcript, session_id)
        recording = db.get(models.Recording, session_id)
        if transcript is None or recording is None:  # 삭제된 경우
            return
        transcript.status = AsyncStatus.processing
        db.commit()

        chunks = db.scalars(
            select(models.RecordingChunk)
            .where(models.RecordingChunk.session_id == session_id)
            .order_by(models.RecordingChunk.seq)
        ).all()
        total = recording.total_chunks
        received = {c.seq for c in chunks}
        # 완비(연속 0..total−1) + 전부 ready 여야 청크 병합, 아니면 전체 파일 폴백(②)
        all_ready = (
            total is not None
            and received == set(range(total))
            and all(c.status == AsyncStatus.ready for c in chunks)
        )

        try:
            if all_ready:
                segments = merge_chunk_segments([
                    {"offset": c.offset_seconds, "overlap": c.overlap_seconds,
                     "segments": c.segments or []}
                    for c in chunks
                ])
            else:
                segments = _transcribe_key(recording.storage_key)
        except UnsupportedMediaError as e:
            _fail(db, transcript, session_id, "UNSUPPORTED_MEDIA", str(e))
            return
        except Exception as e:
            _fail(db, transcript, session_id, "STT_FAILED", str(e))
            return

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
        kind, item_id = _queue.get()
        try:
            if kind == "recording":
                _run_stt(item_id)
            elif kind == "chunk":
                # item_id = "<session_id>:<seq>" (session_id에 ':'는 없음)
                sid, seq_str = item_id.rsplit(":", 1)
                _run_chunk_stt(sid, int(seq_str))
            elif kind == "complete":
                _run_complete(item_id)
            elif kind == "answer":
                # 답변 전사+꼬리질문은 Q&A 도메인 로직 — 순환 임포트를 피해 지연 임포트.
                from app.services.qna_jobs import run_answer_stt

                run_answer_stt(item_id)
            else:  # 방어 — 알 수 없는 kind는 로그만
                logger.error("알 수 없는 STT 잡 종류: %s", kind)
        except Exception:  # 잡이 흡수하지만 최후 방어 — 워커는 죽지 않는다
            logger.exception("STT 잡 처리 중 예외: %s %s", kind, item_id)
        finally:
            _queue.task_done()


def start() -> None:
    """워커 스레드를 (없거나 죽었으면) 시작한다. enqueue가 자동 호출."""
    global _worker
    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="stt-worker", daemon=True)
            _worker.start()


def enqueue_recording(session_id: str) -> None:
    """세션 발표 녹음의 STT 잡을 큐에 넣는다. 워커가 직렬로 하나씩 처리."""
    start()
    _queue.put(("recording", session_id))


# 하위 호환 별칭 — 기존 recordings 라우터·테스트가 enqueue(session_id)를 그대로 쓴다.
enqueue = enqueue_recording


def enqueue_chunk(session_id: str, seq: int) -> None:
    """실시간 녹음 청크의 STT 잡을 큐에 넣는다(api-spec §4.3.1).

    발표·답변 전사와 **같은 직렬 워커**를 공유한다 — 발표 중엔 답변 STT가 없어
    경합이 없고, GPU 직렬 제약(infra 제약 2)을 그대로 지킨다."""
    start()
    _queue.put(("chunk", f"{session_id}:{seq}"))


def enqueue_complete(session_id: str) -> None:
    """실시간 녹음 종료(/recording/complete) 병합 잡을 큐에 넣는다(api-spec §4.3.1).

    청크 STT 잡들 뒤에 직렬로 실행되어, 앞선 청크 결과가 반영된 뒤 병합된다."""
    start()
    _queue.put(("complete", session_id))


def enqueue_answer(question_id: str) -> None:
    """답변 오디오의 STT 잡을 큐에 넣는다. 발표 전사와 같은 워커를 공유(직렬)."""
    start()
    _queue.put(("answer", question_id))


def join() -> None:
    """큐의 모든 잡이 처리될 때까지 대기 (테스트 동기화용)."""
    _queue.join()


def recover() -> None:
    """서버 재시작 시 미완료 전사(발표·답변)를 다시 큐에 넣는다.

    인메모리 큐는 재시작 시 비므로, 처리 중이던 잡이 영원히 멈추지 않게 한다.
    앱 시작 훅(main.py lifespan)에서 호출."""
    with SessionLocal() as db:
        rec_ids = db.scalars(
            select(models.Transcript.session_id).where(
                models.Transcript.status.in_([AsyncStatus.queued, AsyncStatus.processing])
            )
        ).all()
        # 답변 STT는 제출 즉시 processing으로 시작하므로 processing만 복구 대상.
        ans_ids = db.scalars(
            select(models.Answer.question_id).where(
                models.Answer.status == AnswerStatus.processing
            )
        ).all()
        # 실시간 녹음 청크: 미완료(queued/processing) 청크를 다시 큐에 (§4.3.1)
        chunk_keys = db.execute(
            select(models.RecordingChunk.session_id, models.RecordingChunk.seq).where(
                models.RecordingChunk.status.in_([AsyncStatus.queued, AsyncStatus.processing])
            )
        ).all()
    for sid in rec_ids:
        enqueue_recording(sid)
    for qid in ans_ids:
        enqueue_answer(qid)
    for sid, seq in chunk_keys:
        enqueue_chunk(sid, seq)
    if rec_ids or ans_ids or chunk_keys:
        logger.info("STT 큐 복구: 발표 %d건 · 답변 %d건 · 청크 %d건 재등록",
                    len(rec_ids), len(ans_ids), len(chunk_keys))
