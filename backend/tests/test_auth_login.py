"""POST /api/v1/auth/login 회귀 테스트 (작업 3-3).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_auth_login.py -v

핵심 계약 (api-spec §2, B 수정):
- Native(ios/android): refresh_token이 응답 본문에 있음, 쿠키 없음
- Web: refresh_token이 본문에 없고 httpOnly 쿠키(Set-Cookie, Path=/api/v1/auth)로만
- DB에는 refresh 원문이 아니라 SHA-256 해시만 저장
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import decode_access_token, hash_refresh_token
from app.db.enums import ClientPlatform
from app.db.models import RefreshToken, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

client = TestClient(app)

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"

CREDS = {"username": "lgtest_user", "password": "login-pass-123"}


@pytest.fixture(autouse=True)
def test_user():
    """각 테스트마다 깨끗한 유저를 만들고, 끝나면 지운다 (refresh_tokens는 cascade)."""
    res = client.post(SIGNUP_URL, json={
        "name": "로그인테스트", "username": CREDS["username"],
        "password": CREDS["password"], "email": "lgtest@test.io",
    })
    assert res.status_code == 201
    mark_email_verified(CREDS["username"])  # 로그인 차단(403) 우회
    yield res.json()["user"]
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("lgtest%")))
        db.commit()


class TestLoginNative:
    def test_ios_login_returns_tokens_in_body(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        assert res.status_code == 200
        body = res.json()
        # spec §2 Native 응답 예시와 필드 단위 일치
        assert set(body.keys()) == {"access_token", "refresh_token", "token_type", "expires_in", "user"}
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 900
        assert set(body["user"].keys()) == {"id", "name", "username", "email"}
        # Native는 쿠키를 쓰지 않는다
        assert "set-cookie" not in res.headers

    def test_access_token_identifies_user(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "android"})
        assert decode_access_token(res.json()["access_token"]) == test_user["id"]

    def test_refresh_stored_as_hash_with_platform(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        raw = res.json()["refresh_token"]
        with SessionLocal() as db:
            row = db.scalar(select(RefreshToken).where(RefreshToken.user_id == test_user["id"]))
            assert row.token_hash == hash_refresh_token(raw)  # 해시 대조 방식
            assert row.token_hash != raw                       # 원문 저장 금지
            assert row.platform == ClientPlatform.ios
            assert row.revoked_at is None


class TestLoginWeb:
    def test_web_login_uses_cookie_not_body(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        assert res.status_code == 200
        body = res.json()
        assert "refresh_token" not in body  # B 수정: Web 본문엔 refresh 없음
        cookie = res.headers["set-cookie"]
        assert cookie.startswith("refresh_token=")
        assert "HttpOnly" in cookie          # JS에서 탈취 불가
        assert "Path=/api/v1/auth" in cookie # auth 경로에만 전송
        assert "SameSite=strict" in cookie.lower() or "samesite=strict" in cookie.lower()

    def test_missing_platform_header_defaults_to_web(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS)  # 헤더 없음
        assert res.status_code == 200
        assert "refresh_token" not in res.json()
        assert "set-cookie" in res.headers

    def test_cookie_value_matches_db_hash(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        raw = client.cookies.get("refresh_token", path="/api/v1/auth") or \
            res.headers["set-cookie"].split("refresh_token=")[1].split(";")[0]
        with SessionLocal() as db:
            row = db.scalar(select(RefreshToken).where(RefreshToken.user_id == test_user["id"]))
            assert row.token_hash == hash_refresh_token(raw)
            assert row.platform == ClientPlatform.web


class TestLoginFailures:
    def test_wrong_password_401(self, test_user):
        res = client.post(LOGIN_URL, json={**CREDS, "password": "wrong-pass-999"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_unknown_username_same_401(self, test_user):
        """계정 존재 여부가 노출되면 안 된다 — 없는 아이디도 같은 코드/메시지."""
        res_wrong_pw = client.post(LOGIN_URL, json={**CREDS, "password": "wrong-pass-999"})
        res_no_user = client.post(LOGIN_URL, json={"username": "lgtest_ghost", "password": "x" * 10})
        assert res_no_user.status_code == 401
        assert res_no_user.json() == res_wrong_pw.json()

    def test_withdrawn_user_cannot_login(self, test_user):
        from datetime import datetime, timezone
        with SessionLocal() as db:
            u = db.get(User, test_user["id"])
            u.deleted_at = datetime.now(timezone.utc)  # 탈퇴 마커 (PII는 유지한 채도 차단돼야 함)
            db.commit()
        res = client.post(LOGIN_URL, json=CREDS)
        assert res.status_code == 401

    def test_social_only_user_401_not_500(self, test_user):
        """password_hash가 NULL인 소셜 전용 유저 — 비밀번호 로그인 시도가 500이면 안 된다."""
        with SessionLocal() as db:
            u = User(username="lgtest_social", name="소셜", email="lgtest_social@test.io",
                     password_hash=None)
            db.add(u)
            db.commit()
        res = client.post(LOGIN_URL, json={"username": "lgtest_social", "password": "any-pass-123"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


class TestLoginBehavior:
    def test_username_case_insensitive(self, test_user):
        res = client.post(LOGIN_URL, json={**CREDS, "username": "LGTEST_USER"},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 200
        assert res.json()["user"]["id"] == test_user["id"]

    def test_multi_device_login_keeps_all_refresh_rows(self, test_user):
        """폰+웹 동시 로그인: refresh 행이 기기마다 하나씩 쌓여야 한다."""
        client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        with SessionLocal() as db:
            rows = db.scalars(
                select(RefreshToken).where(RefreshToken.user_id == test_user["id"])
            ).all()
            assert len(rows) == 2
            assert {r.platform for r in rows} == {ClientPlatform.ios, ClientPlatform.web}

    def test_two_logins_issue_different_refresh_tokens(self, test_user):
        r1 = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        r2 = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        assert r1.json()["refresh_token"] != r2.json()["refresh_token"]


class TestLoginHardening:
    """재검증(2차)에서 확인한 엣지 케이스들 — 회귀 방지용."""

    def test_web_body_has_exact_keys(self, test_user):
        """Web 응답도 spec 예시와 필드 단위로 일치해야 한다 (refresh_token 없이 4개)."""
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        assert set(res.json().keys()) == {"access_token", "token_type", "expires_in", "user"}

    def test_cookie_has_secure_flag(self, test_user):
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        assert "Secure" in res.headers["set-cookie"]

    def test_unknown_platform_value_falls_back_to_web(self, test_user):
        """'desktop' 같은 규약 밖 값은 web(쿠키 방식)으로 처리한다 — 문서화된 관용 동작."""
        res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "desktop"})
        assert res.status_code == 200
        assert "refresh_token" not in res.json()
        assert "set-cookie" in res.headers

    def test_refresh_row_expires_in_about_14_days(self, test_user):
        from datetime import datetime, timezone
        client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
        with SessionLocal() as db:
            row = db.scalar(select(RefreshToken).where(RefreshToken.user_id == test_user["id"]))
            days = (row.expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
            assert 13.9 < days <= 14.0

    def test_overlong_korean_password_401_not_500(self, test_user):
        """bcrypt 72바이트 상한 — 로그인에서는 500 없이 조용한 401이어야 한다."""
        res = client.post(LOGIN_URL, json={"username": CREDS["username"], "password": "가" * 30})
        assert res.status_code == 401

    def test_sqli_like_username_401_not_500(self, test_user):
        """로그인 username엔 패턴 제한이 없으므로 인젝션류 입력도 안전해야 한다."""
        res = client.post(LOGIN_URL, json={"username": "x'; DROP TABLE users; --",
                                           "password": "any-pass-123"})
        assert res.status_code == 401

    def test_empty_credentials_422_spec_format(self, test_user):
        res = client.post(LOGIN_URL, json={"username": "", "password": ""})
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_timing_equalized_for_unknown_user(self, test_user, monkeypatch):
        """타이밍 공격 방어(재검증에서 발견: 9ms vs 421ms → 수정):
        없는 아이디도 bcrypt 검증을 정확히 1회 수행해 응답 시간을 맞춰야 한다."""
        import app.api.routes.auth as auth_module

        calls = {"n": 0}
        real = auth_module.verify_password

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(auth_module, "verify_password", counting)
        res = client.post(LOGIN_URL, json={"username": "lgtest_ghost_xyz",
                                           "password": "whatever-123"})
        assert res.status_code == 401
        assert calls["n"] == 1, "없는 아이디 경로에서 더미 bcrypt 검증이 수행되지 않음"
