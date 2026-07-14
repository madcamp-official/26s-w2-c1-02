"""POST /api/v1/auth/logout 회귀 테스트 (작업 3-5).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_auth_logout.py -v

핵심 계약 (api-spec §2):
- 제시된 refresh 폐기 → 이후 그 토큰으로 refresh 불가
- Web: 쿠키 삭제 헤더 전송
- 멱등: 두 번 눌러도, 가짜 토큰이어도 204 (유효성 탐색 방지)
- 이 기기 세션만 종료 — 다른 기기는 유지
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import hash_refresh_token
from app.db.models import RefreshToken, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

client = TestClient(app)                              # Native(본문)용
web = TestClient(app, base_url="https://testserver")  # Web(Secure 쿠키)용

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"

CREDS = {"username": "lotest_user", "password": "logout-pass-123"}
IOS = {"X-Client-Platform": "ios"}


@pytest.fixture(autouse=True)
def test_user():
    res = client.post(SIGNUP_URL, json={
        "name": "로그아웃테스트", "username": CREDS["username"],
        "password": CREDS["password"], "email": "lotest@test.io",
    })
    assert res.status_code == 201
    mark_email_verified(CREDS["username"])  # 로그인 차단(403) 우회
    web.cookies.clear()
    yield res.json()["user"]
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("lotest%")))
        db.commit()


def _login_native() -> dict:
    return client.post(LOGIN_URL, json=CREDS, headers=IOS).json()


class TestLogoutNative:
    def test_logout_revokes_and_blocks_refresh(self, test_user):
        tok = _login_native()["refresh_token"]
        res = client.post(LOGOUT_URL, json={"refresh_token": tok}, headers=IOS)
        assert res.status_code == 204
        assert res.content == b""  # 204는 본문 없음
        with SessionLocal() as db:
            row = db.scalar(select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(tok)))
            assert row.revoked_at is not None
        # 폐기된 토큰으로 갱신 시도 → 차단
        assert client.post(REFRESH_URL, json={"refresh_token": tok},
                           headers=IOS).status_code == 401

    def test_logout_is_idempotent(self, test_user):
        tok = _login_native()["refresh_token"]
        assert client.post(LOGOUT_URL, json={"refresh_token": tok}, headers=IOS).status_code == 204
        assert client.post(LOGOUT_URL, json={"refresh_token": tok}, headers=IOS).status_code == 204

    def test_garbage_token_still_204_no_probing(self, test_user):
        """가짜 토큰도 204 — 로그아웃 응답으로 토큰 유효성을 탐색할 수 없어야 한다."""
        res = client.post(LOGOUT_URL, json={"refresh_token": "fake-token-xyz"}, headers=IOS)
        assert res.status_code == 204

    def test_no_token_401(self, test_user):
        assert client.post(LOGOUT_URL, headers=IOS).status_code == 401

    def test_other_device_session_survives(self, test_user):
        """ios에서 로그아웃해도 web 세션(다른 refresh 행)은 살아 있어야 한다."""
        ios_tok = _login_native()["refresh_token"]
        web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        client.post(LOGOUT_URL, json={"refresh_token": ios_tok}, headers=IOS)
        # web 쿠키로 갱신은 여전히 가능
        assert web.post(REFRESH_URL, headers={"X-Client-Platform": "web"}).status_code == 200


class TestLogoutWeb:
    def test_cookie_flow_logout_clears_cookie(self, test_user):
        web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        old_cookie = web.cookies.get("refresh_token")
        assert old_cookie

        res = web.post(LOGOUT_URL, headers={"X-Client-Platform": "web"})
        assert res.status_code == 204
        # 삭제 쿠키 헤더: 같은 이름·path로 만료 처리
        set_cookie = res.headers["set-cookie"]
        assert 'refresh_token=""' in set_cookie or "refresh_token=;" in set_cookie.replace('""', "")
        assert "Path=/api/v1/auth" in set_cookie
        # 클라이언트 쿠키통에서도 사라짐
        assert not web.cookies.get("refresh_token")
        # DB에서도 폐기됨 → 갱신 불가
        with SessionLocal() as db:
            row = db.scalar(select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(old_cookie)))
            assert row.revoked_at is not None

    def test_refresh_right_after_web_logout_401(self, test_user):
        """웹 로그아웃 직후 자동 갱신 시도 — 쿠키가 지워져 401이어야 한다."""
        web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        web.post(LOGOUT_URL, headers={"X-Client-Platform": "web"})
        assert web.post(REFRESH_URL, headers={"X-Client-Platform": "web"}).status_code == 401


class TestLogoutHardening:
    """재검증(2차)에서 확인한 엣지 케이스들 — 회귀 방지용."""

    def test_empty_string_token_401(self, test_user):
        res = client.post(LOGOUT_URL, json={"refresh_token": ""}, headers=IOS)
        assert res.status_code == 401

    def test_non_string_token_422_spec_format(self, test_user):
        res = client.post(LOGOUT_URL, json={"refresh_token": 12345}, headers=IOS)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_mixed_ios_header_with_cookie_only(self, test_user):
        """ios 헤더 + 본문 없음 + 쿠키만 있는 요청 — 폴백으로 폐기되고 쿠키도 지워진다."""
        web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        res = web.post(LOGOUT_URL, headers=IOS)  # 헤더만 ios, 토큰은 쿠키에
        assert res.status_code == 204
        assert not web.cookies.get("refresh_token")

    def test_concurrent_double_logout_both_204(self, test_user):
        """동시 이중 로그아웃 — 500 없이 둘 다 204 (멱등 + 원자적 UPDATE)."""
        from concurrent.futures import ThreadPoolExecutor

        tok = _login_native()["refresh_token"]
        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(client.post, LOGOUT_URL,
                                 json={"refresh_token": tok}, headers=IOS)
                       for _ in range(2)]
            codes = sorted(f.result().status_code for f in futures)
        assert codes == [204, 204]

    def test_same_user_other_session_survives(self, test_user):
        """같은 유저의 두 세션 중 하나만 로그아웃 — 나머지는 refresh 가능해야 한다."""
        tok_a = _login_native()["refresh_token"]
        tok_b = _login_native()["refresh_token"]
        client.post(LOGOUT_URL, json={"refresh_token": tok_a}, headers=IOS)
        assert client.post(REFRESH_URL, json={"refresh_token": tok_b},
                           headers=IOS).status_code == 200
