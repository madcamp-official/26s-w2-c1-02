"""팀 CRUD 회귀 테스트 (작업 4-1, api-spec §3).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_teams.py -v

두 명의 유저(리더 tmtest_a, 타인 tmtest_b)를 만들어 권한 경계를 검증한다.
테스트 종료 시 tmtest 유저를 지우면 팀은 owner RESTRICT가 아니라
team CASCADE로 함께 사라진다 (팀 먼저 정리).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.enums import QuestionerPersona
from app.db.models import RehearsalSession, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
TEAMS_URL = "/api/v1/teams"


def _make_user(username: str, name: str) -> str:
    res = client.post(SIGNUP_URL, json={
        "name": name, "username": username,
        "password": "team-pass-123", "email": f"{username}@test.io",
    })
    assert res.status_code == 201
    return res.json()["user"]["id"]


def _token(username: str) -> str:
    return client.post(LOGIN_URL, json={"username": username, "password": "team-pass-123"},
                       headers={"X-Client-Platform": "ios"}).json()["access_token"]


def _auth(username: str) -> dict:
    return {"Authorization": f"Bearer {_token(username)}"}


@pytest.fixture()
def two_users():
    a = _make_user("tmtest_a", "리더A")
    b = _make_user("tmtest_b", "타인B")
    yield {"a": a, "b": b}
    with SessionLocal() as db:
        # 팀(리더가 tmtest_*)을 먼저 지워야 users RESTRICT에 안 걸림
        team_ids = db.scalars(select(Team.id).join(
            User, User.id == Team.leader_id).where(User.username.ilike("tmtest%"))).all()
        for tid in team_ids:
            db.delete(db.get(Team, tid))
        db.commit()
        db.execute(delete(User).where(User.username.ilike("tmtest%")))
        db.commit()


class TestCreateTeam:
    def test_create_makes_creator_leader_and_member(self, two_users):
        res = client.post(TEAMS_URL, json={"name": "우리팀"}, headers=_auth("tmtest_a"))
        assert res.status_code == 201
        body = res.json()
        assert body["id"].startswith("team_")
        assert body["leader_id"] == two_users["a"]
        assert body["session_count"] == 0
        assert len(body["members"]) == 1
        assert body["members"][0]["id"] == two_users["a"]
        assert body["members"][0]["is_leader"] is True

    def test_create_persists_membership_row(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "우리팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        with SessionLocal() as db:
            assert db.get(TeamMember, (tid, two_users["a"])) is not None

    def test_requires_auth(self):
        assert client.post(TEAMS_URL, json={"name": "무인증"}).status_code == 401

    @pytest.mark.parametrize("bad", ["", "   ", "a" * 21])
    def test_invalid_name_422(self, two_users, bad):
        res = client.post(TEAMS_URL, json={"name": bad}, headers=_auth("tmtest_a"))
        assert res.status_code == 422

    def test_duplicate_name_allowed(self, two_users):
        """팀 이름 중복은 허용 (db-schema: 유니크 없음)."""
        h = _auth("tmtest_a")
        assert client.post(TEAMS_URL, json={"name": "같은이름"}, headers=h).status_code == 201
        assert client.post(TEAMS_URL, json={"name": "같은이름"}, headers=h).status_code == 201


class TestListTeams:
    def test_lists_only_my_teams(self, two_users):
        client.post(TEAMS_URL, json={"name": "A의팀"}, headers=_auth("tmtest_a"))
        client.post(TEAMS_URL, json={"name": "B의팀"}, headers=_auth("tmtest_b"))
        a_list = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()
        names = {t["name"] for t in a_list}
        assert "A의팀" in names and "B의팀" not in names

    def test_card_has_preview_and_count(self, two_users):
        client.post(TEAMS_URL, json={"name": "미리보기팀"}, headers=_auth("tmtest_a"))
        card = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()[0]
        assert set(card.keys()) == {"id", "name", "session_count", "members_preview"}
        assert card["members_preview"] == "리더A"  # 멤버 1명
        assert card["session_count"] == 0

    def test_empty_when_no_teams(self, two_users):
        assert client.get(TEAMS_URL, headers=_auth("tmtest_b")).json() == []


class TestGetTeam:
    def test_member_can_view(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "조회팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a"))
        assert res.status_code == 200
        assert res.json()["id"] == tid

    def test_non_member_gets_404_not_403(self, two_users):
        """비멤버에게는 존재를 숨긴다 (403이 아니라 404)."""
        tid = client.post(TEAMS_URL, json={"name": "비밀팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_b"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_nonexistent_team_404(self, two_users):
        res = client.get(f"{TEAMS_URL}/team_doesnotexist", headers=_auth("tmtest_a"))
        assert res.status_code == 404


class TestUpdateTeam:
    def test_leader_can_rename(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "원래이름"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": "새이름"},
                           headers=_auth("tmtest_a"))
        assert res.status_code == 200
        assert res.json()["name"] == "새이름"

    def test_member_but_not_leader_403(self, two_users):
        """B를 멤버로 넣은 뒤 B가 이름 변경 시도 → 403 FORBIDDEN_NOT_LEADER."""
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        with SessionLocal() as db:  # B를 멤버로 추가 (초대 API는 4-5, 여기선 직접)
            db.add(TeamMember(team_id=tid, user_id=two_users["b"]))
            db.commit()
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": "B가바꿈"},
                           headers=_auth("tmtest_b"))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN_NOT_LEADER"

    def test_non_member_404_not_403(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": "침입"},
                           headers=_auth("tmtest_b"))
        assert res.status_code == 404


class TestDeleteTeam:
    def test_leader_can_delete(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "삭제될팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        assert client.delete(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a")).status_code == 204
        with SessionLocal() as db:
            assert db.get(Team, tid) is None
            assert db.get(TeamMember, (tid, two_users["a"])) is None  # 멤버십 cascade

    def test_member_not_leader_cannot_delete(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        with SessionLocal() as db:
            db.add(TeamMember(team_id=tid, user_id=two_users["b"]))
            db.commit()
        res = client.delete(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_b"))
        assert res.status_code == 403
        with SessionLocal() as db:
            assert db.get(Team, tid) is not None  # 안 지워짐

    def test_non_member_404(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        assert client.delete(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_b")).status_code == 404


def _add_session(team_id: str, owner_id: str, name: str = "리허설") -> str:
    """세션을 DB에 직접 삽입 (세션 API는 Step 2 — 여기선 집계 검증용).

    personas가 ARRAY(ENUM)이라 이 insert 자체가 작업 2-2의 검증 포인트."""
    with SessionLocal() as db:
        ses = RehearsalSession(
            team_id=team_id, owner_id=owner_id, name=name,
            personas=[QuestionerPersona.egen, QuestionerPersona.teto],
            question_count=3, time_limit_minutes=10,
        )
        db.add(ses)
        db.commit()
        return ses.id


def _add_member(team_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        db.add(TeamMember(team_id=team_id, user_id=user_id))
        db.commit()


class TestSessionCount:
    """발표 수 집계 — db-schema §8.3 서브쿼리 + ARRAY(ENUM) 라운드트립."""

    def test_list_and_detail_reflect_sessions(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "집계팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_session(tid, two_users["a"], "발표1")
        _add_session(tid, two_users["a"], "발표2")

        card = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()[0]
        assert card["session_count"] == 2
        detail = client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a")).json()
        assert detail["session_count"] == 2

    def test_personas_enum_array_roundtrip(self, two_users):
        """ARRAY(ENUM) insert가 파이썬 enum 리스트로 되돌아오는지 (작업 2-2 요령)."""
        tid = client.post(TEAMS_URL, json={"name": "배열팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        sid = _add_session(tid, two_users["a"])
        with SessionLocal() as db:
            ses = db.get(RehearsalSession, sid)
            assert ses.personas == [QuestionerPersona.egen, QuestionerPersona.teto]

    def test_delete_team_cascades_sessions(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "삭제팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        sid = _add_session(tid, two_users["a"])
        assert client.delete(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a")).status_code == 204
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid) is None  # sessions CASCADE (db-schema §7.3)


class TestMemberListing:
    """멤버 목록·미리보기 — 가입순 정렬 + is_leader 플래그."""

    def test_detail_members_in_join_order_with_leader_flag(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "정렬팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])  # B가 나중에 합류

        members = client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a")).json()["members"]
        assert [m["id"] for m in members] == [two_users["a"], two_users["b"]]
        assert [m["is_leader"] for m in members] == [True, False]

    def test_preview_joins_names_in_join_order(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "미리보기2"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        card = next(c for c in client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()
                    if c["id"] == tid)
        assert card["members_preview"] == "리더A, 타인B"

    def test_member_sees_shared_team_in_list(self, two_users):
        """멤버로 합류하면 (팀장이 아니어도) 내 목록에 나온다."""
        tid = client.post(TEAMS_URL, json={"name": "공유팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        assert tid in {t["id"] for t in client.get(TEAMS_URL, headers=_auth("tmtest_b")).json()}


class TestNameHandling:
    def test_create_trims_whitespace(self, two_users):
        res = client.post(TEAMS_URL, json={"name": "  공백팀  "}, headers=_auth("tmtest_a"))
        assert res.status_code == 201
        assert res.json()["name"] == "공백팀"

    def test_patch_trims_whitespace(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": "  새이름  "},
                           headers=_auth("tmtest_a"))
        assert res.json()["name"] == "새이름"

    def test_exactly_20_chars_accepted(self, two_users):
        name = "가" * 20  # DDL CHECK도 char_length 기준 20
        res = client.post(TEAMS_URL, json={"name": name}, headers=_auth("tmtest_a"))
        assert res.status_code == 201
        assert res.json()["name"] == name

    @pytest.mark.parametrize("bad", ["", "   ", "a" * 21])
    def test_patch_invalid_name_422(self, two_users, bad):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": bad}, headers=_auth("tmtest_a"))
        assert res.status_code == 422

    def test_patch_missing_name_422(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        assert client.patch(f"{TEAMS_URL}/{tid}", json={},
                            headers=_auth("tmtest_a")).status_code == 422


class TestListOrdering:
    def test_newest_team_first(self, two_users):
        h = _auth("tmtest_a")
        client.post(TEAMS_URL, json={"name": "먼저"}, headers=h)
        client.post(TEAMS_URL, json={"name": "나중"}, headers=h)
        names = [t["name"] for t in client.get(TEAMS_URL, headers=h).json()]
        assert names.index("나중") < names.index("먼저")  # created_at DESC (§8.3)


class TestAuthRequired:
    """전 엔드포인트 무인증 401 — deps.get_current_user 계약."""

    @pytest.mark.parametrize("method,path,body", [
        ("get", "", None),
        ("post", "", {"name": "팀"}),
        ("get", "/team_x", None),
        ("patch", "/team_x", {"name": "팀"}),
        ("delete", "/team_x", None),
    ])
    def test_401_without_token(self, method, path, body):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(f"{TEAMS_URL}{path}", **kwargs)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"
