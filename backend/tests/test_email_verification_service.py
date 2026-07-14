"""인증코드 발급 헬퍼 검증 (email-verification-plan 작업 4). 실 DB 사용.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_email_verification_service.py -v

여기서 고정하는 계약 — 라우트(작업 5)가 전제하는 것들:
- 평문 코드는 반환값으로만 나가고 DB엔 bcrypt 해시만 남는다
- 발급하면 그 유저의 이전 유효 코드는 전부 소비된다 (유효 코드 ≤ 1개 불변식)
- 커밋까지 끝난 상태로 반환된다 (BackgroundTasks 발송 전에 이미 영속)
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.core.security import verify_password
from app.db.models import EmailVerification, User
from app.db.session import SessionLocal
from app.services import email_verification as svc
from app.services.email_verification import issue_verification_code


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def user(db):
    """헬퍼 검증용 유저. 끝나면 삭제 — email_verifications는 FK CASCADE."""
    u = User(username="emvsvc_user", name="발급검증", email="emvsvc_user@test.io")
    db.add(u)
    db.commit()
    yield u
    with SessionLocal() as cleanup:
        cleanup.execute(delete(User).where(User.username.ilike("emvsvc_%")))
        cleanup.commit()


def _valid_rows(db, user_id: str) -> list[EmailVerification]:
    return db.scalars(
        select(EmailVerification)
        .where(EmailVerification.user_id == user_id,
               EmailVerification.consumed_at.is_(None))
    ).all()


class TestConstants:
    def test_values_match_plan(self):
        """plan §4-2 확정값 — 바꾸면 api-spec(§0.9 TTL 10분·5회)과 함께 바꿔야 한다."""
        assert svc.CODE_TTL.total_seconds() == 600
        assert svc.MAX_ATTEMPTS == 5
        assert svc.RESEND_COOLDOWN.total_seconds() == 60


class TestIssue:
    def test_returns_6_ascii_digits(self, db, user):
        code = issue_verification_code(db, user)
        assert len(code) == 6 and code.isascii() and code.isdigit()

    def test_db_has_bcrypt_hash_not_plaintext(self, db, user):
        code = issue_verification_code(db, user)
        [row] = _valid_rows(db, user.id)
        assert row.code_hash != code                # 평문 저장 금지
        assert row.code_hash.startswith("$2")       # bcrypt 포맷
        assert verify_password(code, row.code_hash)
        wrong = "000000" if code != "000000" else "999999"
        assert not verify_password(wrong, row.code_hash)

    def test_row_defaults_and_ttl(self, db, user):
        before = datetime.now(timezone.utc)
        issue_verification_code(db, user)
        [row] = _valid_rows(db, user.id)
        assert row.consumed_at is None
        assert row.attempt_count == 0               # 서버 기본값 (시도 제한 시작점)
        ttl = (row.expires_at - before).total_seconds()
        assert 590 < ttl < 620                      # now + CODE_TTL(10분)

    def test_committed_before_return(self, db, user):
        """반환 시점에 이미 커밋돼 있어야 한다 — 라우트는 이 뒤에 BackgroundTasks로
        발송만 하고 끝나므로, 여기서 커밋이 안 됐으면 코드가 유실된다."""
        issue_verification_code(db, user)
        with SessionLocal() as fresh:               # 다른 세션에서 보이는지
            assert len(_valid_rows(fresh, user.id)) == 1

    def test_uses_csprng_and_zero_pads(self, db, user, monkeypatch):
        """secrets.randbelow(CSPRNG) 사용 + 6자리 제로패딩 — randbelow가 42를 주면
        코드는 '000042'여야 한다 (mock_stt식 monkeypatch 캡처 패턴)."""
        calls = {}

        def fake_randbelow(n):
            calls["n"] = n
            return 42

        monkeypatch.setattr(svc.secrets, "randbelow", fake_randbelow)
        code = issue_verification_code(db, user)
        assert calls["n"] == 1_000_000              # 000000~999999 전 범위
        assert code == "000042"
        [row] = _valid_rows(db, user.id)
        assert verify_password("000042", row.code_hash)


class TestReissue:
    def test_old_codes_all_consumed(self, db, user):
        """유효 코드 ≤ 1개 불변식: 몇 번을 재발급해도 유효 행은 마지막 1개뿐."""
        code1 = issue_verification_code(db, user)
        code2 = issue_verification_code(db, user)
        code3 = issue_verification_code(db, user)
        rows = db.scalars(select(EmailVerification)
                          .where(EmailVerification.user_id == user.id)).all()
        assert len(rows) == 3
        [valid] = _valid_rows(db, user.id)
        assert verify_password(code3, valid.code_hash)
        # 옛 코드(code1·code2)는 유일한 유효 해시와 불일치 → 재발송 후 옛 코드 구멍 없음
        assert not verify_password(code1, valid.code_hash) or code1 == code3
        assert not verify_password(code2, valid.code_hash) or code2 == code3

    def test_consumed_at_set_on_old_rows(self, db, user):
        issue_verification_code(db, user)
        issue_verification_code(db, user)
        rows = db.scalars(select(EmailVerification)
                          .where(EmailVerification.user_id == user.id)
                          .order_by(EmailVerification.created_at)).all()
        assert rows[0].consumed_at is not None
        assert rows[-1].consumed_at is None

    def test_other_users_codes_untouched(self, db, user):
        """무효화는 해당 유저로 한정 — 남의 재발급이 내 코드를 죽이면 안 된다."""
        other = User(username="emvsvc_other", name="격리", email="emvsvc_other@test.io")
        db.add(other)
        db.commit()
        my_code = issue_verification_code(db, other)
        issue_verification_code(db, user)           # 다른 유저의 발급
        [mine] = _valid_rows(db, other.id)
        assert verify_password(my_code, mine.code_hash)


class TestCleanupContract:
    def test_user_delete_cascades_verifications(self, db, user):
        """유저 하드삭제 시 인증 행도 함께 삭제(FK CASCADE) — 테스트 teardown들이
        유저만 지워도 고아 행이 안 남는 근거."""
        issue_verification_code(db, user)
        db.execute(delete(User).where(User.id == user.id))
        db.commit()
        assert db.scalars(select(EmailVerification)
                          .where(EmailVerification.user_id == user.id)).all() == []
