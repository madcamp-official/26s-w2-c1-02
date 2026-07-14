"""Q&A 백그라운드 잡 — 질문 생성 + TTS + 답변 STT + 꼬리질문 (Step 3 작업 2·3·4).

- `run_generate(session_id)`      : BackgroundTasks — LLM 질문 생성 → questions 저장 →
                                    qna 전이 → 각 질문 TTS 인라인 합성.
- `run_answer_stt(question_id)`   : STT 워커 스레드(stt_queue) — 답변 전사 → 꼬리질문 판정 →
                                    자식 질문 삽입 / 다음 질문 이동 / 자동 종료.
- `end_session(db, session, reason)` : qna/end·자동 종료 공용 — completed 전이 + 리포트 큐.

두 잡 모두 요청과 **별도 DB 세션**(SessionLocal)을 열고, 예외를 밖으로 던지지 않는다
(BackgroundTask/워커를 죽이지 않도록 — 전부 failed로 흡수). TTS는 질문이 생기는 곳에서
**인라인** 합성한다(꼬리질문은 워커 스레드에서 생성되어 BackgroundTasks를 못 쓰므로 통일).
LLM 제공자는 async라 sync 잡에서 asyncio.run으로 호출한다.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core import storage
from app.db import models
from app.db.enums import (
    AnswerKind,
    AnswerStatus,
    AsyncStatus,
    EndedReason,
    FollowUpStatus,
    SessionStatus,
)
from app.db.session import SessionLocal
from app.services import report_jobs
from app.services.llm.base import MAX_FOLLOW_UP_DEPTH
from app.services.llm.factory import get_llm_provider
from app.services.session_state import advance_status
from app.services.stt import UnsupportedMediaError, transcribe_recording
from app.services.tts import TtsError, synthesize_question

logger = logging.getLogger("rehearsal.qna_jobs")

_TTS_TIMEOUT = 120.0  # 직렬 큐 대기 포함 (tts.REQUEST_TIMEOUT과 동일 성격)


# ── 작업 2. 질문 생성 잡 (BackgroundTasks) ────────────────────────────

def run_generate(session_id: str) -> None:
    """세션의 질문을 생성해 저장하고 qna로 전이한 뒤, 질문별 TTS를 인라인 합성한다.

    응답 후 실행되므로 자기 DB 세션을 연다. LLM 실패는 세션을 failed로 흡수(재시도 경로)."""
    with SessionLocal() as db:
        session = db.get(models.RehearsalSession, session_id)
        if session is None:  # generate 접수 후 세션 삭제된 경우
            return
        material = db.get(models.Material, session_id)
        transcript = db.get(models.Transcript, session_id)
        slides = material.slides if material is not None else None
        segments = transcript.segments if transcript is not None else None

        try:
            provider = get_llm_provider()
            drafts = asyncio.run(provider.generate_questions(
                speech_name=session.name, slides=slides, transcript=segments,
                personas=list(session.personas), count=session.question_count,
            ))
        except Exception:
            logger.exception("질문 생성 실패: %s", session_id)
            if session.status == SessionStatus.generating_questions:
                session.status = SessionStatus.failed
            db.commit()
            return

        first_id: str | None = None
        for i, d in enumerate(drafts, start=1):
            q = models.Question(
                session_id=session_id, parent_id=None, follow_up_depth=0,
                order_index=i, persona=d.persona, strategy=d.strategy,
                text=d.text, evidence=d.evidence.model_dump(),
                tts_status=AsyncStatus.queued,
            )
            db.add(q)
            db.flush()  # q.id 확보 (current_question_id·TTS 저장에 필요)
            if first_id is None:
                first_id = q.id

        session.current_question_id = first_id
        advance_status(session, SessionStatus.qna)  # generating_questions → qna
        db.commit()

        _synthesize_session_tts(db, session_id)  # 작업 3: 질문 TTS 인라인


# ── 작업 3. 질문 TTS (인라인, 세션 내 직렬) ───────────────────────────

def _synthesize_session_tts(db, session_id: str) -> None:
    """세션의 queued TTS 질문을 하나의 httpx 클라이언트를 공유해 순차 합성 (A6)."""
    questions = db.scalars(
        select(models.Question)
        .where(models.Question.session_id == session_id,
               models.Question.tts_status == AsyncStatus.queued)
        .order_by(models.Question.order_index)
    ).all()
    if not questions:
        return
    base_url = os.environ.get("TTS_BASE_URL", "http://localhost:8100")
    with httpx.Client(base_url=base_url, timeout=_TTS_TIMEOUT) as client:
        for q in questions:
            _synthesize_one(db, q, client=client)


def _synthesize_one(db, question: models.Question, *, client: httpx.Client | None = None) -> None:
    """질문 1건 TTS 합성 → wav 저장 + tts_status=ready. 실패는 failed로 흡수(폴링 노출)."""
    question.tts_status = AsyncStatus.processing
    db.commit()
    try:
        wav = synthesize_question(question.text, persona=question.persona, client=client)
    except Exception as e:  # TtsError·예상못한 버그 전부 흡수 (processing stuck 방지)
        question.tts_status = AsyncStatus.failed
        question.tts_error_code = "TTS_FAILED"
        question.tts_error_message = str(e)[:500]
        db.commit()
        return
    key = storage.tts_key(question.session_id, question.id)
    storage.save(key, wav)
    question.tts_storage_key = key
    question.tts_status = AsyncStatus.ready
    question.tts_error_code = None
    question.tts_error_message = None
    db.commit()


# ── 작업 4. 답변 STT + 꼬리질문 (STT 워커 스레드) ─────────────────────

def run_answer_stt(question_id: str) -> None:
    """답변 오디오를 전사하고 꼬리질문을 판정한다. stt_queue 워커가 직렬 실행.

    예외는 밖으로 던지지 않는다(워커 보호) — 전부 answer.failed로 흡수."""
    with SessionLocal() as db:
        answer = db.get(models.Answer, question_id)
        question = db.get(models.Question, question_id)
        if answer is None or question is None:  # 제출 후 삭제된 경우
            return

        tmp_path: str | None = None
        try:
            data = storage.load(answer.audio_storage_key)
            suffix = Path(answer.audio_storage_key).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(data)
                tmp_path = f.name
            segments = transcribe_recording(tmp_path)
        except UnsupportedMediaError as e:
            _fail_answer(db, answer, "UNSUPPORTED_MEDIA", str(e))
            return
        except Exception as e:
            # SttError·StorageError·예상못한 버그까지 전부 failed로 흡수(재제출로 재시도).
            _fail_answer(db, answer, "STT_FAILED", str(e))
            return
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        answer.text = " ".join(s["text"] for s in segments).strip()
        answer.status = AnswerStatus.ready
        answer.error_code = None
        answer.error_message = None
        db.commit()

        _decide_follow_up_and_advance(db, question, answer)

        # 마지막 답변으로 자동 종료됐으면(A7) 리포트를 인라인 생성 — 꼬리질문 TTS와
        # 같은 규칙(워커 스레드라 BackgroundTasks를 못 씀). run_report는 자기 세션을 연다.
        session = db.get(models.RehearsalSession, question.session_id)
        if session is not None and session.status == SessionStatus.completed:
            report_jobs.run_report(session.id)


def _fail_answer(db, answer: models.Answer, code: str, message: str) -> None:
    """답변 STT 실패 — failed + follow_up 없음. current는 그대로(같은 질문 재제출)."""
    answer.status = AnswerStatus.failed
    answer.error_code = code
    answer.error_message = message[:500]
    answer.follow_up_status = FollowUpStatus.none
    db.commit()


def _decide_follow_up_and_advance(db, question: models.Question, answer: models.Answer) -> None:
    """꼬리질문 판정(깊이 1 제한, A11) → 자식 삽입 후 current 이동, 없으면 다음 1차 질문."""
    session = db.get(models.RehearsalSession, question.session_id)
    child: models.Question | None = None

    can_follow = (
        question.follow_up_depth < MAX_FOLLOW_UP_DEPTH
        and answer.kind == AnswerKind.answered
    )
    if can_follow:
        try:
            provider = get_llm_provider()
            draft = asyncio.run(provider.follow_up(
                question=question.text, answer=answer.text or "",
                depth=question.follow_up_depth, persona=question.persona,
            ))
        except Exception:
            logger.exception("꼬리질문 생성 실패: %s", question.id)
            draft = None
        if draft is not None:
            child = models.Question(
                session_id=question.session_id, parent_id=question.id,
                follow_up_depth=question.follow_up_depth + 1,
                order_index=question.order_index,  # 꼬리는 부모와 같은 순번(부모 뒤 표시)
                persona=question.persona, strategy=draft.strategy,
                text=draft.text, evidence=draft.evidence.model_dump(),
                tts_status=AsyncStatus.queued,
            )
            db.add(child)
            db.flush()  # child.id 확보

    if child is not None:
        answer.follow_up_status = FollowUpStatus.generated
        session.current_question_id = child.id
        db.commit()
        _synthesize_one(db, child)  # 꼬리질문 TTS 인라인
    else:
        answer.follow_up_status = FollowUpStatus.none
        _advance_to_next_primary(db, session, question)
        db.commit()


def _advance_to_next_primary(
    db, session: models.RehearsalSession, question: models.Question,
    *, end_reason: EndedReason = EndedReason.count_reached,
) -> None:
    """current를 다음 1차 질문으로. 더 없으면 자동 종료.

    종료 사유는 기본 count_reached(질의 수 도달). pass(reason=timeout)로 마지막 질문을
    넘긴 경우엔 호출자가 timeout을 넘긴다 (A12: 마지막이 시간초과면 timeout)."""
    next_order = question.order_index + 1  # 꼬리질문도 order_index=부모 순번이라 동일 공식
    nxt = db.scalar(
        select(models.Question).where(
            models.Question.session_id == session.id,
            models.Question.parent_id.is_(None),
            models.Question.order_index == next_order,
        )
    )
    if nxt is not None:
        session.current_question_id = nxt.id
    else:
        end_session(db, session, end_reason)


# ── 작업 4-3. 답변 패스 (동기 — STT 없이 바로 다음) ───────────────────

def record_pass(db, session: models.RehearsalSession, question: models.Question,
                reason: str) -> None:
    """질문을 패스한다: passed 답변 기록 + 꼬리질문 생략 + 다음 1차 질문 이동.

    커밋은 이 함수가 한다. 마지막 질문을 reason=timeout으로 넘기면 종료 사유가 timeout,
    그 외(user 등)는 count_reached (A12). 이전 답변 오디오가 있으면 커밋 후 정리."""
    answer = db.get(models.Answer, question.id)
    old_key = answer.audio_storage_key if answer is not None else None
    if answer is None:
        answer = models.Answer(
            question_id=question.id, kind=AnswerKind.passed,
            status=AnswerStatus.ready, audio_storage_key=None,
            follow_up_status=FollowUpStatus.none,
        )
        db.add(answer)
    else:  # answered(실패 등) → passed로 덮어쓰기
        answer.kind = AnswerKind.passed
        answer.status = AnswerStatus.ready
        answer.audio_storage_key = None
        answer.duration_seconds = None
        answer.text = None
        answer.follow_up_status = FollowUpStatus.none
        answer.error_code = None
        answer.error_message = None

    end_reason = EndedReason.timeout if reason == "timeout" else EndedReason.count_reached
    _advance_to_next_primary(db, session, question, end_reason=end_reason)
    db.commit()

    if old_key:  # 패스 전 올렸던 답변 오디오 고아 정리 (best-effort)
        storage.delete(old_key)


# ── 종료 + 리포트 큐 (qna/end·자동 종료 공용) ─────────────────────────

def end_session(db, session: models.RehearsalSession, reason: EndedReason) -> None:
    """세션을 completed로 전이하고 종료 사유를 기록한 뒤 리포트를 큐에 올린다 (A7).

    커밋은 호출자 몫. 여기선 reports 행을 queued로만 만든다 — 실제 생성
    (report_jobs.run_report)은 호출자가 **커밋 후** 트리거한다(qna/end·pass 라우트는
    BackgroundTasks, 답변 STT 자동 종료는 워커에서 인라인)."""
    if session.status == SessionStatus.qna:
        advance_status(session, SessionStatus.completed)
    session.qna_ended_reason = reason
    session.current_question_id = None
    _enqueue_report(db, session.id)


def _enqueue_report(db, session_id: str) -> None:
    """reports 행을 queued로 생성/초기화 (Step 4 리포트 잡의 트리거 마커)."""
    report = db.get(models.Report, session_id)
    if report is None:
        db.add(models.Report(session_id=session_id, status=AsyncStatus.queued))
    else:
        report.status = AsyncStatus.queued
