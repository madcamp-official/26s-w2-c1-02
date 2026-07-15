"""아이디 찾기 · 비밀번호 재설정 회귀 테스트 (api-spec §2). 실 DB 사용.

실행:
    cd backend
    DATABASE_URL='postgresql+psycopg://rehearsal:asdf1234@127.0.0.1:5433/rehearsal_dev' \
        .venv/bin/pytest tests/test_account_recovery.py -v

계약:
- POST /auth/username/find      → 항상 204 (열거 방지). 아이디는 본문에 없고 메일로만.
- POST /auth/password/reset-request → 항상 204 · 60초 쿨다운 429 + Retry-After
- POST /auth/password/reset     → 200 {reset:true} · 400 INVALID_CODE/CODE_EXPIRED
                                   · attempt 검사가 대조보다 먼저 · 성공 시 전 세션 폐기

코드/아이디 평문은 응답에 없으므로 발급·발송 함수를 monkeypatch로 감싸 캡처한다
(test_email_verify.py의 codes 픽스처 방식).
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

import app.api.routes.auth as auth_module
from app.core.security import hash_refresh_token, verify_password
from app.db.enums import ClientPlatform
from app.db.models import PasswordReset, RefreshToken, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

BASE = "/api/v1/auth"
PASSWORD = "recover-pass-12345"
NEW_PASSWORD = "brand-new-pass-99"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("rectest_%")))
        db.commit()


@pytest.fixture()
def reset_codes(monkeypatch) -> list[str]:
    """발급된 재설정 코드 평문 캡처 — 라우트가 참조하는 issue_reset_code를 감싼다."""
    issued: list[str] = []
    real = auth_module.issue_reset_code

    def capture(db, user):
        code = real(db, user)
        issued.append(code)
        return code

    monkeypatch.setattr(auth_module, "issue_reset_code", capture)
    return issued


@pytest.fixture()
def usernames(monkeypatch) -> list[tuple[str, str]]:
    """아이디 찾기 발송 캡처 — 발송 태스크가 받은 (email, username)을 기록."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth_module, "send_username_reminder_email",
        lambda email, username: sent.append((email, username)),
    )
    return sent


def _signup(username: str = "rectest_u1") -> dict:
    res = client.post(f"{BASE}/signup", json={
        "name": "복구테스트", "username": username,
        "password": PASSWORD, "email": f"{username}@test.io",
    })
    assert res.status_code == 201, res.text
    user = res.json()["user"]
    # 로그인/재설정 흐름 검증이 목적이라 인증 상태는 별개 — 여기선 인증 완료로 만들어 둔다
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == user["id"])
                   .values(email_verified_at=datetime.now(timezone.utc)))
        db.commit()
    return user


def _find_username(email: str):
    return client.post(f"{BASE}/username/find", json={"email": email})


def _reset_request(email: str):
    return client.post(f"{BASE}/password/reset-request", json={"email": email})


def _reset(email: str, code: str, new_password: str = NEW_PASSWORD):
    return client.post(f"{BASE}/password/reset",
                       json={"email": email, "code": code, "new_password": new_password})


def _login(username: str = "rectest_u1", password: str = PASSWORD):
    return client.post(f"{BASE}/login", json={"username": username, "password": password},
                       headers={"X-Client-Platform": "ios"})


def _lift_cooldown(user_id: str) -> None:
    """쿨다운 우회 — 이 유저의 재설정 발급 시각을 61초 전으로 민다."""
    with SessionLocal() as db:
        db.execute(update(PasswordReset)
                   .where(PasswordReset.user_id == user_id)
                   .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=61)))
        db.commit()


def _valid_row(user_id: str) -> PasswordReset | None:
    with SessionLocal() as db:
        return db.scalar(select(PasswordReset).where(
            PasswordReset.user_id == user_id,
            PasswordReset.consumed_at.is_(None)))


def _wrong_code(right: str) -> str:
    return "000000" if right != "000000" else "111111"


