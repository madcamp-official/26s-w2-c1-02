"""팀장 ∈ 멤버 불변식의 동시성·DB 레벨 보장 (Step 1 재검증 보강).

기존 test_teams.py가 승계의 기능적 케이스(tiebreak·세션 보존·솔로 삭제)를 커버하므로,
여기서는 그것들이 커버하지 않는 두 축만 다룬다:
  1) 동시성 — 리더와 멤버가 '동시에' 나가도 불변식이 깨지지 않는가
  2) DB 보장 — 애초에 '팀장 ∉ 멤버' 상태는 커밋 자체가 불가능한가 (DEFERRABLE FK)

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_team_invariant.py -v
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.db.models import Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _signup_login(username: str) -> dict:
    client.post("/api/v1/auth/signup", json={
        "name": username, "username": username,
        "password": "invariant-123", "email": f"{username}@t.io"})
    return client.post("/api/v1/auth/login",
                       json={"username": username, "password": "invariant-123"},
                       headers={"X-Client-Platform": "ios"}).json()


def _uid(username: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _auth(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


def _add_member(team_id: str, user_id: str, joined_offset_sec: int) -> None:
    with SessionLocal() as db:
        db.add(TeamMember(team_id=team_id, user_id=user_id,
                          joined_at=datetime.now(timezone.utc) + timedelta(seconds=joined_offset_sec)))
        db.commit()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as db:
        tids = db.scalars(select(Team.id).join(User, User.id == Team.leader_id)
                          .where(User.username.ilike("tivar%"))).all()
        for t in tids:
            db.delete(db.get(Team, t))
        db.commit()
        db.execute(delete(User).where(User.username.ilike("tivar%")))
        db.commit()


class TestConcurrency:
    def test_leader_and_member_leave_simultaneously_keeps_invariant(self):
        """리더(a)와 멤버(b)가 동시에 나가도: 둘 다 성공하고, 남은 리더는
        반드시 아직 멤버인 사람이어야 한다 (고아 리더/500 없음)."""
        a = _signup_login("tivar_a")
        b = _signup_login("tivar_b")
        _signup_login("tivar_c")
        tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth(a)).json()["id"]
        _add_member(tid, _uid("tivar_b"), 10)
        _add_member(tid, _uid("tivar_c"), 20)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_leader = ex.submit(client.post, f"/api/v1/teams/{tid}/leave", headers=_auth(a))
            f_member = ex.submit(client.post, f"/api/v1/teams/{tid}/leave", headers=_auth(b))
            codes = sorted([f_leader.result().status_code, f_member.result().status_code])

        assert codes == [204, 204], f"동시 나가기 실패: {codes}"
        with SessionLocal() as db:
            leader = db.scalar(select(Team.leader_id).where(Team.id == tid))
            assert leader is not None
            # 핵심 불변식: 남은 리더는 여전히 팀 멤버여야 한다
            assert db.get(TeamMember, (tid, leader)) is not None


class TestDatabaseInvariant:
    """DEFERRABLE FK가 승계 설계의 안전망 — 코드 버그가 있어도 DB가 최종 차단한다."""

    def test_deferrable_allows_out_of_order_insert_within_txn(self):
        """팀 insert(리더 지정) → 멤버 insert 순서가 한 트랜잭션에서 허용돼야 한다.
        (즉시 검사 FK라면 팀 insert 시점에 실패 — 승계 로직 전체가 이 성질에 의존)."""
        _signup_login("tivar_a")
        uid = _uid("tivar_a")
        with SessionLocal() as db:
            db.execute(text("INSERT INTO teams(id,name,leader_id) VALUES('team_tivar_ok','D',:l)"),
                       {"l": uid})
            db.execute(text("INSERT INTO team_members(team_id,user_id) "
                            "VALUES('team_tivar_ok',:u)"), {"u": uid})
            db.commit()  # 커밋 시점엔 리더 ∈ 멤버 → 통과
            assert db.get(Team, "team_tivar_ok") is not None
            db.delete(db.get(Team, "team_tivar_ok"))
            db.commit()

    def test_commit_with_leader_not_member_is_rejected(self):
        """'팀장 ∉ 멤버' 상태는 커밋 자체가 불가능해야 한다 (데이터 오염 원천 차단)."""
        _signup_login("tivar_a")
        uid = _uid("tivar_a")
        with SessionLocal() as db:
            db.execute(text("INSERT INTO teams(id,name,leader_id) VALUES('team_tivar_bad','B',:l)"),
                       {"l": uid})  # 멤버 insert를 일부러 생략
            with pytest.raises(Exception):  # FK 위반으로 커밋 거부
                db.commit()
            db.rollback()
        with SessionLocal() as db:
            assert db.get(Team, "team_tivar_bad") is None  # 남지 않음
