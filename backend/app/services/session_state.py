"""세션 상태머신 (작업 2-3, api-spec §4 상태 다이어그램).

세션 status는 정해진 순서로만 전이한다. 허용되지 않은 전이(예: draft→qna 건너뛰기)는
409 INVALID_STATE_TRANSITION으로 막아, 잘못된 순서의 호출을 데이터가 오염되기 전에 차단.

    from app.services.session_state import advance_status
    advance_status(session, SessionStatus.transcribing)  # 검증 후 session.status 변경
    db.commit()                                          # 커밋은 호출자 몫

전이 표 (api-spec §4):
    draft                 → recording_in_progress | transcribing
    recording_in_progress → transcribing
    transcribing          → generating_questions | failed
    generating_questions  → qna | failed
    qna                   → completed
    failed                → transcribing | generating_questions   # retry 경로
    completed             → (종료)
"""

from app.core.errors import ApiError
from app.db.enums import SessionStatus
from app.db import models

# from → 허용되는 to 집합
ALLOWED_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.draft: frozenset({
        SessionStatus.recording_in_progress,  # 실시간 녹음 시작
        SessionStatus.transcribing,           # 파일 업로드 → 바로 STT
    }),
    SessionStatus.recording_in_progress: frozenset({SessionStatus.transcribing}),
    SessionStatus.transcribing: frozenset({
        SessionStatus.generating_questions,   # STT 완료 → 질문 생성
        SessionStatus.failed,                 # STT 실패
    }),
    SessionStatus.generating_questions: frozenset({
        SessionStatus.qna,                    # 질문 생성 완료
        SessionStatus.failed,                 # 생성 실패
    }),
    SessionStatus.qna: frozenset({SessionStatus.completed}),  # qna/end
    # 재시도: 실패 지점으로 되돌아가 다시 시도 (transcript/qna retry)
    SessionStatus.failed: frozenset({
        SessionStatus.transcribing,
        SessionStatus.generating_questions,
    }),
    SessionStatus.completed: frozenset(),     # 종료 상태 — 더 전이 없음
}


def can_transition(current: SessionStatus, to: SessionStatus) -> bool:
    return to in ALLOWED_TRANSITIONS.get(current, frozenset())


def advance_status(session: "models.RehearsalSession", to: SessionStatus) -> None:
    """세션 상태를 to로 전이한다. 허용되지 않으면 409로 거부(변경하지 않음).

    같은 상태로의 재진입(to == 현재)도 명시적으로 거부 — 멱등이 필요한 곳은
    호출 전에 상태를 확인할 것. 커밋은 호출자가 한다."""
    current = session.status
    if not can_transition(current, to):
        # to가 enum이 아닌 값(무효 문자열 등)일 수 있으므로 .value를 가정하지 않는다.
        to_label = to.value if isinstance(to, SessionStatus) else to
        raise ApiError(
            409, "INVALID_STATE_TRANSITION",
            f"'{current.value}' 상태에서 '{to_label}'(으)로 진행할 수 없어요.",
        )
    session.status = to
