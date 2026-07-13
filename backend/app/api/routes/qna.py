"""질의응답 (Q&A) 라우터 (Step 3, api-spec §4.4).

작업 2: `POST /qna/generate` — 전사 완료 후 slides+transcript+personas로 질문 생성을 접수(202).
실제 생성·TTS는 백그라운드(qna_jobs.run_generate)에서 돌고, 결과는 GET /qna 폴링(작업 5)으로
확인한다. 답변·꼬리질문·종료(작업 4·5)는 이후 이 라우터에 추가된다.
"""

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_session_owner
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus, SessionStatus
from app.db.session import get_db
from app.services import qna_jobs
from app.services.session_state import advance_status

router = APIRouter(tags=["qna"])

# 이미 질문 생성이 시작된(또는 끝난) 세션 — 재접수를 막을 상태들
_ALREADY_STARTED = {
    SessionStatus.generating_questions,
    SessionStatus.qna,
    SessionStatus.completed,
}


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