class TestFindUsername:
    def test_sends_username_by_email_and_body_has_none(self, usernames):
        """가입된 이메일 → 204 + 메일로 아이디 발송. 응답 본문엔 아이디가 없어야 한다."""
        user = _signup()
        res = _find_username(user["email"])
        assert res.status_code == 204
        assert usernames == [(user["email"], "rectest_u1")]
        assert "rectest_u1" not in res.text  # 본문 노출 금지 (204라 사실상 빈 본문)

    def test_unknown_email_same_204_without_sending(self, usernames):
        """없는 이메일도 204 (계정 열거 방지) — 발송도 없어야 한다."""
        res = _find_username("rectest_ghost@nowhere.io")
        assert res.status_code == 204
        assert usernames == []

    def test_email_lookup_case_insensitive(self, usernames):
        """이메일 대소문자 무시 — 가입 시 소문자 기준과 동일."""
        _signup()
        res = _find_username("RECTEST_U1@TEST.IO")
        assert res.status_code == 204
        assert usernames == [("rectest_u1@test.io", "rectest_u1")]


class TestResetRequest:
    def test_issues_code_and_sends_reset_mail(self, reset_codes, caplog):
        """가입된 이메일 → 204 + 재설정 코드 발급·발송 (mock 로그에 코드)."""
        user = _signup()
        with caplog.at_level("INFO", logger="rehearsal.email"):
            res = _reset_request(user["email"])
        assert res.status_code == 204
        assert len(reset_codes) == 1 and len(reset_codes[0]) == 6
        assert any("[MOCK 메일]" in m and reset_codes[0] in m for m in caplog.messages)

    def test_code_stored_hashed_not_plaintext(self, reset_codes):
        """DB엔 평문이 아니라 bcrypt 해시만 (비밀번호와 동일 규율)."""
        user = _signup()
        _reset_request(user["email"])
        row = _valid_row(user["id"])
        assert row is not None
        assert row.code_hash != reset_codes[0]
        assert row.code_hash.startswith("$2")
        assert row.attempt_count == 0

    def test_unknown_email_204_without_issuing(self, reset_codes):
        """없는 이메일 → 204 (열거 방지). 발급도 없어야 한다."""
        assert _reset_request("rectest_ghost@nowhere.io").status_code == 204
        assert reset_codes == []

    def test_within_cooldown_429_with_retry_after(self, reset_codes):
        """60초 내 재요청 → 429 RATE_LIMITED + Retry-After 헤더."""
        user = _signup()
        assert _reset_request(user["email"]).status_code == 204  # 첫 발급
        res = _reset_request(user["email"])                      # 쿨다운 중
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "RATE_LIMITED"
        assert 1 <= int(res.headers["retry-after"]) <= 61
        assert res.json()["error"]["details"]["retry_after_seconds"] == int(res.headers["retry-after"])

    def test_resend_invalidates_old_code(self, reset_codes):
        """재발송 → 옛 코드 무효, 새 코드로만 재설정 가능."""
        user = _signup()
        _reset_request(user["email"])
        _lift_cooldown(user["id"])
        assert _reset_request(user["email"]).status_code == 204
        assert len(reset_codes) == 2
        assert _reset(user["email"], reset_codes[0]).status_code == 400  # 옛 코드 무효
        assert _reset(user["email"], reset_codes[1]).status_code == 200  # 새 코드 성공


