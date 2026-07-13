"""세션 권한 Depends 회귀 테스트 (작업 1, Step 2).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_session_deps.py -v

세션 라우터(작업 2)가 아직 없으므로, deps의 순수 로직을 직접 호출해 검증한다.
등장인물: owner(발표자), leader(팀장·발표자 아님), member(그냥 멤버), outsider(비멤버).
"""

import pytest
from sqlalchemy import delete, select

from app.api.deps import (
    load_session_as_member,
    require_session_owner,
    require_session_owner_or_leader,
)
from app.core.errors import ApiError
from app.db import models
from app.db.enums import QuestionerPersona
from app.db.session import SessionLocal
from app.core.ids import new_id


@pytest.fixture()
def scene():
    """leader가 만든 팀에 owner·member가 속하고, owner가 세션을 가진 상황.
    outsider는 팀 밖. (leader는 팀장이지만 이 세션의 발표자는 아님)"""
    db = SessionLocal()
    ids = {}
    try:
        leader = models.User(id=new_id("usr"), username="sdep_leader", name="팀장", email="sdep_l@t.io")
        owner = models.User(id=new_id("usr"), username="sdep_owner", name="발표자", email="sdep_o@t.io")
        member = models.User(id=new_id("usr"), username="sdep_member", name="멤버", email="sdep_m@t.io")
        outsider = models.User(id=new_id("usr"), username="sdep_out", name="외부", email="sdep_x@t.io")
        db.add_all([leader, owner, member, outsider])
        db.flush()

        team = models.Team(id=new_id("team"), name="세션팀", leader_id=leader.id)
        db.add(team)
        db.flush()
        db.add_all([
            models.TeamMember(team_id=team.id, user_id=leader.id),
            models.TeamMember(team_id=team.id, user_id=owner.id),
            models.TeamMember(team_id=team.id, user_id=member.id),
        ])
        session = models.RehearsalSession(
            id=new_id("ses"), team_id=team.id, owner_id=owner.id, name="발표",
            personas=[QuestionerPersona.egen], question_count=3, time_limit_minutes=10,
        )
        db.add(session)
        db.commit()
        ids = {"leader": leader.id, "owner": owner.id, "member": member.id,
               "outsider": outsider.id, "team": team.id, "session": session.id}
        yield db, ids
    finally:
        db.rollback()
        db.execute(delete(models.Team).where(models.Team.id == ids.get("team", "")))
        db.execute(delete(models.User).where(models.User.username.ilike("sdep_%")))
        db.commit()
        db.close()


def _user(db, uid):
    return db.get(models.User, uid)


class TestLoadSessionAsMember:
    def test_member_loads_session(self, scene):
        db, ids = scene
        for role in ("owner", "member", "leader"):
            s = load_session_as_member(ids["session"], _user(db, ids[role]), db)
            assert s.id == ids["session"]

    def test_outsider_gets_404(self, scene):
        db, ids = scene
        with pytest.raises(ApiError) as e:
            load_session_as_member(ids["session"], _user(db, ids["outsider"]), db)
        assert e.value.status_code == 404 and e.value.code == "SESSION_NOT_FOUND"

    def test_missing_session_404(self, scene):
        db, ids = scene
        with pytest.raises(ApiError) as e:
            load_session_as_member("ses_doesnotexist", _user(db, ids["owner"]), db)
        assert e.value.status_code == 404


class TestRequireSessionOwner:
    def test_owner_passes(self, scene):
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["owner"]), db)
        assert require_session_owner(session, _user(db, ids["owner"])).id == ids["session"]

    def test_leader_who_is_not_owner_403(self, scene):
        """팀장이라도 이 세션의 발표자가 아니면 설정 수정 불가 (403 FORBIDDEN_NOT_OWNER)."""
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["leader"]), db)
        with pytest.raises(ApiError) as e:
            require_session_owner(session, _user(db, ids["leader"]))
        assert e.value.status_code == 403 and e.value.code == "FORBIDDEN_NOT_OWNER"

    def test_plain_member_403(self, scene):
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["member"]), db)
        with pytest.raises(ApiError) as e:
            require_session_owner(session, _user(db, ids["member"]))
        assert e.value.code == "FORBIDDEN_NOT_OWNER"


