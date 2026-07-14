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
from sqlalchemy import delete, select

from app.core.config import settings
from app.db import models
from app.db.models import RefreshToken, SocialAccount, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

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

# 테스트가 만든 유저·팀 id 등록부 — teardown이 팀(→세션·멤버 CASCADE) 먼저,
# 그다음 유저를 지운다. 익명화는 username을 NULL로 만들어 ilike로 안 잡히므로 id 등록 필수.
_user_ids: list[str] = []
_team_ids: list[str] = []


def _signup(username: str, email: str, password: str = "um-pass-12345",
            name: str = "마이테스트") -> dict:
    res = client.post("/api/v1/auth/signup", json={
        "name": name, "username": username, "password": password, "email": email,
    })
    assert res.status_code == 201, res.text
    user = res.json()["user"]
    _user_ids.append(user["id"])
    mark_email_verified(username)  # 로그인 차단(403) 우회
    return user


def _create_team(token: str, name: str = "테스트팀") -> dict:
    res = client.post("/api/v1/teams", json={"name": name},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 201, res.text
    team = res.json()
    _team_ids.append(team["id"])
    return team


@pytest.fixture(autouse=True)
def test_user():
    _user_ids.clear()
    _team_ids.clear()
    user = _signup(CREDS["username"], "umtest@test.io", CREDS["password"], "마이테스트")
    yield user
    # 팀을 먼저 지운다 — 세션(owner_id RESTRICT)·멤버십·초대가 팀 CASCADE로 함께 사라져야
    # 그다음 유저 하드삭제가 owner_id RESTRICT에 안 걸린다. 접두사 조건은 잔여분 보험.
    with SessionLocal() as db:
        if _team_ids:
            db.execute(delete(Team).where(Team.id.in_(_team_ids)))
        db.execute(delete(User).where(
            User.id.in_(_user_ids) | User.username.ilike("umtest%")
        ))
        db.commit()


def _login() -> dict:
    """Native 로그인 → access·refresh 둘 다 본문으로 받는다 (X-Client-Platform: ios)."""
    return client.post("/api/v1/auth/login", json=CREDS,
                       headers={"X-Client-Platform": "ios"}).json()


def _token() -> str:
    return _login()["access_token"]


def _expired_token(user_id: str) -> str:
    """실제 시크릿으로 서명했지만 이미 만료된 access 토큰 (test_auth_me와 동일 방식)."""
    return pyjwt.encode(
        {"sub": user_id, "type": "access",
         "iat": datetime.now(timezone.utc) - timedelta(seconds=1000),
         "exp": datetime.now(timezone.utc) - timedelta(seconds=100)},
        settings.jwt_secret, algorithm="HS256",
    )


def _call(method: str, url: str, headers: dict | None = None, json=None):
    return client.request(method, url, headers=headers or {}, json=json)


def _auth(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or _token()}"}


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

    def test_email_verified_false_when_not_verified(self, test_user):
        """email_verified_at=None → email_verified=False (파생 규약 고정).

        로그인 강제 도입 후 미인증 유저는 로그인 자체가 403이므로, 토큰을 먼저
        받고 인증 표식을 되돌려 '이미 로그인돼 있던 미인증 세션'을 재현한다
        (기존 세션은 차단되지 않는다는 plan §5-4 노트의 실제 시나리오)."""
        token = _token()
        with SessionLocal() as db:
            db.execute(
                User.__table__.update()
                .where(User.id == test_user["id"])
                .values(email_verified_at=None)
            )
            db.commit()
        res = _call("GET", ME_URL, headers={"Authorization": f"Bearer {token}"})
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


class TestUpdateMe:
    """작업 4 — PATCH /users/me (닉네임 수정) 기능 검증."""

    def test_updates_nickname(self, test_user):
        res = _call("PATCH", ME_URL, headers=_auth(), json={"name": "바뀐닉"})
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "바뀐닉"
        # 나머지 필드는 그대로
        assert body["id"] == test_user["id"]
        assert body["username"] == CREDS["username"]
        assert body["email"] == "umtest@test.io"
        assert set(body) == {"id", "name", "username", "email", "email_verified"}

    def test_change_persists(self, test_user):
        """수정이 DB에 반영돼 이후 GET에서도 보인다."""
        _call("PATCH", ME_URL, headers=_auth(), json={"name": "영속닉"})
        res = _call("GET", ME_URL, headers=_auth())
        assert res.json()["name"] == "영속닉"

    def test_name_stripped_server_side(self, test_user):
        """서버가 앞뒤 공백을 제거해 저장한다(스키마 strip_name)."""
        res = _call("PATCH", ME_URL, headers=_auth(), json={"name": "  공백닉  "})
        assert res.json()["name"] == "공백닉"

    @pytest.mark.parametrize("bad", [
        {"name": ""},            # 빈 이름
        {"name": "   "},         # 공백만
        {"name": "가" * 31},     # 30자 초과
        {},                      # name 누락
    ])
    def test_invalid_body_422(self, test_user, bad):
        res = _call("PATCH", ME_URL, headers=_auth(), json=bad)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_username_change_rejected(self, test_user):
        """username 등 다른 필드 변경 시도는 extra=forbid로 422 — 닉네임만 수정 가능."""
        res = _call("PATCH", ME_URL, headers=_auth(),
                    json={"name": "새닉", "username": "hacker"})
        assert res.status_code == 422
        # username은 바뀌지 않았다
        assert _call("GET", ME_URL, headers=_auth()).json()["username"] == CREDS["username"]

    def test_no_token_no_body_is_401_not_422(self, test_user):
        """인증이 바디 검증보다 먼저 — 무토큰+무바디 PATCH는 401(인증)이지 422가 아니다.
        (작업 2 감사에서 예고한 순서 계약 고정)."""
        res = _call("PATCH", ME_URL)  # 토큰·바디 둘 다 없음
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_token_but_no_body_is_422(self, test_user):
        """인증은 됐지만 바디 없음 → 422 (name 필수)."""
        res = _call("PATCH", ME_URL, headers=_auth())
        assert res.status_code == 422

    def test_preserves_email_verified(self, test_user):
        """닉네임만 바꾼다 — 이메일 인증 상태(email_verified_at)는 건드리지 않는다."""
        with SessionLocal() as db:
            db.execute(User.__table__.update().where(User.id == test_user["id"])
                       .values(email_verified_at=datetime.now(timezone.utc)))
            db.commit()
        res = _call("PATCH", ME_URL, headers=_auth(), json={"name": "여전히인증됨"})
        assert res.status_code == 200
        assert res.json()["email_verified"] is True
        # DB에도 인증 시각이 그대로 남아 있다
        with SessionLocal() as db:
            u = db.get(User, test_user["id"])
            assert u.email_verified_at is not None and u.name == "여전히인증됨"

    def test_anonymized_user_cannot_resurrect_name(self, test_user):
        """탈퇴(익명화)된 유저가 유효 토큰으로 PATCH해도 401 — get_current_user가
        deleted_at으로 막으므로 NULL이 된 name을 되살릴 수 없다(GET과 대칭 방어)."""
        token = _token()  # 활성 상태에서 유효 토큰 확보
        with SessionLocal() as db:
            db.execute(User.__table__.update().where(User.id == test_user["id"]).values(
                username=None, password_hash=None, name=None, email=None,
                deleted_at=datetime.now(timezone.utc),
            ))
            db.commit()
        res = _call("PATCH", ME_URL, headers=_auth(token), json={"name": "부활시도"})
        assert res.status_code == 401
        # name이 되살아나지 않고 NULL로 유지된다
        with SessionLocal() as db:
            assert db.get(User, test_user["id"]).name is None


class TestChangePassword:
    """작업 5 — PATCH /users/me/password (비밀번호 변경) 기능 검증."""

    NEW_PW = "new-strong-pw-9876"

    def _body(self, **over) -> dict:
        b = {"current_password": CREDS["password"], "new_password": self.NEW_PW}
        b.update(over)
        return b

    def _login_status(self, password: str) -> int:
        return client.post("/api/v1/auth/login",
                           json={"username": CREDS["username"], "password": password},
                           headers={"X-Client-Platform": "ios"}).status_code

    def test_success_returns_204_and_switches_password(self, test_user):
        res = _call("PATCH", PW_URL, headers=_auth(), json=self._body())
        assert res.status_code == 204
        assert res.content == b""              # 204 no-body 계약
        assert self._login_status(self.NEW_PW) == 200          # 새 비번으로 로그인 OK
        assert self._login_status(CREDS["password"]) == 401    # 옛 비번은 실패

    def test_wrong_current_password_400_and_unchanged(self, test_user):
        res = _call("PATCH", PW_URL, headers=_auth(),
                    json=self._body(current_password="totally-wrong"))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"
        # 비번은 바뀌지 않았다 — 기존 비번으로 여전히 로그인된다
        assert self._login_status(CREDS["password"]) == 200

    def test_revokes_all_refresh_tokens(self, test_user):
        """비번 변경 → 변경 전 발급된 refresh 토큰은 무력화(refresh 시 401)."""
        old_refresh = _login()["refresh_token"]
        res = _call("PATCH", PW_URL, headers=_auth(), json=self._body())
        assert res.status_code == 204
        refreshed = client.post("/api/v1/auth/refresh",
                                json={"refresh_token": old_refresh},
                                headers={"X-Client-Platform": "ios"})
        assert refreshed.status_code == 401

    def test_social_only_account_400(self, test_user):
        """로컬 비번이 없는(소셜 전용) 계정 → 400 NO_PASSWORD_SET."""
        token = _token()  # password_hash NULL 만들기 전에 토큰 확보
        with SessionLocal() as db:
            db.execute(User.__table__.update().where(User.id == test_user["id"])
                       .values(password_hash=None))
            db.commit()
        res = _call("PATCH", PW_URL, headers=_auth(token), json=self._body())
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "NO_PASSWORD_SET"

    def test_new_password_over_bcrypt_byte_limit_400(self, test_user):
        """스키마(≤128자)는 통과하지만 bcrypt 72바이트 상한 초과(한글 30자=90바이트)
        → 500이 아니라 400 PASSWORD_TOO_LONG (작업 1 감사 메모 실현).
        해시 실패는 password_hash 대입 전에 raise되므로 기존 비번은 그대로."""
        res = _call("PATCH", PW_URL, headers=_auth(), json=self._body(new_password="가" * 30))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "PASSWORD_TOO_LONG"
        assert self._login_status(CREDS["password"]) == 200  # 옛 비번 그대로 유효

    def test_anonymized_user_cannot_reset_password(self, test_user):
        """탈퇴(익명화)된 유저가 유효 토큰으로 비번 변경해도 401 — get_current_user가
        deleted_at으로 막아 password_hash를 되살리지 못한다(GET/PATCH와 대칭 방어)."""
        token = _token()
        with SessionLocal() as db:
            db.execute(User.__table__.update().where(User.id == test_user["id"]).values(
                username=None, password_hash=None, name=None, email=None,
                deleted_at=datetime.now(timezone.utc),
            ))
            db.commit()
        res = _call("PATCH", PW_URL, headers=_auth(token), json=self._body())
        assert res.status_code == 401
        with SessionLocal() as db:  # 되살아나지 않고 NULL 유지
            assert db.get(User, test_user["id"]).password_hash is None

    def test_other_users_refresh_not_revoked(self, test_user):
        """내 비번 변경은 내 refresh만 폐기 — 다른 유저의 세션은 살아 있다
        (revoke 쿼리의 user_id 필터 격리 확인)."""
        # 두 번째 유저(umtest2) 생성 후 refresh 확보
        client.post("/api/v1/auth/signup", json={
            "name": "마이테스트2", "username": "umtest2_user",
            "password": "um2-pass-12345", "email": "umtest2@test.io",
        })
        mark_email_verified("umtest2_user")  # 로그인 차단(403) 우회
        other_refresh = client.post("/api/v1/auth/login",
            json={"username": "umtest2_user", "password": "um2-pass-12345"},
            headers={"X-Client-Platform": "ios"}).json()["refresh_token"]
        # 내(umtest) 비번 변경
        assert _call("PATCH", PW_URL, headers=_auth(), json=self._body()).status_code == 204
        # 다른 유저 refresh는 여전히 유효
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": other_refresh},
                        headers={"X-Client-Platform": "ios"})
        assert r.status_code == 200

    @pytest.mark.parametrize("bad,code", [
        ({"current_password": CREDS["password"], "new_password": "short7!"}, "VALIDATION_ERROR"),  # 8자 미만
        ({"new_password": "new-strong-pw-9876"}, "VALIDATION_ERROR"),                              # current 누락
        ({"current_password": CREDS["password"]}, "VALIDATION_ERROR"),                             # new 누락
        ({"current_password": "", "new_password": "new-strong-pw-9876"}, "VALIDATION_ERROR"),      # current 빈값
    ])
    def test_invalid_body_422(self, test_user, bad, code):
        res = _call("PATCH", PW_URL, headers=_auth(), json=bad)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == code

    def test_unknown_field_rejected(self, test_user):
        """new_pasword 같은 오타 → 422 (extra=forbid), 비번은 안 바뀐다."""
        res = _call("PATCH", PW_URL, headers=_auth(),
                    json={"current_password": CREDS["password"], "new_pasword": self.NEW_PW})
        assert res.status_code == 422
        assert self._login_status(CREDS["password"]) == 200  # 변경 안 됨

    def test_no_token_no_body_is_401_not_422(self, test_user):
        """인증이 바디 검증보다 먼저 — 무토큰+무바디 → 401."""
        res = _call("PATCH", PW_URL)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


