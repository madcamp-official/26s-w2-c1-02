"""권한 가드 Depends 계약 테스트 (작업 4-2).

require_team_member / require_team_leader 를 **임시 앱의 별도 라우트**에 직접
주입해서, 특정 팀 엔드포인트가 아니라 '어디에 붙여도' 같은 계약으로 동작하는지
검증한다. 이게 Step 2("권한 검사 공통화" — 세션 owner 가드)가 재사용할 씨앗이다.

계약:
- require_team_member : 멤버면 Team 주입 / 비멤버·없는 팀 → 404 TEAM_NOT_FOUND
                        (존재를 숨김) / 무인증·위조 → 401
- require_team_leader : 팀장이면 Team 주입 / 멤버지만 팀장 아님 → 403 FORBIDDEN_NOT_LEADER
                        / 비멤버 → 404 (멤버 가드가 먼저라 403이 아니라 404) / 무인증 → 401

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_team_guards.py -v
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import require_team_leader, require_team_member
from app.core.errors import ApiError, api_error_handler
from app.db import models
from app.db.models import Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app

# 팀·유저 준비는 실제 API로 (main 앱)
main_client = TestClient(app)

# ── 가드만 얹은 임시 앱 — 가드의 재사용성 자체를 검증하는 '프로브' ──
guard_app = FastAPI()
guard_app.add_exception_handler(ApiError, api_error_handler)


@guard_app.get("/probe/{team_id}/member")
def _member_probe(team: models.Team = Depends(require_team_member)) -> dict:
    # 가드가 실제 Team 객체를 주입하는지 확인하려고 핵심 필드를 되돌려준다
    return {"team_id": team.id, "leader_id": team.leader_id, "name": team.name}


@guard_app.get("/probe/{team_id}/leader")
def _leader_probe(team: models.Team = Depends(require_team_leader)) -> dict:
    return {"team_id": team.id, "leader_id": team.leader_id}


guard_client = TestClient(guard_app)

PASS = "guard-pass-123"
SIGNUP = "/api/v1/auth/signup"
LOGIN = "/api/v1/auth/login"
TEAMS = "/api/v1/teams"


def _make_user(username: str, name: str) -> str:
    res = main_client.post(SIGNUP, json={
        "name": name, "username": username,
        "password": PASS, "email": f"{username}@test.io",
    })
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


def _auth(username: str) -> dict:
    tok = main_client.post(
        LOGIN, json={"username": username, "password": PASS},
        headers={"X-Client-Platform": "ios"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    """리더/일반멤버/외부인 3인 + 리더가 세운 팀(멤버 2명)."""
    leader = _make_user("guardtest_l", "리더")
    member = _make_user("guardtest_m", "멤버")
    outsider = _make_user("guardtest_o", "외부인")
    tid = main_client.post(TEAMS, json={"name": "가드팀"},
                           headers=_auth("guardtest_l")).json()["id"]
    with SessionLocal() as db:  # 초대 API는 4-5 — 여기선 멤버를 직접 넣는다
        db.add(TeamMember(team_id=tid, user_id=member))
        db.commit()
    yield {"tid": tid, "leader": leader, "member": member, "outsider": outsider}
    with SessionLocal() as db:
        team_ids = db.scalars(select(Team.id).join(
            User, User.id == Team.leader_id).where(User.username.ilike("guardtest%"))).all()
        for t in team_ids:
            db.delete(db.get(Team, t))
        db.commit()
        db.execute(delete(User).where(User.username.ilike("guardtest%")))
        db.commit()


class TestRequireTeamMember:
    def test_member_gets_team_injected(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/member", headers=_auth("guardtest_m"))
        assert res.status_code == 200
        body = res.json()
        assert body["team_id"] == ctx["tid"]
        assert body["leader_id"] == ctx["leader"]   # 진짜 Team 객체가 주입됨
        assert body["name"] == "가드팀"

    def test_leader_is_also_member(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/member", headers=_auth("guardtest_l"))
        assert res.status_code == 200
        assert res.json()["team_id"] == ctx["tid"]

    def test_outsider_gets_404_not_403(self, ctx):
        """비멤버에게는 존재를 숨긴다 — 403이 아니라 404."""
        res = guard_client.get(f"/probe/{ctx['tid']}/member", headers=_auth("guardtest_o"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_nonexistent_team_404(self, ctx):
        res = guard_client.get("/probe/team_nope/member", headers=_auth("guardtest_l"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_no_auth_401(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/member")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"

    def test_forged_token_401(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/member",
                               headers={"Authorization": "Bearer not.a.jwt"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


class TestRequireTeamLeader:
    def test_leader_gets_team_injected(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/leader", headers=_auth("guardtest_l"))
        assert res.status_code == 200
        assert res.json()["team_id"] == ctx["tid"]

    def test_member_but_not_leader_403(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/leader", headers=_auth("guardtest_m"))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN_NOT_LEADER"

    def test_outsider_gets_404_not_403(self, ctx):
        """합성 순서 계약: 비멤버는 멤버 가드가 먼저 걸려 404 (403으로 존재가 새면 안 됨)."""
        res = guard_client.get(f"/probe/{ctx['tid']}/leader", headers=_auth("guardtest_o"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_nonexistent_team_404(self, ctx):
        res = guard_client.get("/probe/team_nope/leader", headers=_auth("guardtest_l"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_no_auth_401(self, ctx):
        res = guard_client.get(f"/probe/{ctx['tid']}/leader")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"