class TestRequireSessionOwnerOrLeader:
    def test_owner_can_delete(self, scene):
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["owner"]), db)
        assert require_session_owner_or_leader(session, _user(db, ids["owner"]), db).id == ids["session"]

    def test_leader_can_delete_even_if_not_owner(self, scene):
        """삭제는 발표자 외에 팀장도 가능 (api-spec §4.1)."""
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["leader"]), db)
        assert require_session_owner_or_leader(session, _user(db, ids["leader"]), db).id == ids["session"]

    def test_plain_member_cannot_delete_403(self, scene):
        db, ids = scene
        session = load_session_as_member(ids["session"], _user(db, ids["member"]), db)
        with pytest.raises(ApiError) as e:
            require_session_owner_or_leader(session, _user(db, ids["member"]), db)
        assert e.value.status_code == 403 and e.value.code == "FORBIDDEN_NOT_OWNER"


class TestCrossTeamIsolation:
    """재검증(2차) — 권한의 스코프가 '올바른 팀'인지. 가장 흔한 인가 버그 지점."""

    @pytest.fixture()
    def other_team(self):
        """세션 팀과 무관한 별도 팀 B (팀장 obt_leader, 멤버 obt_member)."""
        db = SessionLocal()
        ids = {}
        try:
            bl = models.User(id=new_id("usr"), username="obt_leader", name="B팀장", email="obt_l@t.io")
            bm = models.User(id=new_id("usr"), username="obt_member", name="B멤버", email="obt_m@t.io")
            db.add_all([bl, bm])
            db.flush()
            team = models.Team(id=new_id("team"), name="B팀", leader_id=bl.id)
            db.add(team)
            db.flush()
            db.add_all([
                models.TeamMember(team_id=team.id, user_id=bl.id),
                models.TeamMember(team_id=team.id, user_id=bm.id),
            ])
            db.commit()
            ids = {"leader": bl.id, "member": bm.id, "team": team.id}
            yield db, ids
        finally:
            db.rollback()
            db.execute(delete(models.Team).where(models.Team.id == ids.get("team", "")))
            db.execute(delete(models.User).where(models.User.username.ilike("obt_%")))
            db.commit()
            db.close()

    def test_other_team_member_cannot_view_session_404(self, scene, other_team):
        """다른 팀 멤버가 남의 팀 세션 조회 → 404 (아무 팀 멤버면 통과, 가 아님)."""
        db, ids = scene
        odb, oids = other_team
        with pytest.raises(ApiError) as e:
            load_session_as_member(ids["session"], _user(db, oids["member"]), db)
        assert e.value.status_code == 404 and e.value.code == "SESSION_NOT_FOUND"

    def test_other_team_leader_cannot_view_session_404(self, scene, other_team):
        db, ids = scene
        odb, oids = other_team
        with pytest.raises(ApiError) as e:
            load_session_as_member(ids["session"], _user(db, oids["leader"]), db)
        assert e.value.status_code == 404

    def test_other_team_leader_cannot_delete_403(self, scene, other_team):
        """'팀장이면 삭제 가능'이 아니라 '이 세션 팀의 팀장'이어야 한다.
        다른 팀 팀장에게 세션 객체를 직접 넘겨도 403 (스코프 정확성)."""
        db, ids = scene
        odb, oids = other_team
        session = db.get(models.RehearsalSession, ids["session"])
        with pytest.raises(ApiError) as e:
            require_session_owner_or_leader(session, _user(db, oids["leader"]), db)
        assert e.value.status_code == 403 and e.value.code == "FORBIDDEN_NOT_OWNER"


class TestOwnerLeftTeam:
    def test_owner_who_left_team_loses_session_access(self, scene):
        """발표자가 팀을 떠나면 자기 세션이라도 접근 불가 (세션=팀 스코프). 404."""
        db, ids = scene
        db.delete(db.get(models.TeamMember, (ids["team"], ids["owner"])))
        db.commit()
        with pytest.raises(ApiError) as e:
            load_session_as_member(ids["session"], _user(db, ids["owner"]), db)
        assert e.value.status_code == 404
        # 세션 자체는 여전히 존재하고 owner_id는 유지 (팀 자산으로 보존)
        assert db.get(models.RehearsalSession, ids["session"]).owner_id == ids["owner"]
