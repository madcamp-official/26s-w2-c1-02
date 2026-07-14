"""질의응답 (Q&A) 라우터 (Step 3, api-spec §4.4).

작업 2: `POST /qna/generate` — 전사 완료 후 slides+transcript+personas로 질문 생성을 접수(202).
실제 생성·TTS는 백그라운드(qna_jobs.run_generate)에서 돌고, 결과는 GET /qna 폴링(작업 5)으로
확인한다. 답변·꼬리질문·종료(작업 4·5)는 이후 이 라우터에 추가된다.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_session_member, require_session_owner
from app.api.routes.recordings import _audio_ext  # 답변 오디오도 녹음과 동일 형식 세트
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import (
    AnswerKind, AnswerStatus, AsyncStatus, EndedReason, FollowUpStatus, SessionStatus,
)
from app.db.session import get_db
from app.schemas.qna import (
    AnswerOut,
    EvidenceOut,
    PassRequest,
    QnaStateOut,
    QnaStatus,
    QuestionOut,
    TranscriptRefOut,
    TtsOut,
)
from app.schemas.session import ErrorInfo
from app.services import qna_jobs, report_jobs, stt_queue
from app.services.session_state import advance_status
from app.services.stt import seconds_to_ts

router = APIRouter(tags=["qna"])

# 이미 질문 생성이 시작된(또는 끝난) 세션 — 재접수를 막을 상태들
_ALREADY_STARTED = {
    SessionStatus.generating_questions,
    SessionStatus.qna,
    SessionStatus.completed,
}

# GET /qna를 볼 수 있는 상태 (질문 생성 이후). 그 전엔 409 QNA_NOT_STARTED.
# failed도 포함한다 — 생성 시작 후 LLM 실패로 failed가 된 세션을 QNA_NOT_STARTED
# ("아직 생성 전")로 오해시키지 않고, status=failed로 내려 폴링 화면이 '재생성'을
# 안내하게 한다. (진짜 생성 전인 draft·transcribing은 여전히 409.)
_QNA_VIEWABLE = {
    SessionStatus.generating_questions,  # 생성 중 — questions 빈 채로 폴링 가능
    SessionStatus.qna,
    SessionStatus.completed,
    SessionStatus.failed,                # 생성 실패 — status=failed로 노출(재생성 가능)
}

_MAX_ANSWER_BYTES = 200 * 1024 * 1024  # §1.3: 200MB (답변은 짧지만 상한은 녹음과 동일)


@router.post("/sessions/{session_id}/qna/generate", status_code=202)
def generate_questions(
    background: BackgroundTasks,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """질문 생성 접수 (owner) → 202. 전사(+자료)가 준비됐을 때만.

    선행조건: 발표 전사 ready. 자료가 **있으면** 그것도 ready여야 한다(없으면 자료 없이 진행).
    상태는 transcribing/failed(생성 재시도)에서만 generating_questions로 전이된다.
    """
    # 중복 방지 — 이미 생성 중/완료면 재접수 거부 (전사 검사보다 먼저: 더 명확한 메시지)
    if session.status in _ALREADY_STARTED:
        raise ApiError(409, "QNA_ALREADY_STARTED", "이미 질문 생성이 시작됐어요.")

    transcript = db.get(models.Transcript, session.id)
    if transcript is None or transcript.status != AsyncStatus.ready:
        raise ApiError(409, "TRANSCRIPT_NOT_READY", "발표 전사가 끝난 뒤 질문을 생성할 수 있어요.")

    material = db.get(models.Material, session.id)
    if material is not None and material.status != AsyncStatus.ready:
        # 자료가 남아 있는데 아직 처리 중/실패면 먼저 정리(재시도 또는 삭제)해야 한다.
        raise ApiError(409, "MATERIAL_NOT_READY",
                       "자료 처리가 끝난 뒤 질문을 생성할 수 있어요. (자료를 지우면 자료 없이 진행돼요)")

    # transcribing → generating_questions (실패 후 재시도면 failed → generating_questions).
    # 허용되지 않은 상태(draft 등)면 여기서 409 INVALID_STATE_TRANSITION.
    advance_status(session, SessionStatus.generating_questions)
    db.commit()

    background.add_task(qna_jobs.run_generate, session.id)
    return {"status": SessionStatus.generating_questions.value}


# ── 작업 4. 답변 제출 · 패스 ──────────────────────────────────────────

def _require_current_question(
    session: models.RehearsalSession, question_id: str, db: Session,
) -> models.Question:
    """세션이 qna이고, question_id가 이 세션의 **현재 차례** 질문인지 확인."""
    if session.status != SessionStatus.qna:
        raise ApiError(409, "QNA_NOT_ACTIVE", "질의응답 중일 때만 할 수 있어요.")
    question = db.get(models.Question, question_id)
    if question is None or question.session_id != session.id:
        raise ApiError(404, "QUESTION_NOT_FOUND", "질문을 찾을 수 없어요.")
    if session.current_question_id != question_id:
        raise ApiError(409, "NOT_CURRENT_QUESTION", "지금 답할 차례의 질문이 아니에요.")
    return question


@router.post("/sessions/{session_id}/qna/questions/{question_id}/answer", status_code=202)
def submit_answer(
    question_id: str,
    file: UploadFile = File(...),
    duration_seconds: int = Form(...),
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """답변 오디오 업로드 → **202 접수만**. STT·꼬리질문은 비동기(§4.4 A 수정).

    실패 답변 재제출은 같은 질문에 덮어쓰기. 결과는 GET /qna 폴링으로 확정."""
    question = _require_current_question(session, question_id, db)
    ext = _audio_ext(file)
    if ext is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "mp3 · wav · m4a 파일만 올릴 수 있어요.")
    if duration_seconds < 0:
        raise ApiError(400, "INVALID_DURATION", "재생 길이가 올바르지 않아요.")

    data = file.file.read()
    if len(data) == 0:
        raise ApiError(400, "EMPTY_FILE", "빈 파일이에요.")
    if len(data) > _MAX_ANSWER_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "답변은 200MB 이하만 올릴 수 있어요.")

    key = storage.answer_key(session.id, question_id, ext)
    storage.save(key, data)

    answer = db.get(models.Answer, question_id)
    old_key = answer.audio_storage_key if answer is not None else None
    if answer is None:
        answer = models.Answer(
            question_id=question_id, kind=AnswerKind.answered, status=AnswerStatus.processing,
            audio_storage_key=key, duration_seconds=duration_seconds,
            follow_up_status=FollowUpStatus.pending,
        )
        db.add(answer)
    else:  # 재제출 — 덮어쓰기 + 상태 초기화
        answer.kind = AnswerKind.answered
        answer.status = AnswerStatus.processing
        answer.audio_storage_key = key
        answer.duration_seconds = duration_seconds
        answer.follow_up_status = FollowUpStatus.pending
        answer.text = None
        answer.error_code = None
        answer.error_message = None
    db.commit()

    if old_key and old_key != key:  # 확장자 변경 재제출 → 옛 파일 정리
        storage.delete(old_key)
    stt_queue.enqueue_answer(question_id)  # 발표 전사와 같은 직렬 워커

    return {"answer": AnswerOut(
        status=AnswerStatus.processing.value, text=None,
        audio_url=storage.signed_url(key), follow_up_status=FollowUpStatus.pending,
    ).model_dump()}


@router.post("/sessions/{session_id}/qna/questions/{question_id}/pass", status_code=200)
def pass_question(
    background: BackgroundTasks,
    question_id: str,
    body: PassRequest | None = None,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """답변 패스 → 꼬리질문 생략하고 다음 질문. 마지막을 timeout으로 넘기면 종료 사유=timeout."""
    question = _require_current_question(session, question_id, db)
    reason = body.reason if body is not None else "user"
    qna_jobs.record_pass(db, session, question, reason)
    db.refresh(session)
    if session.status == SessionStatus.completed:  # 마지막 질문 패스 → 자동 종료 → 리포트(A7)
        background.add_task(report_jobs.run_report, session.id)
    return {
        "status": session.status.value,
        "current_question_id": session.current_question_id,
        "ended_reason": session.qna_ended_reason.value if session.qna_ended_reason else None,
    }


# ── 작업 5-2. 사용자 종료 (POST /qna/end) ────────────────────────────

@router.post("/sessions/{session_id}/qna/end", status_code=200)
def end_qna(
    background: BackgroundTasks,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """질의응답 사용자 종료 (owner) → completed + 리포트 자동 생성 (A7).

    A12: 사용자 종료가 최우선순위 → ended_reason=user_end (질의 수 도달 여부와 무관)."""
    if session.status != SessionStatus.qna:
        raise ApiError(409, "QNA_NOT_ACTIVE", "질의응답 중일 때만 종료할 수 있어요.")
    qna_jobs.end_session(db, session, EndedReason.user_end)
    db.commit()
    db.refresh(session)
    background.add_task(report_jobs.run_report, session.id)
    return {"status": session.status.value, "ended_reason": session.qna_ended_reason.value}


# ── 작업 5-1. Q&A 폴링 소스 (GET /qna, 질문 상세) ─────────────────────

def _answer_out(answer: models.Answer | None) -> AnswerOut:
    """answers row → AnswerOut. row 부재 = 아직 답 안 함 → status "pending" (db-schema §5)."""
    if answer is None:
        return AnswerOut(status="pending", follow_up_status=FollowUpStatus.none)
    error = None
    if answer.error_code:
        error = ErrorInfo(code=answer.error_code, message=answer.error_message or "")
    return AnswerOut(
        status=answer.status.value,
        text=answer.text,
        audio_url=storage.signed_url(answer.audio_storage_key) if answer.audio_storage_key else None,
        follow_up_status=answer.follow_up_status,
        error=error,
    )


def _question_out(question: models.Question, answer: models.Answer | None) -> QuestionOut:
    """questions(+answers) row → QuestionOut (§4.4). evidence·ts는 서빙 시 포맷."""
    ev = question.evidence or {}
    refs = [TranscriptRefOut(ts=seconds_to_ts(r["start"])) for r in ev.get("transcript_refs", [])]
    tts = TtsOut(
        status=question.tts_status,
        audio_url=storage.signed_url(question.tts_storage_key) if question.tts_storage_key else None,
    )
    return QuestionOut(
        id=question.id, order=question.order_index, persona=question.persona,
        strategy=question.strategy, parent_id=question.parent_id,
        follow_up_depth=question.follow_up_depth, text=question.text,
        evidence=EvidenceOut(slides=ev.get("slides", []), transcript_refs=refs),
        tts=tts, answer=_answer_out(answer),
    )


@router.get("/sessions/{session_id}/qna", response_model=QnaStateOut)
def get_qna(
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> QnaStateOut:
    """Q&A 전체 상태 (멤버) — 폴링 단일 소스 (§4.4). 표시 순서: order_index, follow_up_depth."""
    if session.status not in _QNA_VIEWABLE:
        raise ApiError(409, "QNA_NOT_STARTED", "아직 질문 생성 전이에요.")

    questions = db.scalars(
        select(models.Question)
        .where(models.Question.session_id == session.id)
        .order_by(models.Question.order_index, models.Question.follow_up_depth)  # 꼬리는 부모 뒤
    ).all()
    items = [_question_out(q, db.get(models.Answer, q.id)) for q in questions]

    if session.status == SessionStatus.completed:
        status = QnaStatus.ended
    elif session.status == SessionStatus.failed:
        status = QnaStatus.failed          # 생성 실패 — FE가 재생성 안내
    else:
        status = QnaStatus.in_progress
    return QnaStateOut(
        status=status,
        current_question_id=session.current_question_id,
        ended_reason=session.qna_ended_reason,
        questions=items,
    )


@router.get("/sessions/{session_id}/qna/questions/{question_id}", response_model=QuestionOut)
def get_question(
    question_id: str,
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> QuestionOut:
    """질문 1건 상세 (멤버) — GET /qna의 questions[] 원소와 동일 형태."""
    question = db.get(models.Question, question_id)
    if question is None or question.session_id != session.id:
        raise ApiError(404, "QUESTION_NOT_FOUND", "질문을 찾을 수 없어요.")
    return _question_out(question, db.get(models.Answer, question_id))
