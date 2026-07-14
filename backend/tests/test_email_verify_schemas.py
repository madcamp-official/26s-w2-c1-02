"""이메일 인증 요청 스키마 검증 (email-verification-plan 작업 3). 순수 Pydantic — DB 불필요.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_email_verify_schemas.py -v

api-spec §2 계약: verify-request는 {email}, verify는 {email, code(6자리 숫자)}.
형식 위반은 라우트에 도달하기 전 422로 떨어진다 — 라우트 구현(작업 5)은
"형식이 맞는 입력"만 다루면 된다는 전제를 여기서 회귀로 고정한다.
"""

import pytest
from pydantic import ValidationError

from app.schemas.auth import SignupRequest, VerifyBody, VerifyRequestBody

GOOD_EMAIL = "user@test.io"

# signup을 통과한 이메일이 verify에서 형식 거부되면 안 되고, 그 역도 마찬가지 —
# 세 스키마가 이메일 기준을 공유하는지와 별개로, 대표 케이스를 직접 나열해 고정한다.
BAD_EMAILS = [
    "no-at-sign.io",          # @ 없음
    "a b@test.io",            # 로컬파트 공백
    "user@test io.com",       # 도메인 공백
    "user@test",              # 최상위 도메인 없음
    "user@.io",               # 도메인 레이블 없음
    "",                       # 빈 문자열
    "user@test.io" + "x" * 250,  # max_length=254 초과
]


class TestVerifyRequestBody:
    """POST /auth/email/verify-request 요청 — email 하나."""

    def test_valid_email_passes(self):
        body = VerifyRequestBody(email=GOOD_EMAIL)
        assert body.email == GOOD_EMAIL  # 정규화·변형 없이 그대로

    @pytest.mark.parametrize("email", BAD_EMAILS)
    def test_bad_email_rejected(self, email):
        with pytest.raises(ValidationError):
            VerifyRequestBody(email=email)

    def test_email_required(self):
        with pytest.raises(ValidationError):
            VerifyRequestBody()

    def test_email_criteria_same_as_signup(self):
        """가입을 통과한 이메일은 인증 요청에서도 반드시 통과 — 패턴·상한이 signup과
        동일해야 한다. (기준이 갈라지면 '가입은 됐는데 재발송이 422'가 생긴다)"""
        mine = VerifyRequestBody.model_json_schema()["properties"]["email"]
        signup = SignupRequest.model_json_schema()["properties"]["email"]
        assert mine["pattern"] == signup["pattern"]
        assert mine["maxLength"] == signup["maxLength"]


class TestVerifyBodyCode:
    """POST /auth/email/verify 요청 — code는 정확히 6자리 ASCII 숫자."""

    def test_valid_code_passes(self):
        assert VerifyBody(email=GOOD_EMAIL, code="123456").code == "123456"

    def test_leading_zeros_preserved(self):
        """코드가 '012345'처럼 0으로 시작해도 str이라 자릿수가 보존된다 —
        int 필드였다면 12345가 되어 영원히 인증 불가."""
        assert VerifyBody(email=GOOD_EMAIL, code="012345").code == "012345"

    @pytest.mark.parametrize("code", [
        "12345",      # 5자리
        "1234567",    # 7자리
        "12a456",     # 문자 혼입
        "12 456",     # 공백 혼입
        "12345\n",    # 개행 (6글자지만 [0-9] 아님)
        "-12345",     # 부호
        "12.345",     # 소수점
        "",           # 빈 문자열
        "１２３４５６",  # 전각 숫자 — \d 패턴이면 통과했을 케이스
        "١٢٣٤٥٦",     # 아라비아-인도 숫자 — 위와 동일 (그래서 [0-9]로 제한)
    ])
    def test_bad_code_rejected(self, code):
        with pytest.raises(ValidationError):
            VerifyBody(email=GOOD_EMAIL, code=code)

    def test_int_code_rejected(self):
        """JSON에서 {"code": 123456}(숫자 타입)으로 보내면 거부 — FE는 문자열로
        보내야 한다는 계약. (pydantic v2는 int→str 자동 변환을 하지 않는다)"""
        with pytest.raises(ValidationError):
            VerifyBody(email=GOOD_EMAIL, code=123456)

    @pytest.mark.parametrize("missing", ["email", "code"])
    def test_both_fields_required(self, missing):
        body = {"email": GOOD_EMAIL, "code": "123456"}
        del body[missing]
        with pytest.raises(ValidationError):
            VerifyBody(**body)

    @pytest.mark.parametrize("email", BAD_EMAILS)
    def test_bad_email_rejected_even_with_good_code(self, email):
        with pytest.raises(ValidationError):
            VerifyBody(email=email, code="123456")

    def test_json_path_like_fastapi(self):
        """FastAPI가 실제로 타는 경로(dict → model_validate)로도 동일 동작."""
        VerifyBody.model_validate({"email": GOOD_EMAIL, "code": "654321"})
        with pytest.raises(ValidationError):
            VerifyBody.model_validate({"email": GOOD_EMAIL, "code": "abc123"})
