"""/users/me 라우터 골격 회귀 테스트 (Step 4 작업 2).

실행:
    cd backend
    DATABASE_URL=postgresql+psycopg://rehearsal:asdf1234@localhost:5432/rehearsal_dev \
      python -m pytest tests/test_users_me.py -v

이 단계에서 검증하는 것은 **라우팅 + 인증 배선**뿐이다(핸들러 본문은 작업 3~6에서 채움):
  - 4개 엔드포인트가 /api/v1/users/me* 에 등록됐는가
  - 토큰 없이 호출하면 401 (get_current_user 가드가 걸렸는가)
  - 유효 토큰이면 핸들러까지 도달해 501 NOT_IMPLEMENTED (아직 미구현 표식)

주의: 실제 로컬 DB(rehearsal_dev)에 붙는다. 테스트 유저는 'umtest' 접두사를 쓰고
각 테스트 후 fixture가 지운다.
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import settings
from app.db.models import User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

ME_URL = "/api/v1/users/me"
PW_URL = "/api/v1/users/me/password"
CREDS = {"username": "umtest_user", "password": "um-pass-12345"}

# (method, url) — 4개 엔드포인트 전체 (인증 배선은 구현 여부와 무관하게 전부 적용)
ENDPOINTS = [
    ("GET", ME_URL),
    ("PATCH", ME_URL),
    ("PATCH", PW_URL),
    ("DELETE", ME_URL),
]

# 아직 미구현(501 골격)인 엔드포인트 — 구현되면 여기서 빼고 기능 테스트로 대체한다.
# 작업 3: GET /me 구현 완료 → 목록에서 제외.
PENDING_ENDPOINTS = [
    ("PATCH", ME_URL),
    ("PATCH", PW_URL),
    ("DELETE", ME_URL),
]


@pytest.fixture(autouse=True)
def test_user():
    res = client.post("/api/v1/auth/signup", json={
        "name": "마이테스트", "username": CREDS["username"],
        "password": CREDS["password"], "email": "umtest@test.io",
    })
    assert res.status_code == 201
    user = res.json()["user"]
    yield user
    # id로도 지운다 — 익명화 테스트는 username을 NULL로 만들어 ilike로는 안 잡히므로
    # (그대로 두면 익명화 고아 행이 남는다). 접두사 조건은 이전 실패 잔여분 청소용.
    with SessionLocal() as db:
        db.execute(delete(User).where(
            (User.id == user["id"]) | (User.username.ilike("umtest%"))
        ))
        db.commit()


def _token() -> str:
    return client.post("/api/v1/auth/login", json=CREDS,
                       headers={"X-Client-Platform": "ios"}).json()["access_token"]


def _expired_token(user_id: str) -> str:
    """실제 시크릿으로 서명했지만 이미 만료된 access 토큰 (test_auth_me와 동일 방식)."""
    return pyjwt.encode(
        {"sub": user_id, "type": "access",
         "iat": datetime.now(timezone.utc) - timedelta(seconds=1000),
         "exp": datetime.now(timezone.utc) - timedelta(seconds=100)},
        settings.jwt_secret, algorithm="HS256",
    )


def _call(method: str, url: str, headers: dict | None = None):
    return client.request(method, url, headers=headers or {})


class TestRouteRegistration:
    def test_all_four_routes_registered(self):
        """4개 (method, path)가 OpenAPI 스키마에 정확히 등록됐다."""
        paths = app.openapi()["paths"]
        methods_me = {m.upper() for m in paths["/api/v1/users/me"]}
        methods_pw = {m.upper() for m in paths["/api/v1/users/me/password"]}
        assert {"GET", "PATCH", "DELETE"} <= methods_me
        assert "PATCH" in methods_pw


class TestAuthWiring:
    @pytest.mark.parametrize("method,url", ENDPOINTS)
    def test_requires_auth(self, method, url):
        """토큰 없이 호출 → 401 (get_current_user 가드 배선 확인)."""
        res = _call(method, url)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.parametrize("method,url", ENDPOINTS)
    def test_invalid_token_rejected(self, method, url):
        """엉터리 토큰 → 401 (핸들러 도달 전 차단)."""
        res = _call(method, url, headers={"Authorization": "Bearer not-a-real-token"})
        assert res.status_code == 401

    @pytest.mark.parametrize("method,url", ENDPOINTS)
    def test_expired_token_returns_token_expired(self, method, url, test_user):
        """만료 토큰 → 정확히 401 "TOKEN_EXPIRED".

        FE 자동 갱신 인터셉터가 이 코드 문자열로 refresh 여부를 판단한다(api-spec §2·§6.2).
        /users/me도 get_current_user를 쓰므로 이 계약을 상속 — 의존성이 바뀌어도
        깨지지 않게 4개 엔드포인트 전부에 대해 고정한다."""
        res = _call(method, url,
                    headers={"Authorization": f"Bearer {_expired_token(test_user['id'])}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


class TestSkeletonReachable:
    @pytest.mark.parametrize("method,url", PENDING_ENDPOINTS)
    def test_valid_token_reaches_handler(self, method, url):
        """미구현 엔드포인트: 유효 토큰 → 핸들러 도달 → 501 NOT_IMPLEMENTED (골격 표식).

        작업 4~6에서 각 핸들러를 구현하면 여기서 빼고 기능 테스트로 대체한다."""
        res = _call(method, url, headers={"Authorization": f"Bearer {_token()}"})
        assert res.status_code == 501
        assert res.json()["error"]["code"] == "NOT_IMPLEMENTED"


class TestGetMe:
    """작업 3 — GET /users/me 기능 검증."""

    def test_returns_current_user(self, test_user):
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {_token()}"})
        assert res.status_code == 200
        body = res.json()
        # api-spec §2.1 응답 형태 — 정확히 5필드
        assert set(body) == {"id", "name", "username", "email", "email_verified"}
        assert body["id"] == test_user["id"]
        assert body["username"] == CREDS["username"]
        assert body["name"] == "마이테스트"
        assert body["email"] == "umtest@test.io"

    def test_email_verified_false_for_unverified_signup(self, test_user):
        """갓 가입한 유저는 email_verified_at=None → email_verified=False."""
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {_token()}"})
        assert res.json()["email_verified"] is False

    def test_email_verified_true_when_verified(self, test_user):
        """email_verified_at이 채워지면 email_verified=True (파생 규약 고정)."""
        with SessionLocal() as db:
            db.execute(
                User.__table__.update()
                .where(User.id == test_user["id"])
                .values(email_verified_at=datetime.now(timezone.utc))
            )
            db.commit()
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {_token()}"})
        assert res.status_code == 200
        assert res.json()["email_verified"] is True

    def test_reflects_no_password_hash_leak(self, test_user):
        """응답에 password_hash·deleted_at 등 내부 필드가 새지 않는다."""
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {_token()}"})
        body = res.json()
        assert "password_hash" not in body
        assert "deleted_at" not in body

    def test_anonymized_user_with_valid_token_gets_401_not_500(self, test_user):
        """탈퇴(익명화)로 PII가 NULL이 된 유저가 아직 만료 안 된 토큰을 들고 와도
        401로 막힌다 — get_current_user가 deleted_at을 보고 차단하므로, non-null
        UserOut이 NULL name/username/email로 500나는 사고가 없다.
        작업 6 익명화 설계와 GET의 계약을 함께 고정."""
        token = _token()  # 활성 상태에서 유효 토큰 확보
        with SessionLocal() as db:
            db.execute(
                User.__table__.update().where(User.id == test_user["id"]).values(
                    username=None, password_hash=None, name=None, email=None,
                    deleted_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


class TestContractLocks:
    """작업 3~6이 계약을 벗어나지 않게 지금 고정 — 구현이 이 값들을 바꾸면 실패한다."""

    def test_success_status_codes_declared(self):
        """조회/수정은 200, 비번변경/탈퇴는 204로 선언 — 구현이 200 본문을 돌려주면
        여기서 잡힌다 (작업 5·6은 204 no-body 계약)."""
        paths = app.openapi()["paths"]
        assert "200" in paths["/api/v1/users/me"]["get"]["responses"]
        assert "200" in paths["/api/v1/users/me"]["patch"]["responses"]
        assert "204" in paths["/api/v1/users/me"]["delete"]["responses"]
        assert "204" in paths["/api/v1/users/me/password"]["patch"]["responses"]

    def test_get_and_patch_me_use_user_out_schema(self):
        """GET·PATCH /me 200 응답 스키마가 UserOut(5필드)로 고정됐는가."""
        paths = app.openapi()["paths"]
        for method in ("get", "patch"):
            schema_ref = (paths["/api/v1/users/me"][method]["responses"]["200"]
                          ["content"]["application/json"]["schema"]["$ref"])
            assert schema_ref.endswith("/UserOut")

    @pytest.mark.parametrize("method,url", [
        ("POST", ME_URL),      # /me는 GET·PATCH·DELETE만
        ("PUT", ME_URL),
        ("GET", PW_URL),       # /me/password는 PATCH만
        ("POST", PW_URL),
        ("DELETE", PW_URL),
    ])
    def test_unexposed_methods_405(self, method, url):
        """선언 안 한 메서드는 405 — 실수로 과다 노출되지 않았는지 확인."""
        assert _call(method, url).status_code == 405
