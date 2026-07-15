"""POST /api/v1/auth/signup 회귀 테스트 (작업 3-2).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_auth_signup.py -v

주의: 실제 로컬 DB(rehearsal_dev)에 붙는다. 테스트 유저는 전부 'sgtest' 접두사를
쓰고, 각 테스트가 끝나면 fixture가 지운다 — 실패해도 잔여 데이터가 남지 않는다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.models import EmailVerification, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

SIGNUP_URL = "/api/v1/auth/signup"


def _valid_body(**overrides) -> dict:
    body = {
        "name": "가입테스트",
        "username": "sgtest_user",
        "password": "safe-password-123",
        "email": "sgtest@test.io",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def cleanup():
    """각 테스트 후 sgtest 유저 제거 (email_verifications는 FK cascade로 함께 삭제)."""
    yield
    with SessionLocal() as db:
        db.execute(delete(User).where(User.username.ilike("sgtest%")))
        db.commit()


class TestSignupSuccess:
    def test_returns_201_with_user(self):
        res = client.post(SIGNUP_URL, json=_valid_body())
        assert res.status_code == 201
        user = res.json()["user"]
        assert user["id"].startswith("usr_") and len(user["id"]) == 24
        assert user["name"] == "가입테스트"
        assert user["username"] == "sgtest_user"
        assert user["email"] == "sgtest@test.io"
        assert user["email_verified"] is False  # 미인증 유저로 생성 (spec §2)

    def test_password_stored_hashed_not_plaintext(self):
        res = client.post(SIGNUP_URL, json=_valid_body())
        uid = res.json()["user"]["id"]
        with SessionLocal() as db:
            row = db.get(User, uid)
            assert row.password_hash != "safe-password-123"
            assert "safe-password-123" not in row.password_hash
            assert row.password_hash.startswith("$2")  # bcrypt 형식

    def test_verification_code_row_created_hashed(self):
        res = client.post(SIGNUP_URL, json=_valid_body())
        uid = res.json()["user"]["id"]
        with SessionLocal() as db:
            ev = db.scalar(select(EmailVerification).where(EmailVerification.user_id == uid))
            assert ev is not None, "인증코드 행이 안 생김"
            assert ev.consumed_at is None
            assert ev.code_hash.startswith("$2")  # bcrypt — 원문 6자리 평문이 아님
            assert ev.attempt_count == 0


class TestSignupConflicts:
    def test_duplicate_username_409(self):
        client.post(SIGNUP_URL, json=_valid_body())
        res = client.post(SIGNUP_URL, json=_valid_body(email="sgtest2@test.io"))
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "USERNAME_TAKEN"

    def test_duplicate_username_case_insensitive(self):
        """DB 부분 유니크가 lower() 기준이므로 API도 대소문자 무시로 막아야 한다."""
        client.post(SIGNUP_URL, json=_valid_body())
        res = client.post(
            SIGNUP_URL, json=_valid_body(username="SGTEST_USER", email="sgtest2@test.io")
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "USERNAME_TAKEN"

    def test_duplicate_email_409_case_insensitive(self):
        client.post(SIGNUP_URL, json=_valid_body())
        res = client.post(
            SIGNUP_URL, json=_valid_body(username="sgtest_other", email="SGTEST@TEST.IO")
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "EMAIL_TAKEN"


class TestSignupValidation:
    def test_long_korean_password_400_not_500(self):
        """bcrypt 72바이트 상한 — 한글 30자는 90바이트. 500이 아니라 400이어야 한다."""
        res = client.post(SIGNUP_URL, json=_valid_body(password="가" * 30))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "PASSWORD_TOO_LONG"

    @pytest.mark.parametrize("field,value", [
        ("password", "short"),          # 8자 미만
        ("username", "ab"),             # 3자 미만
        ("username", "한글아이디"),      # 허용 문자 위반
        ("username", "x'; DROP TABLE users; --"),  # 인젝션류 문자 거부
        ("email", "not-an-email"),      # 형식 오류
        ("name", ""),                   # 빈 닉네임
        ("name", "   "),                # 공백만 있는 닉네임 (재검증에서 발견한 버그)
    ])
    def test_invalid_field_422(self, field, value):
        res = client.post(SIGNUP_URL, json=_valid_body(**{field: value}))
        assert res.status_code == 422

    def test_422_follows_spec_error_format(self):
        """검증 실패도 spec §1.1 포맷이어야 FE가 error.code를 파싱할 수 있다 (재검증에서 발견)."""
        res = client.post(SIGNUP_URL, json=_valid_body(password="short"))
        body = res.json()
        assert "error" in body, f"spec 포맷 아님: {body}"
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"]["errors"][0]["field"] == "password"

    def test_no_partial_data_on_validation_failure(self):
        """검증 실패 시 유저가 반쯤 만들어지면 안 된다."""
        client.post(SIGNUP_URL, json=_valid_body(password="short"))
        with SessionLocal() as db:
            count = db.scalar(
                select(func.count()).select_from(User).where(User.username.ilike("sgtest%"))
            )
            assert count == 0


class TestSignupHardening:
    """재검증(2차)에서 확인한 엣지 케이스들 — 회귀 방지용."""

    def test_password_whitespace_preserved(self):
        """비밀번호의 앞뒤 공백은 유효 문자다 — 스트립되면 로그인 때 불일치가 난다."""
        from app.core.security import verify_password

        res = client.post(SIGNUP_URL, json=_valid_body(password="  spaced-pass-123  "))
        assert res.status_code == 201
        with SessionLocal() as db:
            row = db.get(User, res.json()["user"]["id"])
            assert verify_password("  spaced-pass-123  ", row.password_hash) is True
            assert verify_password("spaced-pass-123", row.password_hash) is False

    def test_name_is_stripped_but_kept(self):
        """닉네임 앞뒤 공백은 제거하되 내용은 보존한다."""
        res = client.post(SIGNUP_URL, json=_valid_body(name="  서영  "))
        assert res.status_code == 201
        assert res.json()["user"]["name"] == "서영"

    def test_withdrawn_user_email_can_resignup(self):
        """탈퇴(익명화, D4) 유저의 이메일로 재가입이 가능해야 한다 (db-schema §7.1)."""
        from datetime import datetime, timezone

        res1 = client.post(SIGNUP_URL, json=_valid_body())
        uid = res1.json()["user"]["id"]
        with SessionLocal() as db:  # 탈퇴 시뮬레이션: PII null + deleted_at
            u = db.get(User, uid)
            u.username = None
            u.name = None
            u.email = None
            u.deleted_at = datetime.now(timezone.utc)
            db.commit()

        res2 = client.post(
            SIGNUP_URL, json=_valid_body(username="sgtest_again", email="sgtest@test.io")
        )
        assert res2.status_code == 201

        with SessionLocal() as db:  # 익명화된 원 유저 정리 (fixture는 username 기준이라)
            anon = db.get(User, uid)
            if anon:
                db.delete(anon)
                db.commit()

    def test_legacy_unprefixed_path_is_gone(self):
        """Base URL이 /api/v1로 옮겨졌다 — 옛 경로가 살아있으면 이중 계약이 된다."""
        assert client.post("/auth/signup", json=_valid_body()).status_code == 404

    def test_response_never_leaks_password_fields(self):
        res = client.post(SIGNUP_URL, json=_valid_body())
        keys = set(res.json()["user"].keys())
        assert not any("password" in k or "hash" in k for k in keys)
        assert keys == {"id", "name", "username", "email", "email_verified"}

    def test_two_distinct_users_both_succeed(self):
        """서로 다른 두 유저가 연달아 가입해도 오탐 충돌이 없어야 한다."""
        r1 = client.post(SIGNUP_URL, json=_valid_body())
        r2 = client.post(
            SIGNUP_URL, json=_valid_body(username="sgtest_two", email="sgtest2@test.io")
        )
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["user"]["id"] != r2.json()["user"]["id"]

    def _expire_codes(self, uid: str) -> None:
        """유저의 모든 미소비 인증코드를 과거로 만료시킨다 (인증 창 닫힘 시뮬레이션)."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import update

        with SessionLocal() as db:
            db.execute(
                update(EmailVerification)
                .where(EmailVerification.user_id == uid)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
            db.commit()

    def test_stale_unverified_username_can_be_reclaimed(self):
        """인증 창까지 만료된 미인증 계정의 아이디로 재가입이 가능해야 한다."""
        res1 = client.post(SIGNUP_URL, json=_valid_body())
        uid1 = res1.json()["user"]["id"]
        self._expire_codes(uid1)

        res2 = client.post(SIGNUP_URL, json=_valid_body(email="sgtest2@test.io"))
        assert res2.status_code == 201
        assert res2.json()["user"]["id"] != uid1
        with SessionLocal() as db:  # 옛 stale 행은 회수(삭제)됐어야 한다
            assert db.get(User, uid1) is None

    def test_stale_unverified_email_can_be_reclaimed(self):
        res1 = client.post(SIGNUP_URL, json=_valid_body())
        uid1 = res1.json()["user"]["id"]
        self._expire_codes(uid1)

        res2 = client.post(SIGNUP_URL, json=_valid_body(username="sgtest_new"))
        assert res2.status_code == 201
        with SessionLocal() as db:
            assert db.get(User, uid1) is None

    def test_unverified_but_live_code_is_not_reclaimed(self):
        """코드가 아직 살아있으면(진행 중 가입) 회수하지 않고 409를 준다."""
        client.post(SIGNUP_URL, json=_valid_body())  # 방금 가입 → 코드 유효
        res = client.post(SIGNUP_URL, json=_valid_body(email="sgtest2@test.io"))
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "USERNAME_TAKEN"

    def test_verified_account_is_never_reclaimed(self):
        """인증 완료 계정은 코드가 만료돼도 절대 회수되지 않는다."""
        from tests.conftest import mark_email_verified

        res1 = client.post(SIGNUP_URL, json=_valid_body())
        uid1 = res1.json()["user"]["id"]
        mark_email_verified("sgtest_user")
        self._expire_codes(uid1)

        res2 = client.post(SIGNUP_URL, json=_valid_body(email="sgtest2@test.io"))
        assert res2.status_code == 409
        assert res2.json()["error"]["code"] == "USERNAME_TAKEN"
        with SessionLocal() as db:
            assert db.get(User, uid1) is not None

    def test_verification_code_expiry_is_about_10_minutes(self):
        """인증코드 유효시간이 의도(10분)대로 설정되는지."""
        from datetime import datetime, timezone

        res = client.post(SIGNUP_URL, json=_valid_body())
        uid = res.json()["user"]["id"]
        with SessionLocal() as db:
            ev = db.scalar(select(EmailVerification).where(EmailVerification.user_id == uid))
            remaining = (ev.expires_at - datetime.now(timezone.utc)).total_seconds()
            assert 9 * 60 < remaining <= 10 * 60
