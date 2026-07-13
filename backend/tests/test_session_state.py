"""세션 상태머신 검증 (작업 2-3). 순수 로직 — DB 저장 불필요.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_session_state.py -v
"""

import pytest

from app.core.errors import ApiError
from app.db.enums import SessionStatus as S
from app.db.models import RehearsalSession
from app.services.session_state import (
    ALLOWED_TRANSITIONS,
    advance_status,
    can_transition,
)

# api-spec §4 다이어그램의 유효 전이 (표와 1:1)
VALID = {
    (S.draft, S.recording_in_progress),
    (S.draft, S.transcribing),
    (S.recording_in_progress, S.transcribing),
    (S.transcribing, S.generating_questions),
    (S.transcribing, S.failed),
    (S.generating_questions, S.qna),
    (S.generating_questions, S.failed),
    (S.qna, S.completed),
    (S.failed, S.transcribing),
    (S.failed, S.generating_questions),
}


def _session(status: S) -> RehearsalSession:
    return RehearsalSession(status=status)  # 저장 안 함, status만 사용


class TestTransitionTable:
    def test_all_valid_transitions_allowed(self):
        for frm, to in VALID:
            assert can_transition(frm, to), f"{frm}->{to} 허용돼야 함"

    def test_all_invalid_transitions_blocked(self):
        """유효 목록에 없는 모든 (from,to) 조합은 전부 막혀야 한다 (전수)."""
        for frm in S:
            for to in S:
                if (frm, to) not in VALID:
                    assert not can_transition(frm, to), f"{frm}->{to} 막혀야 함"

    def test_terminal_states_have_no_exit(self):
        assert ALLOWED_TRANSITIONS[S.completed] == frozenset()

    def test_every_status_has_an_entry(self):
        """상태가 새로 추가돼도 표에 빠지지 않게 (KeyError 방지)."""
        for s in S:
            assert s in ALLOWED_TRANSITIONS


class TestAdvanceStatus:
    def test_valid_advance_mutates(self):
        s = _session(S.draft)
        advance_status(s, S.transcribing)
        assert s.status is S.transcribing

    def test_invalid_advance_409_and_unchanged(self):
        s = _session(S.draft)
        with pytest.raises(ApiError) as e:
            advance_status(s, S.qna)  # draft에서 qna 건너뛰기
        assert e.value.status_code == 409
        assert e.value.code == "INVALID_STATE_TRANSITION"
        assert s.status is S.draft  # 실패 시 상태 안 바뀜

    def test_self_transition_rejected(self):
        """같은 상태로의 재진입도 거부 (명시적 멱등은 호출부 책임)."""
        s = _session(S.transcribing)
        with pytest.raises(ApiError):
            advance_status(s, S.transcribing)

    def test_full_happy_path(self):
        """draft → … → completed 전체 경로가 순서대로 흐른다."""
        s = _session(S.draft)
        for to in (S.transcribing, S.generating_questions, S.qna, S.completed):
            advance_status(s, to)
        assert s.status is S.completed

    def test_realtime_path(self):
        s = _session(S.draft)
        advance_status(s, S.recording_in_progress)
        advance_status(s, S.transcribing)
        assert s.status is S.transcribing

    def test_retry_from_failed(self):
        """STT 실패 후 재시도로 transcribing 복귀."""
        s = _session(S.transcribing)
        advance_status(s, S.failed)
        advance_status(s, S.transcribing)  # retry
        assert s.status is S.transcribing

    def test_cannot_escape_completed(self):
        s = _session(S.completed)
        with pytest.raises(ApiError):
            advance_status(s, S.qna)


class TestStateMachineInvariants:
    """재검증(2차) — 표를 잘못 수정하면 세션이 갇히거나 완료 불가가 되는 걸 막는다."""

    def test_only_completed_is_terminal(self):
        """나가는 전이가 없는(갇히는) 상태는 completed 하나뿐이어야 한다."""
        terminal = {s for s in S if not ALLOWED_TRANSITIONS[s]}
        assert terminal == {S.completed}, f"예상치 못한 종료 상태: {terminal - {S.completed}}"

    def test_every_state_can_reach_completed(self):
        """어떤 상태의 세션도 completed로 갈 경로가 있어야 한다 (영구 미완료 방지)."""
        def reaches(start, target, seen=None):
            seen = seen or set()
            if start == target:
                return True
            seen.add(start)
            return any(reaches(n, target, seen)
                       for n in ALLOWED_TRANSITIONS[start] if n not in seen)

        for s in S:
            assert reaches(s, S.completed), f"{s.value}에서 completed 도달 불가"


class TestTargetTypeHandling:
    """대상 값의 타입이 이상해도 crash 없이 처리 (StrEnum 특성 고정)."""

    def test_valid_raw_string_target_works(self):
        """StrEnum이라 'transcribing' 같은 raw 문자열도 enum과 동일하게 취급된다."""
        s = _session(S.draft)
        advance_status(s, "transcribing")
        assert s.status == S.transcribing

    def test_invalid_raw_string_409_not_crash(self):
        s = _session(S.draft)
        with pytest.raises(ApiError) as e:
            advance_status(s, "not_a_state")
        assert e.value.status_code == 409

    @pytest.mark.parametrize("bad", [123, None, "typo"])
    def test_odd_type_rejected_gracefully(self, bad):
        assert can_transition(S.draft, bad) is False
