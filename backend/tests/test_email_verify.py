"""이메일 인증 라우트 회귀 테스트 (email-verification-plan 작업 5·6). 실 DB 사용.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_email_verify.py -v

계약 (api-spec §2·§6.2, plan §5):
- signup → 코드 발급 + BackgroundTasks 발송 (mock: 로그 출력)
- verify-request → 항상 204 (열거 방지) · 60초 쿨다운 429 + Retry-After
- verify → 200 멱등 · 400 INVALID_CODE/CODE_EXPIRED (attempt 검사가 대조보다 먼저)
- login → 미인증 403 EMAIL_NOT_VERIFIED (비밀번호 검증 통과 후에만)

코드 평문은 응답에 없으므로 issue_verification_code를 monkeypatch로 감싸
반환값을 캡처한다 (mock_stt 스타일).
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

import app.api.routes.auth as auth_module
from app.db.models import EmailVerification, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

BASE = "/api/v1/auth"
PASSWORD = "emv-pass-12345"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("emvtest_%")))
        db.commit()


@pytest.fixture()
def codes(monkeypatch) -> list[str]:
    """발급된 코드 평문 캡처 — 라우트가 참조하는 issue_verification_code를 감싼다."""
    issued: list[str] = []
    real = auth_module.issue_verification_code

    def capture(db, user):
        code = real(db, user)
        issued.append(code)
        return code

    monkeypatch.setattr(auth_module, "issue_verification_code", capture)
    return issued


def _signup(username: str = "emvtest_u1") -> dict:
    res = client.post(f"{BASE}/signup", json={
        "name": "인증테스트", "username": username,
        "password": PASSWORD, "email": f"{username}@test.io",
    })
    assert res.status_code == 201, res.text
    return res.json()["user"]


def _verify(email: str, code: str):
    return client.post(f"{BASE}/email/verify", json={"email": email, "code": code})


def _resend(email: str):
    return client.post(f"{BASE}/email/verify-request", json={"email": email})


def _login(username: str = "emvtest_u1", password: str = PASSWORD):
    return client.post(f"{BASE}/login", json={"username": username, "password": password},
                       headers={"X-Client-Platform": "ios"})


def _lift_cooldown(user_id: str) -> None:
    """쿨다운 우회 — 이 유저의 발급 시각을 60초 전으로 민다."""
    with SessionLocal() as db:
        db.execute(update(EmailVerification)
                   .where(EmailVerification.user_id == user_id)
                   .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=61)))
        db.commit()


def _valid_row(user_id: str) -> EmailVerification | None:
    with SessionLocal() as db:
        return db.scalar(select(EmailVerification).where(
            EmailVerification.user_id == user_id,
            EmailVerification.consumed_at.is_(None)))


def _wrong_code(right: str) -> str:
    return "000000" if right != "000000" else "111111"


class TestSignupIssuesCode:
    def test_signup_creates_hashed_code_row(self, codes):
        """케이스 1: 가입 → 인증 행 생성, DB엔 평문이 아니라 bcrypt 해시."""
        user = _signup()
        assert len(codes) == 1 and len(codes[0]) == 6
        row = _valid_row(user["id"])
        assert row is not None
        assert row.code_hash != codes[0]           # 평문 저장 금지
        assert row.code_hash.startswith("$2")      # bcrypt (sha256 아님)
        assert row.attempt_count == 0

    def test_signup_sends_mock_email_with_code(self, codes, caplog):
        """signup이 발송 서비스까지 연결됐는지 — mock 발송 로그에 코드가 찍힌다."""
        with caplog.at_level("INFO", logger="rehearsal.email"):
            _signup()
        assert any("[MOCK 메일]" in m and codes[0] in m for m in caplog.messages)

    def test_signup_response_has_no_code(self, codes):
        """응답 어디에도 코드 평문이 없어야 한다 (메일로만 전달)."""
        res = client.post(f"{BASE}/signup", json={
            "name": "인증테스트", "username": "emvtest_u1",
            "password": PASSWORD, "email": "emvtest_u1@test.io"})
        assert codes[0] not in res.text


class TestVerify:
    def test_correct_code_marks_verified(self, codes):
        """케이스 2: 올바른 코드 → 200 + email_verified_at·consumed_at 설정."""
        user = _signup()
        res = _verify(user["email"], codes[0])
        assert res.status_code == 200 and res.json() == {"email_verified": True}
        with SessionLocal() as db:
            u = db.get(User, user["id"])
            assert u.email_verified_at is not None
            rows = db.scalars(select(EmailVerification)
                              .where(EmailVerification.user_id == user["id"])).all()
            assert all(r.consumed_at is not None for r in rows)

    def test_wrong_code_400_and_attempt_incremented(self, codes):
        """케이스 3: 틀린 코드 → 400 INVALID_CODE + attempt_count 1 증가."""
        user = _signup()
        res = _verify(user["email"], _wrong_code(codes[0]))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CODE"
        assert _valid_row(user["id"]).attempt_count == 1

    def test_exhausted_attempts_reject_even_correct_code(self, codes):
        """케이스 4: 5회 실패 후엔 맞는 코드도 400 CODE_EXPIRED (소진 취급).
        attempt 검사가 대조보다 먼저라는 순서 계약을 함께 고정한다."""
        user = _signup()
        for _ in range(5):
            assert _verify(user["email"], _wrong_code(codes[0])).status_code == 400
        res = _verify(user["email"], codes[0])
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CODE_EXPIRED"
        # 소진 후에는 attempt가 더 늘지 않는다 (대조 자체를 안 함)
        assert _valid_row(user["id"]).attempt_count == 5

    def test_expired_code_rejected(self, codes):
        """케이스 5: 만료된 코드 → 400 CODE_EXPIRED."""
        user = _signup()
        with SessionLocal() as db:
            db.execute(update(EmailVerification)
                       .where(EmailVerification.user_id == user["id"])
                       .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            db.commit()
        res = _verify(user["email"], codes[0])
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CODE_EXPIRED"

    def test_already_verified_idempotent_200(self, codes):
        """케이스 9: 이미 인증된 유저는 코드가 뭐든 200 — 멱등."""
        user = _signup()
        assert _verify(user["email"], codes[0]).status_code == 200
        res = _verify(user["email"], _wrong_code(codes[0]))  # 틀린 코드로도
        assert res.status_code == 200 and res.json() == {"email_verified": True}

    def test_unknown_email_same_400_as_wrong_code(self, codes):
        """존재 여부 숨김: 없는 이메일도 404가 아니라 INVALID_CODE 400 —
        틀린 코드 응답과 본문까지 완전히 같아야 한다."""
        user = _signup()
        res_ghost = _verify("emvtest_ghost@nowhere.io", "123456")
        res_wrong = _verify(user["email"], _wrong_code(codes[0]))
        assert res_ghost.status_code == res_wrong.status_code == 400
        assert res_ghost.json() == res_wrong.json()

    def test_bad_code_shape_422_spec_format(self):
        """형식 위반(5자리)은 라우트 전에 422 VALIDATION_ERROR (스키마 차단)."""
        user = _signup()
        res = _verify(user["email"], "12345")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


class TestResend:
    def test_resend_invalidates_old_code(self, codes):
        """케이스 6: 재발송 → 옛 코드 400, 새 코드 200."""
        user = _signup()
        _lift_cooldown(user["id"])
        assert _resend(user["email"]).status_code == 204
        assert len(codes) == 2
        assert _verify(user["email"], codes[0]).status_code == 400  # 옛 코드 무효
        assert _verify(user["email"], codes[1]).status_code == 200  # 새 코드 성공

    def test_unknown_email_still_204(self, codes):
        """케이스 7: 없는 이메일 → 204 (계정 열거 방지). 발급도 없어야 한다."""
        assert _resend("emvtest_ghost@nowhere.io").status_code == 204
        assert codes == []

    def test_within_cooldown_429_with_retry_after(self, codes):
        """케이스 8: 60초 내 재요청 → 429 RATE_LIMITED + Retry-After 헤더."""
        user = _signup()  # 방금 발급됐으므로 쿨다운 중
        res = _resend(user["email"])
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "RATE_LIMITED"
        assert 1 <= int(res.headers["retry-after"]) <= 61
        assert res.json()["error"]["details"]["retry_after_seconds"] == int(res.headers["retry-after"])

    def test_retry_after_exposed_to_web_frontend(self, codes):
        """웹 FE(JS)가 Retry-After를 읽으려면 CORS expose가 필요 — 회귀 고정."""
        user = _signup()
        res = client.post(f"{BASE}/email/verify-request", json={"email": user["email"]},
                          headers={"Origin": "http://localhost:5173"})
        assert res.status_code == 429
        assert "retry-after" in res.headers.get("access-control-expose-headers", "").lower()

    def test_verified_user_204_without_issuing(self, codes):
        """케이스 10: 이미 인증된 유저 → 204이되 새 코드 발급·발송이 없어야 한다."""
        user = _signup()
        assert _verify(user["email"], codes[0]).status_code == 200
        n = len(codes)
        assert _resend(user["email"]).status_code == 204  # 쿨다운(429)보다 먼저 204
        assert len(codes) == n                             # 발급 없음
        assert _valid_row(user["id"]) is None              # 유효 행도 없음


class TestLoginGate:
    def test_unverified_login_403(self, codes):
        """케이스 11: 미인증 유저 로그인 → 403 EMAIL_NOT_VERIFIED."""
        _signup()
        res = _login()
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    def test_verified_login_200_with_tokens(self, codes):
        """케이스 12: 인증 완료 후 로그인 → 200 + 토큰 (기존 계약 그대로)."""
        user = _signup()
        assert _verify(user["email"], codes[0]).status_code == 200
        res = _login()
        assert res.status_code == 200
        body = res.json()
        assert body["access_token"] and body["refresh_token"] and body["expires_in"] == 900

    def test_unverified_and_wrong_password_401(self, codes):
        """케이스 13: 미인증 + 비밀번호 틀림 → 401 (비밀번호 검사가 403보다 먼저) —
        401/403 순서가 뒤집히면 응답만으로 '비밀번호는 맞다'가 노출된다."""
        _signup()
        res = _login(password="totally-wrong-99")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"
