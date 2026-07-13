"""세션 스키마 검증 (작업 2-1). 순수 Pydantic — DB 불필요.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_session_schemas.py -v
"""

import pytest
from pydantic import ValidationError

from app.db.enums import QuestionerPersona, SessionMode, SessionStatus
from app.schemas.session import (
    SessionCard,
    SessionCreateRequest,
    SessionDetail,
    SessionUpdateRequest,
)


def _valid(**over):
    body = {"name": "1차 발표", "personas": ["egen", "teto"],
            "question_count": 5, "time_limit_minutes": 10, "mode": "realtime"}
    body.update(over)
    return body


class TestCreateValidation:
    def test_valid_parses(self):
        s = SessionCreateRequest(**_valid())
        assert s.name == "1차 발표"
        assert s.personas == [QuestionerPersona.egen, QuestionerPersona.teto]
        assert s.mode is SessionMode.realtime

    def test_mode_defaults_to_realtime(self):
        body = _valid()
        del body["mode"]
        assert SessionCreateRequest(**body).mode is SessionMode.realtime

    def test_personas_deduped_preserving_order(self):
        """협의사항(6): 중복 페르소나는 하나로. 순서는 첫 등장 기준 보존."""
        s = SessionCreateRequest(**_valid(personas=["kkondae", "egen", "kkondae", "egen"]))
        assert s.personas == [QuestionerPersona.kkondae, QuestionerPersona.egen]

    def test_name_stripped(self):
        assert SessionCreateRequest(**_valid(name="  발표  ")).name == "발표"

    @pytest.mark.parametrize("field,value", [
        ("name", ""),                 # 빈 이름
        ("name", "   "),              # 공백만 → strip 후 빈값
        ("name", "가" * 51),          # 50자 초과
        ("personas", []),             # 최소 1개
        ("personas", ["nope"]),       # 잘못된 enum
        ("question_count", 0),        # 1 미만
        ("question_count", 21),       # 20 초과
        ("time_limit_minutes", 0),
        ("time_limit_minutes", 121),
        ("mode", "streaming"),        # 잘못된 enum
    ])
    def test_invalid_rejected(self, field, value):
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(**{field: value}))

    def test_boundaries_ok(self):
        SessionCreateRequest(**_valid(question_count=1, time_limit_minutes=1))
        SessionCreateRequest(**_valid(question_count=20, time_limit_minutes=120,
                                      name="가" * 50))


class TestCreateHardening:
    """재검증(2차) — Pydantic 미묘 동작 고정."""

    def test_unknown_field_rejected(self):
        """오타 필드(question_cont)를 조용히 무시하지 않고 422로 거부 (extra=forbid)."""
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(question_cont=5))

    def test_float_with_fraction_rejected(self):
        """5.5개 질문 같은 소수는 거부."""
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(question_count=5.5))

    def test_integral_float_and_str_coerced(self):
        """5.0·'5'는 정수 5로 허용(관용) — 동작 고정."""
        assert SessionCreateRequest(**_valid(question_count=5.0)).question_count == 5
        assert SessionCreateRequest(**_valid(question_count="5")).question_count == 5

    def test_personas_string_rejected(self):
        """personas는 리스트여야 — 문자열 하나는 거부."""
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(personas="egen"))

    def test_all_five_personas_with_dupes(self):
        s = SessionCreateRequest(**_valid(
            personas=["egen", "teto", "kkondae", "mungcheong", "jammin", "egen", "teto"]))
        assert [p.value for p in s.personas] == ["egen", "teto", "kkondae", "mungcheong", "jammin"]

    def test_mode_is_case_sensitive(self):
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(mode="Realtime"))

    def test_name_length_checked_after_strip(self):
        """50자 + 뒤 공백 → strip 후 50자라 통과 (검사 순서 고정)."""
        assert len(SessionCreateRequest(**_valid(name="가" * 50 + "  ")).name) == 50

    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValidationError):
            SessionCreateRequest(**_valid(name="\t\n "))


class TestUpdateValidation:
    def test_all_optional(self):
        u = SessionUpdateRequest()
        assert u.name is None and u.personas is None and u.mode is None

    def test_partial_update(self):
        u = SessionUpdateRequest(name="새 이름")
        assert u.name == "새 이름" and u.question_count is None

    def test_dedupe_when_present(self):
        u = SessionUpdateRequest(personas=["egen", "egen", "teto"])
        assert u.personas == [QuestionerPersona.egen, QuestionerPersona.teto]

    def test_bounds_still_enforced(self):
        with pytest.raises(ValidationError):
            SessionUpdateRequest(question_count=99)

    def test_empty_personas_rejected_not_treated_as_none(self):
        """부분수정이라도 personas=[]는 '수정 안 함(None)'이 아니라 잘못된 값 → 거부."""
        with pytest.raises(ValidationError):
            SessionUpdateRequest(personas=[])

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            SessionUpdateRequest(naem="오타")


class TestResponseShapes:
    def test_detail_matches_spec_fields(self):
        d = SessionDetail(
            id="ses_1", team_id="team_1", owner_id="usr_1", name="1차 발표",
            status="qna", personas=["egen", "teto"], question_count=5,
            time_limit_minutes=10, mode="realtime",
            material={"status": "ready", "slide_count": 10},
            recording={"status": "ready", "duration_seconds": 663,
                       "audio_url": "/api/v1/files/x?expires=1&sig=a"},
            transcript={"status": "ready"},
            created_at="2026-07-08T02:10:00Z",
        )
        dumped = d.model_dump()
        # api-spec §4.1 응답 예시의 키 집합과 일치
        assert set(dumped) == {"id", "team_id", "owner_id", "name", "status", "personas",
                               "question_count", "time_limit_minutes", "mode",
                               "material", "recording", "transcript", "report", "created_at"}
        assert dumped["report"] is None  # A7: 종료 전 항상 null
        assert dumped["status"] is SessionStatus.qna

    def test_detail_sub_resources_nullable(self):
        """자료·녹음·전사 업로드 전엔 None."""
        d = SessionDetail(
            id="ses_1", team_id="team_1", owner_id="usr_1", name="draft 발표",
            status="draft", personas=["egen"], question_count=3,
            time_limit_minutes=10, mode="realtime",
            created_at="2026-07-08T02:10:00Z",
        )
        assert d.material is None and d.recording is None and d.transcript is None

    def test_card_shape(self):
        c = SessionCard(id="ses_1", name="발표", status="draft", mode="upload",
                        persona_count=3, question_count=5, time_limit_minutes=10,
                        created_at="2026-07-08T02:10:00Z")
        assert c.persona_count == 3