class TestDeleteMe:
    """작업 6 — DELETE /users/me (회원 탈퇴 = 익명화, §7.1). 최난도."""

    def test_anonymizes_not_hard_delete(self, test_user):
        """하드삭제가 아니라 익명화 — row는 남고 PII만 NULL + deleted_at."""
        res = _call("DELETE", ME_URL, headers=_auth())
        assert res.status_code == 204
        assert res.content == b""
        with SessionLocal() as db:
            u = db.get(User, test_user["id"])
            assert u is not None                        # row 보존
            assert u.username is None and u.password_hash is None
            assert u.name is None and u.email is None
            assert u.deleted_at is not None             # 익명화 마커

    def test_token_and_relogin_blocked_after_delete(self, test_user):
        """탈퇴 후: 기존 토큰은 401, 옛 자격증명 재로그인도 401(탈퇴 유저 차단)."""
        token = _token()
        assert _call("DELETE", ME_URL, headers=_auth(token)).status_code == 204
        assert _call("GET", ME_URL, headers=_auth(token)).status_code == 401
        assert client.post("/api/v1/auth/login", json=CREDS,
                           headers={"X-Client-Platform": "ios"}).status_code == 401

    def test_refresh_tokens_revoked(self, test_user):
        refresh = _login()["refresh_token"]
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh},
                        headers={"X-Client-Platform": "ios"})
        assert r.status_code == 401
        with SessionLocal() as db:
            rows = db.scalars(select(RefreshToken).where(
                RefreshToken.user_id == test_user["id"])).all()
            assert rows and all(t.revoked_at is not None for t in rows)

    def test_social_accounts_deleted(self, test_user):
        with SessionLocal() as db:
            db.add(SocialAccount(user_id=test_user["id"], provider="google",
                                 provider_user_id="g-123"))
            db.commit()
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        with SessionLocal() as db:
            n = db.scalars(select(SocialAccount).where(
                SocialAccount.user_id == test_user["id"])).all()
            assert n == []

    def test_reregister_same_username_email_allowed(self, test_user):
        """익명화(PII NULL)라 부분 유니크 인덱스와 안 부딪혀 재가입 허용."""
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        res = client.post("/api/v1/auth/signup", json={
            "name": "재가입", "username": CREDS["username"],
            "password": CREDS["password"], "email": "umtest@test.io",
        })
        assert res.status_code == 201
        _user_ids.append(res.json()["user"]["id"])  # teardown 등록

    def test_solo_team_leader_delete_removes_team(self, test_user):
        """혼자인 팀의 팀장 탈퇴 → 팀 통째로 삭제(세션 CASCADE)."""
        team = _create_team(_token())
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        with SessionLocal() as db:
            assert db.get(Team, team["id"]) is None

    def test_leader_succession_on_delete(self, test_user):
        """멤버가 더 있는 팀의 팀장 탈퇴 → 최고참 승계 + 내 멤버십 제거, 팀 보존."""
        team = _create_team(_token())
        other = _signup("umtest_succ", "umtest_succ@test.io", name="후임")
        with SessionLocal() as db:  # 두 번째 멤버 직접 추가(초대 플로우 생략)
            db.add(TeamMember(team_id=team["id"], user_id=other["id"]))
            db.commit()
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        with SessionLocal() as db:
            t = db.get(Team, team["id"])
            assert t is not None and t.leader_id == other["id"]     # 승계됨
            assert db.get(TeamMember, (team["id"], test_user["id"])) is None  # 내 멤버십 제거

    def test_owner_sessions_preserved_when_team_survives(self, test_user):
        """팀이 살아남으면 내가 owner인 세션은 보존 — owner_id는 익명화된 나를 계속 가리킨다."""
        team = _create_team(_token())
        other = _signup("umtest_keep", "umtest_keep@test.io", name="잔류")
        with SessionLocal() as db:
            db.add(TeamMember(team_id=team["id"], user_id=other["id"]))
            db.commit()
        sess = client.post(f"/api/v1/teams/{team['id']}/sessions",
            json={"name": "내발표", "personas": ["egen"], "question_count": 3,
                  "time_limit_minutes": 10, "mode": "upload"},
            headers=_auth()).json()
        assert _call("DELETE", ME_URL, headers=_auth()).status_code == 204
        with SessionLocal() as db:
            s = db.get(models.RehearsalSession, sess["id"])
            assert s is not None and s.owner_id == test_user["id"]  # 세션 보존
            u = db.get(User, test_user["id"])
            assert u.deleted_at is not None and u.name is None       # 나는 익명화됨


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
