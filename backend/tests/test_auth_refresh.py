"""POST /api/v1/auth/refresh 회귀 테스트 (작업 3-4).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_auth_refresh.py -v

핵심 계약 (api-spec §2):
- Web: 쿠키의 refresh를 자동 사용, 응답도 새 쿠키 (본문에 refresh 없음)
- Native: 본문 {refresh_token} 사용, 응답 본문에 새 refresh
- 회전: 사용한 refresh는 즉시 폐기(revoked_at) — 재사용 시 401
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import decode_access_token, hash_refresh_token
from app.db.models import RefreshToken, User
from app.db.session import SessionLocal
from app.main import app

# refresh 쿠키는 Secure라 http로는 전송되지 않는다 → Web 흐름은 https 가상 주소로
client = TestClient(app)                                  # Native(본문) 테스트용
web = TestClient(app, base_url="https://testserver")      # Web(쿠키 자동 전송) 테스트용

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"

CREDS = {"username": "rftest_user", "password": "refresh-pass-123"}


@pytest.fixture(autouse=True)
def test_user():
    res = client.post(SIGNUP_URL, json={
        "name": "리프레시테스트", "username": CREDS["username"],
        "password": CREDS["password"], "email": "rftest@test.io",
    })
    assert res.status_code == 201
    web.cookies.clear()  # 이전 테스트의 쿠키 오염 방지
    yield res.json()["user"]
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("rftest%")))
        db.commit()


def _login_native() -> dict:
    res = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"})
    assert res.status_code == 200
    return res.json()


class TestRefreshNative:
    def test_body_token_returns_new_pair(self, test_user):
        old = _login_native()
        res = client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"access_token", "refresh_token", "token_type", "expires_in", "user"}
        assert body["expires_in"] == 900
        assert decode_access_token(body["access_token"]) == test_user["id"]
        assert body["refresh_token"] != old["refresh_token"]  # 회전 — 새 토큰

    def test_rotation_revokes_old_and_creates_new_row(self, test_user):
        old = _login_native()
        client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                    headers={"X-Client-Platform": "ios"})
        with SessionLocal() as db:
            rows = db.scalars(select(RefreshToken)
                              .where(RefreshToken.user_id == test_user["id"])).all()
            assert len(rows) == 2
            old_row = next(r for r in rows
                           if r.token_hash == hash_refresh_token(old["refresh_token"]))
            new_row = next(r for r in rows if r is not old_row)
            assert old_row.revoked_at is not None   # 쓴 토큰은 폐기됨
            assert new_row.revoked_at is None

    def test_rotated_token_reuse_is_rejected(self, test_user):
        """회전의 핵심: 한 번 쓴(또는 탈취돼 이미 쓰인) 토큰의 재사용은 401."""
        old = _login_native()
        first = client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                            headers={"X-Client-Platform": "ios"})
        assert first.status_code == 200
        second = client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                             headers={"X-Client-Platform": "ios"})
        assert second.status_code == 401


class TestRefreshWeb:
    def test_cookie_flow_roundtrip(self, test_user):
        """웹: 로그인 쿠키가 자동 전송되고, 응답은 새 쿠키 + 본문엔 refresh 없음."""
        login = web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        assert login.status_code == 200
        old_cookie = web.cookies.get("refresh_token")
        assert old_cookie

        res = web.post(REFRESH_URL, headers={"X-Client-Platform": "web"})  # 본문 없음
        assert res.status_code == 200
        assert "refresh_token" not in res.json()
        assert "set-cookie" in res.headers
        assert web.cookies.get("refresh_token") != old_cookie  # 새 쿠키로 교체됨
        assert decode_access_token(res.json()["access_token"]) == test_user["id"]

    def test_web_old_cookie_value_is_revoked(self, test_user):
        web.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "web"})
        old_cookie = web.cookies.get("refresh_token")
        web.post(REFRESH_URL, headers={"X-Client-Platform": "web"})
        with SessionLocal() as db:
            old_row = db.scalar(select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(old_cookie)))
            assert old_row.revoked_at is not None


class TestRefreshFailures:
    def test_no_token_at_all_401(self, test_user):
        res = client.post(REFRESH_URL, headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_garbage_token_401(self, test_user):
        res = client.post(REFRESH_URL, json={"refresh_token": "totally-fake-token"},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401

    def test_expired_refresh_401(self, test_user):
        old = _login_native()
        with SessionLocal() as db:  # 만료 시뮬레이션
            row = db.scalar(select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(old["refresh_token"])))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        res = client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401

    def test_withdrawn_user_refresh_401(self, test_user):
        old = _login_native()
        with SessionLocal() as db:  # 탈퇴 마커
            db.get(User, test_user["id"]).deleted_at = datetime.now(timezone.utc)
            db.commit()
        res = client.post(REFRESH_URL, json={"refresh_token": old["refresh_token"]},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401

    def test_access_token_cannot_be_used_as_refresh(self, test_user):
        """access(JWT)를 refresh 자리에 넣어도 통하면 안 된다 (형식이 달라 해시 불일치)."""
        old = _login_native()
        res = client.post(REFRESH_URL, json={"refresh_token": old["access_token"]},
                          headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401


class TestRefreshHardening:
    """재검증(2차)에서 확인한 엣지 케이스들 — 회귀 방지용."""

    @pytest.mark.parametrize("payload", [{}, {"refresh_token": None}, {"refresh_token": ""}])
    def test_empty_body_variants_401(self, test_user, payload):
        res = client.post(REFRESH_URL, json=payload, headers={"X-Client-Platform": "ios"})
        assert res.status_code == 401

    def test_chained_refresh_works(self, test_user):
        """refresh로 받은 새 토큰으로 다시 refresh — 회전이 무한히 이어져야 한다."""
        t0 = _login_native()["refresh_token"]
        r1 = client.post(REFRESH_URL, json={"refresh_token": t0},
                         headers={"X-Client-Platform": "ios"})
        t1 = r1.json()["refresh_token"]
        r2 = client.post(REFRESH_URL, json={"refresh_token": t1},
                         headers={"X-Client-Platform": "ios"})
        assert r2.status_code == 200
        assert r2.json()["refresh_token"] not in (t0, t1)

    def test_web_header_with_body_token_fallback(self, test_user):
        """web 헤더인데 쿠키가 없고 본문에 토큰이 있으면 그걸 쓴다 (관용 폴백)."""
        tok = _login_native()["refresh_token"]
        res = client.post(REFRESH_URL, json={"refresh_token": tok},
                          headers={"X-Client-Platform": "web"})
        assert res.status_code == 200

    def test_concurrent_refresh_exactly_one_wins(self, test_user):
        """동시성 레이스 방어 (재검증에서 발견: 10회 중 8회 이중 성공 → 원자적 소비로 수정):
        같은 토큰으로 동시에 2요청 → 정확히 1개만 200, 나머지는 401이어야 한다."""
        from concurrent.futures import ThreadPoolExecutor

        for _ in range(5):
            tok = _login_native()["refresh_token"]
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = [
                    ex.submit(client.post, REFRESH_URL,
                              json={"refresh_token": tok},
                              headers={"X-Client-Platform": "ios"})
                    for _ in range(2)
                ]
                codes = sorted(f.result().status_code for f in futures)
            assert codes == [200, 401], f"이중 성공 또는 이중 실패: {codes}"

    def test_revoked_and_garbage_tokens_indistinguishable(self, test_user):
        """폐기된 토큰과 존재한 적 없는 토큰의 응답이 완전히 같아야 한다 (정보 노출 방지)."""
        tok = _login_native()["refresh_token"]
        client.post(REFRESH_URL, json={"refresh_token": tok},
                    headers={"X-Client-Platform": "ios"})  # 소비 → 폐기됨
        r_revoked = client.post(REFRESH_URL, json={"refresh_token": tok},
                                headers={"X-Client-Platform": "ios"})
        r_garbage = client.post(REFRESH_URL, json={"refresh_token": "x" * 64},
                                headers={"X-Client-Platform": "ios"})
        assert r_revoked.status_code == r_garbage.status_code == 401
        assert r_revoked.json() == r_garbage.json()