class TestResetPassword:
    def test_correct_code_changes_password_and_revokes_sessions(self, reset_codes):
        """올바른 코드 → 200 {reset:true} + 새 비번으로 로그인 가능 + 기존 세션 폐기."""
        user = _signup()
        # 재설정 전에 로그인해 세션(refresh) 하나 만들어 둔다
        login = _login()
        assert login.status_code == 200
        old_refresh = login.json()["refresh_token"]

        _reset_request(user["email"])
        res = _reset(user["email"], reset_codes[0])
        assert res.status_code == 200 and res.json() == {"reset": True}

        with SessionLocal() as db:
            u = db.get(User, user["id"])
            assert verify_password(NEW_PASSWORD, u.password_hash)   # 새 비번 적용
            assert not verify_password(PASSWORD, u.password_hash)   # 옛 비번 폐기
            # 재설정 전 발급된 refresh는 모두 폐기됐어야 한다
            live = db.scalars(select(RefreshToken).where(
                RefreshToken.user_id == user["id"],
                RefreshToken.revoked_at.is_(None))).all()
            assert live == []

        # 옛 refresh로는 재발급 불가, 새 비번으로는 로그인 가능
        assert client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh},
                           headers={"X-Client-Platform": "ios"}).status_code == 401
        assert _login(password=NEW_PASSWORD).status_code == 200
        assert _login(password=PASSWORD).status_code == 401

    def test_wrong_code_400_and_attempt_incremented(self, reset_codes):
        """틀린 코드 → 400 INVALID_CODE + attempt_count 1 증가. 비번은 안 바뀐다."""
        user = _signup()
        _reset_request(user["email"])
        res = _reset(user["email"], _wrong_code(reset_codes[0]))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CODE"
        assert _valid_row(user["id"]).attempt_count == 1
        with SessionLocal() as db:
            assert verify_password(PASSWORD, db.get(User, user["id"]).password_hash)

    def test_exhausted_attempts_reject_even_correct_code(self, reset_codes):
        """5회 실패 후엔 맞는 코드도 400 CODE_EXPIRED — attempt 검사가 대조보다 먼저."""
        user = _signup()
        _reset_request(user["email"])
        for _ in range(5):
            assert _reset(user["email"], _wrong_code(reset_codes[0])).status_code == 400
        res = _reset(user["email"], reset_codes[0])
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CODE_EXPIRED"
        assert _valid_row(user["id"]).attempt_count == 5  # 대조 안 하므로 더 안 늘어남

    def test_expired_code_rejected(self, reset_codes):
        """만료된 코드 → 400 CODE_EXPIRED."""
        user = _signup()
        _reset_request(user["email"])
        with SessionLocal() as db:
            db.execute(update(PasswordReset)
                       .where(PasswordReset.user_id == user["id"])
                       .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            db.commit()
        res = _reset(user["email"], reset_codes[0])
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CODE_EXPIRED"

    def test_no_request_means_no_code(self, reset_codes):
        """reset-request 없이 곧바로 reset → 유효 코드가 없어 400 CODE_EXPIRED."""
        user = _signup()
        res = _reset(user["email"], "123456")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CODE_EXPIRED"

    def test_unknown_email_same_400_as_wrong_code(self, reset_codes):
        """없는 이메일도 INVALID_CODE 400 — 틀린 코드 응답과 본문까지 동일 (존재 숨김)."""
        user = _signup()
        _reset_request(user["email"])
        res_ghost = _reset("rectest_ghost@nowhere.io", "123456")
        res_wrong = _reset(user["email"], _wrong_code(reset_codes[0]))
        assert res_ghost.status_code == res_wrong.status_code == 400
        assert res_ghost.json() == res_wrong.json()

    def test_consumed_code_cannot_be_reused(self, reset_codes):
        """성공한 코드는 소비돼 재사용 불가 → 두 번째 시도는 400."""
        user = _signup()
        _reset_request(user["email"])
        assert _reset(user["email"], reset_codes[0]).status_code == 200
        assert _reset(user["email"], reset_codes[0]).status_code == 400

    def test_bad_code_shape_422(self, reset_codes):
        """형식 위반(5자리)은 라우트 전에 422 (스키마 차단)."""
        user = _signup()
        res = _reset(user["email"], "12345")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_short_new_password_422(self, reset_codes):
        """새 비밀번호 8자 미만은 422 (SignupRequest.password와 동일 제약)."""
        user = _signup()
        _reset_request(user["email"])
        res = _reset(user["email"], reset_codes[0], new_password="short")
        assert res.status_code == 422
