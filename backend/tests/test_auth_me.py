"""GET /api/v1/auth/me + 인증 의존성 회귀 테스트 (작업 3-6).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_auth_me.py -v

가장 중요한 계약: access 만료는 정확히 401 "TOKEN_EXPIRED" —
FE의 자동 갱신 인터셉터가 이 문자열로 refresh 여부를 결정한다.
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
from tests.conftest import mark_email_verified

client = TestClient(app)

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"

CREDS = {"username": "metest_user", "password": "me-pass-12345"}


@pytest.fixture(autouse=True)
def test_user():
    res = client.post(SIGNUP_URL, json={
        "name": "미테스트", "username": CREDS["username"],
        "password": CREDS["password"], "email": "metest@test.io",
    })
    assert res.status_code == 201
    mark_email_verified(CREDS["username"])  # 로그인 차단(403) 우회
    yield res.json()["user"]
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("metest%")))
        db.commit()


def _access_token() -> str:
    return client.post(LOGIN_URL, json=CREDS,
                       headers={"X-Client-Platform": "ios"}).json()["access_token"]


def _expired_token(user_id: str) -> str:
    """실제 시크릿으로 서명했지만 이미 만료된 access 토큰."""
    return pyjwt.encode(
        {"sub": user_id, "type": "access",
         "iat": datetime.now(timezone.utc) - timedelta(seconds=1000),
         "exp": datetime.now(timezone.utc) - timedelta(seconds=100)},
        settings.jwt_secret, algorithm="HS256",
    )


class TestMeSuccess:
    def test_returns_current_user(self, test_user):
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {_access_token()}"})
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"id", "name", "username", "email"}  # 로그인 user와 동일 형태
        assert body["id"] == test_user["id"]
        assert body["username"] == CREDS["username"]

    def test_lowercase_bearer_scheme_accepted(self, test_user):
        """HTTP 인증 스킴은 대소문자 무구분(RFC 7235) — 'bearer'도 받아야 한다."""
        res = client.get(ME_URL, headers={"Authorization": f"bearer {_access_token()}"})
        assert res.status_code == 200


class TestMeFailures:
    def test_no_header_401_unauthorized(self, test_user):
        res = client.get(ME_URL)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_expired_token_is_exactly_TOKEN_EXPIRED(self, test_user):
        """FE 인터셉터 계약의 핵심 — 만료는 UNAUTHORIZED가 아니라 TOKEN_EXPIRED."""
        res = client.get(ME_URL, headers={
            "Authorization": f"Bearer {_expired_token(test_user['id'])}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "TOKEN_EXPIRED"

    def test_garbage_token_401_unauthorized_not_expired(self, test_user):
        """위조 토큰은 TOKEN_EXPIRED가 아니어야 한다 (인터셉터가 무한 refresh 루프에 빠짐)."""
        res = client.get(ME_URL, headers={"Authorization": "Bearer not-a-real-token"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.parametrize("header", [
        "Basic dXNlcjpwYXNz",   # 다른 인증 방식
        "Bearer",                # 토큰 없음
        "Bearer ",               # 공백뿐
    ])
    def test_malformed_authorization_401(self, test_user, header):
        res = client.get(ME_URL, headers={"Authorization": header})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_refresh_token_cannot_access_me(self, test_user):
        """refresh 토큰(불투명 문자열)을 Bearer 자리에 넣어도 통하면 안 된다."""
        login = client.post(LOGIN_URL, json=CREDS, headers={"X-Client-Platform": "ios"}).json()
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {login['refresh_token']}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_valid_signature_unknown_user_401(self, test_user):
        """서명은 유효하나 없는 유저를 가리키는 토큰 → 401 (DB 조회에서 걸러짐)."""
        ghost = pyjwt.encode(
            {"sub": "usr_GhostGhostGhostXXXX", "type": "access",
             "iat": datetime.now(timezone.utc),
             "exp": datetime.now(timezone.utc) + timedelta(seconds=900)},
            settings.jwt_secret, algorithm="HS256",
        )
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {ghost}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.parametrize("bad_sub_payload", [
        {"type": "access"},                 # sub 없음
        {"sub": 12345, "type": "access"},   # sub 숫자
    ])
    def test_malformed_sub_token_401_not_500(self, test_user, bad_sub_payload):
        """sub가 없거나 숫자인 유효 서명 토큰 → 500이 아니라 401 (재검증에서 발견한 버그)."""
        bad_sub_payload = {
            **bad_sub_payload,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=900),
        }
        token = pyjwt.encode(bad_sub_payload, settings.jwt_secret, algorithm="HS256")
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_alg_none_forged_token_401(self, test_user):
        """alg=none 위조 토큰 → 401 (서명 우회 차단)."""
        import base64
        import json

        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
        body = base64.urlsafe_b64encode(
            json.dumps({"sub": test_user["id"], "type": "access"}).encode()
        ).rstrip(b"=")
        forged = f"{header.decode()}.{body.decode()}."
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_valid_token_of_withdrawn_user_401(self, test_user):
        """토큰 유효기간(15분) 안에 탈퇴한 경우 — 토큰이 살아있어도 차단해야 한다."""
        token = _access_token()
        with SessionLocal() as db:
            db.get(User, test_user["id"]).deleted_at = datetime.now(timezone.utc)
            db.commit()
        res = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"
