"""초대 테스트 — 이메일 · 링크 · 토큰 수락/거절 (작업 4-5, api-spec §3.1).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_invites.py -v

유저 규약: invtest_a(팀장) · invtest_b(멤버) · invtest_n/invtest_m(외부 신규 가입자).
teardown은 invtest_* 팀을 먼저 지운 뒤(CASCADE로 초대·멤버십 정리) 유저를 지운다.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.enums import InviteStatus, QuestionerPersona
from app.db.models import (
    RehearsalSession,
    Team,
    TeamEmailInvite,
    TeamInviteLink,
    TeamMember,
    User,
)
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

client = TestClient(app)

SIGNUP = "/api/v1/auth/signup"
LOGIN = "/api/v1/auth/login"
TEAMS = "/api/v1/teams"
TOKENS = "/api/v1/invites"
PASS = "inv-pass-123"


def _make_user(username: str) -> str:
    res = client.post(SIGNUP, json={"name": username, "username": username,
                                    "password": PASS, "email": f"{username}@test.io"})
    assert res.status_code == 201, res.text
    mark_email_verified(username)  # 로그인 차단(403) 우회
    return res.json()["user"]["id"]


def _auth(username: str) -> dict:
    tok = client.post(LOGIN, json={"username": username, "password": PASS},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _add_member(team_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        db.add(TeamMember(team_id=team_id, user_id=user_id))
        db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _insert_email_invite(team_id: str, email: str, *, status=InviteStatus.pending,
                         expires_at=None, token=None) -> str:
    """토큰을 직접 지정해 이메일 초대를 넣는다(만료·상태 케이스용). 토큰 반환."""
    token = token or secrets.token_urlsafe(16)
    with SessionLocal() as db:
        db.add(TeamEmailInvite(
            team_id=team_id, email=email, token=token, status=status,
            expires_at=expires_at or (_now() + timedelta(days=7)),
        ))
        db.commit()
    return token


def _insert_link(team_id: str, *, expires_at=None, revoked_at=None, token=None) -> str:
    token = token or secrets.token_urlsafe(16)
    with SessionLocal() as db:
        db.add(TeamInviteLink(
            team_id=team_id, token=token,
            expires_at=expires_at or (_now() + timedelta(days=7)),
            revoked_at=revoked_at,
        ))
        db.commit()
    return token


def _add_session(team_id: str, owner_id: str) -> str:
    with SessionLocal() as db:
        s = RehearsalSession(team_id=team_id, owner_id=owner_id, name="발표",
                             personas=[QuestionerPersona.egen],
                             question_count=1, time_limit_minutes=5)
        db.add(s)
        db.commit()
        return s.id


def _purge() -> None:
    with SessionLocal() as db:
        team_ids = db.scalars(select(Team.id).join(
            User, User.id == Team.leader_id).where(User.username.ilike("invtest%"))).all()
        for tid in team_ids:
            db.delete(db.get(Team, tid))
        db.commit()
        db.execute(delete(User).where(User.username.ilike("invtest%")))
        db.commit()


@pytest.fixture()
def env():
    a = _make_user("invtest_a")
    b = _make_user("invtest_b")
    n = _make_user("invtest_n")
    m = _make_user("invtest_m")
    tid = client.post(TEAMS, json={"name": "초대팀"}, headers=_auth("invtest_a")).json()["id"]
    _add_member(tid, b)  # B는 비팀장 멤버
    yield {"tid": tid, "a": a, "b": b, "n": n, "m": m}
    _purge()


# ── 이메일 초대 생성 ──────────────────────────────────────────────────

class TestCreateEmailInvite:
    def test_member_creates_invite(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "guest@x.com"}, headers=_auth("invtest_a"))
        assert res.status_code == 201
        body = res.json()
        assert body["id"].startswith("inv_")
        assert body["email"] == "guest@x.com"
        assert body["status"] == "pending"
        assert body["token"] and body["url"].endswith(body["token"])
        assert "expires_at" in body

    def test_non_leader_member_can_invite(self, env):
        """권한이 '멤버'이므로 팀장이 아닌 B도 초대 가능."""
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "g2@x.com"}, headers=_auth("invtest_b"))
        assert res.status_code == 201

    def test_email_lowercased(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "  Mixed@Case.COM "}, headers=_auth("invtest_a"))
        assert res.json()["email"] == "mixed@case.com"

    def test_duplicate_pending_409(self, env):
        h = _auth("invtest_a")
        assert client.post(f"{TEAMS}/{env['tid']}/invites",
                           json={"email": "dup@x.com"}, headers=h).status_code == 201
        r2 = client.post(f"{TEAMS}/{env['tid']}/invites",
                         json={"email": "dup@x.com"}, headers=h)
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "INVITE_ALREADY_PENDING"

    def test_duplicate_case_insensitive_409(self, env):
        h = _auth("invtest_a")
        client.post(f"{TEAMS}/{env['tid']}/invites", json={"email": "Case@x.com"}, headers=h)
        r2 = client.post(f"{TEAMS}/{env['tid']}/invites", json={"email": "case@X.COM"}, headers=h)
        assert r2.status_code == 409

    def test_reinvite_after_cancel_ok(self, env):
        h = _auth("invtest_a")
        inv_id = client.post(f"{TEAMS}/{env['tid']}/invites",
                             json={"email": "re@x.com"}, headers=h).json()["id"]
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}", headers=h).status_code == 204
        # 취소로 pending이 풀려 재초대 가능
        assert client.post(f"{TEAMS}/{env['tid']}/invites",
                           json={"email": "re@x.com"}, headers=h).status_code == 201

    def test_invalid_email_422(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "not-an-email"}, headers=_auth("invtest_a"))
        assert res.status_code == 422

    def test_outsider_404(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "x@x.com"}, headers=_auth("invtest_n"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_requires_auth(self, env):
        assert client.post(f"{TEAMS}/{env['tid']}/invites",
                           json={"email": "x@x.com"}).status_code == 401


class TestListEmailInvites:
    def test_lists_pending_newest_first(self, env):
        h = _auth("invtest_a")
        client.post(f"{TEAMS}/{env['tid']}/invites", json={"email": "first@x.com"}, headers=h)
        client.post(f"{TEAMS}/{env['tid']}/invites", json={"email": "second@x.com"}, headers=h)
        emails = [i["email"] for i in client.get(f"{TEAMS}/{env['tid']}/invites", headers=h).json()]
        assert emails[:2] == ["second@x.com", "first@x.com"]

    def test_excludes_non_pending(self, env):
        h = _auth("invtest_a")
        inv_id = client.post(f"{TEAMS}/{env['tid']}/invites",
                             json={"email": "gone@x.com"}, headers=h).json()["id"]
        client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}", headers=h)  # canceled
        assert client.get(f"{TEAMS}/{env['tid']}/invites", headers=h).json() == []

    def test_outsider_404(self, env):
        assert client.get(f"{TEAMS}/{env['tid']}/invites",
                          headers=_auth("invtest_n")).status_code == 404


class TestCancelEmailInvite:
    def test_cancel_sets_status_and_removes_from_list(self, env):
        h = _auth("invtest_a")
        inv_id = client.post(f"{TEAMS}/{env['tid']}/invites",
                             json={"email": "c@x.com"}, headers=h).json()["id"]
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}", headers=h).status_code == 204
        with SessionLocal() as db:
            assert db.get(TeamEmailInvite, inv_id).status == InviteStatus.canceled

    def test_unknown_invite_404(self, env):
        res = client.delete(f"{TEAMS}/{env['tid']}/invites/inv_ghost",
                            headers=_auth("invtest_a"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "INVITE_NOT_FOUND"

    def test_wrong_team_path_404(self, env):
        """다른 팀의 초대를 이 팀 경로로 취소 시도 → 404 (교차 접근 차단)."""
        other_tid = client.post(TEAMS, json={"name": "다른팀"},
                                headers=_auth("invtest_b")).json()["id"]
        inv_id = client.post(f"{TEAMS}/{other_tid}/invites",
                             json={"email": "o@x.com"}, headers=_auth("invtest_b")).json()["id"]
        res = client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}", headers=_auth("invtest_a"))
        assert res.status_code == 404

    def test_outsider_404(self, env):
        h = _auth("invtest_a")
        inv_id = client.post(f"{TEAMS}/{env['tid']}/invites",
                             json={"email": "c2@x.com"}, headers=h).json()["id"]
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}",
                             headers=_auth("invtest_n")).status_code == 404


# ── 링크 초대 ────────────────────────────────────────────────────────

class TestInviteLink:
    def test_leader_creates_link(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=_auth("invtest_a"))
        assert res.status_code == 201
        body = res.json()
        assert set(body.keys()) == {"token", "url", "expires_at"}
        assert body["url"].endswith(body["token"])

    def test_rotation_revokes_old_keeps_single_active(self, env):
        h = _auth("invtest_a")
        t1 = client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=h).json()["token"]
        t2 = client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=h).json()["token"]
        assert t1 != t2
        with SessionLocal() as db:  # 활성 링크는 항상 1개 (부분 유니크 불변식)
            active = db.scalar(select(func.count()).select_from(TeamInviteLink).where(
                TeamInviteLink.team_id == env["tid"], TeamInviteLink.revoked_at.is_(None)))
            assert active == 1
        # GET은 최신 토큰을 반환, 옛 토큰은 무효
        assert client.get(f"{TEAMS}/{env['tid']}/invites/link", headers=h).json()["token"] == t2
        assert client.get(f"{TOKENS}/{t1}").status_code == 409  # 옛 토큰 revoked → INVITE_INVALID

    def test_get_active_link_null_when_none(self, env):
        assert client.get(f"{TEAMS}/{env['tid']}/invites/link",
                          headers=_auth("invtest_a")).json() is None

    def test_member_can_get_link(self, env):
        client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=_auth("invtest_a"))
        res = client.get(f"{TEAMS}/{env['tid']}/invites/link", headers=_auth("invtest_b"))
        assert res.status_code == 200 and res.json()["token"]

    def test_non_leader_cannot_rotate(self, env):
        res = client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=_auth("invtest_b"))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN_NOT_LEADER"

    def test_revoke_link(self, env):
        h = _auth("invtest_a")
        client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=h)
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/link", headers=h).status_code == 204
        assert client.get(f"{TEAMS}/{env['tid']}/invites/link", headers=h).json() is None

    def test_revoke_when_none_is_idempotent(self, env):
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/link",
                             headers=_auth("invtest_a")).status_code == 204

    def test_non_leader_cannot_revoke(self, env):
        client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=_auth("invtest_a"))
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/link",
                             headers=_auth("invtest_b")).status_code == 403

    def test_outsider_404(self, env):
        assert client.get(f"{TEAMS}/{env['tid']}/invites/link",
                          headers=_auth("invtest_n")).status_code == 404


class TestInviteCodeFormat:
    """초대코드 통일 (plan §11-1, api-spec §3.1): 링크 초대 token = 8자 코드."""

    ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")  # I O 0 1 제외 32자

    def test_token_is_8_chars_from_safe_alphabet(self, env):
        """8자 + 혼동 문자(I O 0 1) 없음 — 구두 전달·수기 입력 가능해야 한다."""
        h = _auth("invtest_a")
        for _ in range(5):  # 무작위라 여러 번 회전해 형식을 확인
            token = client.post(f"{TEAMS}/{env['tid']}/invites/link", headers=h).json()["token"]
            assert len(token) == 8
            assert set(token) <= self.ALPHABET, f"허용 밖 문자: {token}"

    def test_code_full_flow_preview_and_accept(self, env):
        """8자 코드로 기존 토큰 플로우(미리보기 → 수락) 전부 동작 — 계약 무변경 확인."""
        token = client.post(f"{TEAMS}/{env['tid']}/invites/link",
                            headers=_auth("invtest_a")).json()["token"]
        assert client.get(f"{TOKENS}/{token}").status_code == 200          # 미리보기(인증 불필요)
        res = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert res.status_code == 200 and res.json()["team_id"] == env["tid"]

    def test_legacy_long_token_still_valid(self, env):
        """기존 발급분(43자 urlsafe)도 계속 유효 — 검증이 문자열 대조라 길이 무관."""
        long_token = _insert_link(env["tid"])  # token_urlsafe(16) 직삽입
        assert client.get(f"{TOKENS}/{long_token}").status_code == 200

    def test_collision_regenerates(self, env, monkeypatch):
        """UNIQUE 충돌 방어: 이미 존재하는 코드가 뽑히면 버리고 재생성한다.

        랜덤 소스(secrets.choice)를 스크립트해 첫 8글자는 기존 코드와 같게,
        다음 8글자는 새 코드가 나오게 만든다 — 충돌 검사 로직 자체를 통과시켜야
        하므로 _generate_invite_code를 직접 패치하면 안 된다."""
        import app.api.routes.invites as invites_module

        existing = "AAAA2222"
        _insert_link(env["tid"], token=existing)

        chars = iter(existing + "BBBB3333")
        monkeypatch.setattr(invites_module.secrets, "choice", lambda _alpha: next(chars))
        with SessionLocal() as db:
            assert invites_module._generate_invite_code(db) == "BBBB3333"


# ── 토큰 미리보기 (인증 불필요) ────────────────────────────────────────

class TestPreview:
    def test_email_token_preview_no_auth(self, env):
        _add_session(env["tid"], env["a"])
        token = _insert_email_invite(env["tid"], "p@x.com")
        res = client.get(f"{TOKENS}/{token}")  # 인증 헤더 없음
        assert res.status_code == 200
        body = res.json()
        assert body["team_id"] == env["tid"]
        assert body["team_name"] == "초대팀"
        assert body["member_count"] == 2  # A + B
        assert body["session_count"] == 1

    def test_link_token_preview(self, env):
        token = _insert_link(env["tid"])
        res = client.get(f"{TOKENS}/{token}")
        assert res.status_code == 200 and res.json()["team_id"] == env["tid"]

    def test_unknown_token_409(self, env):
        res = client.get(f"{TOKENS}/does-not-exist")
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "INVITE_INVALID"

    def test_expired_email_410(self, env):
        token = _insert_email_invite(env["tid"], "e@x.com",
                                     expires_at=_now() - timedelta(days=1))
        res = client.get(f"{TOKENS}/{token}")
        assert res.status_code == 410
        assert res.json()["error"]["code"] == "INVITE_EXPIRED"

    def test_canceled_email_409(self, env):
        token = _insert_email_invite(env["tid"], "c@x.com", status=InviteStatus.canceled)
        res = client.get(f"{TOKENS}/{token}")
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "INVITE_INVALID"

    def test_revoked_link_409(self, env):
        token = _insert_link(env["tid"], revoked_at=_now())
        assert client.get(f"{TOKENS}/{token}").status_code == 409

    def test_expired_link_410(self, env):
        token = _insert_link(env["tid"], expires_at=_now() - timedelta(days=1))
        assert client.get(f"{TOKENS}/{token}").status_code == 410


# ── 수락 ─────────────────────────────────────────────────────────────

class TestAccept:
    def test_newcomer_accepts_email_invite(self, env):
        token = _insert_email_invite(env["tid"], "invtest_n@test.io")
        res = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert res.status_code == 200 and res.json()["team_id"] == env["tid"]
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is not None  # 합류
            inv = db.scalar(select(TeamEmailInvite).where(TeamEmailInvite.token == token))
            assert inv.status == InviteStatus.accepted and inv.responded_at is not None

    def test_accept_requires_auth(self, env):
        token = _insert_email_invite(env["tid"], "x@x.com")
        assert client.post(f"{TOKENS}/{token}/accept").status_code == 401

    def test_accept_link_token_joins(self, env):
        token = _insert_link(env["tid"])
        res = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert res.status_code == 200
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is not None

    def test_link_is_reusable_by_multiple(self, env):
        token = _insert_link(env["tid"])
        assert client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n")).status_code == 200
        assert client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_m")).status_code == 200
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is not None
            assert db.get(TeamMember, (env["tid"], env["m"])) is not None

    def test_accept_when_already_member_idempotent(self, env):
        """이미 멤버(B)가 링크로 다시 수락 → 200, 중복 삽입 없음."""
        token = _insert_link(env["tid"])
        res = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_b"))
        assert res.status_code == 200
        with SessionLocal() as db:
            cnt = db.scalar(select(func.count()).select_from(TeamMember).where(
                TeamMember.team_id == env["tid"], TeamMember.user_id == env["b"]))
            assert cnt == 1

    def test_accept_expired_410(self, env):
        token = _insert_email_invite(env["tid"], "x@x.com",
                                     expires_at=_now() - timedelta(days=1))
        assert client.post(f"{TOKENS}/{token}/accept",
                           headers=_auth("invtest_n")).status_code == 410

    def test_reaccept_email_409(self, env):
        token = _insert_email_invite(env["tid"], "invtest_n@test.io")
        client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        # 이미 accepted → 재수락 불가
        r2 = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert r2.status_code == 409 and r2.json()["error"]["code"] == "INVITE_INVALID"


# ── 거절 ─────────────────────────────────────────────────────────────

class TestDecline:
    def test_decline_email_sets_status(self, env):
        token = _insert_email_invite(env["tid"], "d@x.com")
        assert client.post(f"{TOKENS}/{token}/decline",
                           headers=_auth("invtest_n")).status_code == 204
        with SessionLocal() as db:
            inv = db.scalar(select(TeamEmailInvite).where(TeamEmailInvite.token == token))
            assert inv.status == InviteStatus.declined
            assert db.get(TeamMember, (env["tid"], env["n"])) is None  # 합류 안 함

    def test_decline_link_is_noop(self, env):
        """링크 초대는 개인별 상태가 없어 거절은 no-op 204 (합류 안 함)."""
        token = _insert_link(env["tid"])
        assert client.post(f"{TOKENS}/{token}/decline",
                           headers=_auth("invtest_n")).status_code == 204
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is None

    def test_decline_requires_auth(self, env):
        token = _insert_email_invite(env["tid"], "x@x.com")
        assert client.post(f"{TOKENS}/{token}/decline").status_code == 401

    def test_decline_unknown_409(self, env):
        assert client.post(f"{TOKENS}/nope/decline",
                           headers=_auth("invtest_n")).status_code == 409

    def test_preview_after_decline_409(self, env):
        token = _insert_email_invite(env["tid"], "d2@x.com")
        client.post(f"{TOKENS}/{token}/decline", headers=_auth("invtest_n"))
        assert client.get(f"{TOKENS}/{token}").status_code == 409

    def test_accept_after_decline_409(self, env):
        """거절한 초대는 더 이상 수락할 수 없다 (status=declined → INVITE_INVALID)."""
        token = _insert_email_invite(env["tid"], "invtest_n@test.io")
        client.post(f"{TOKENS}/{token}/decline", headers=_auth("invtest_n"))
        r = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert r.status_code == 409 and r.json()["error"]["code"] == "INVITE_INVALID"
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is None  # 합류 안 함


# ── 하드닝: 의도적 설계·격리·상태 부수효과 ────────────────────────────

class TestTokenBasedAcceptance:
    def test_accept_ignores_invite_email_mismatch(self, env):
        """H(토큰 기반): 초대 이메일과 로그인 유저 이메일이 달라도 수락된다.
        (초대 링크를 받은 사람이 자기 계정으로 가입/로그인해 합류하는 흐름)"""
        # 초대는 다른 이메일 앞으로 발급, 수락은 invtest_n이
        token = _insert_email_invite(env["tid"], "someone-else@x.com")
        res = client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        assert res.status_code == 200
        with SessionLocal() as db:
            assert db.get(TeamMember, (env["tid"], env["n"])) is not None

    def test_accept_frees_pending_allows_reinvite(self, env):
        """수락으로 status가 pending을 벗어나면 부분 유니크가 풀려 같은 이메일 재초대 가능."""
        token = _insert_email_invite(env["tid"], "reuse@x.com")
        client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        res = client.post(f"{TEAMS}/{env['tid']}/invites",
                          json={"email": "reuse@x.com"}, headers=_auth("invtest_a"))
        assert res.status_code == 201


class TestCancelSideEffects:
    def test_cancel_accepted_invite_is_noop(self, env):
        """이미 수락된 초대를 취소해도 no-op 204 — 멤버십은 그대로 유지."""
        token = _insert_email_invite(env["tid"], "invtest_n@test.io")
        client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        with SessionLocal() as db:
            inv_id = db.scalar(select(TeamEmailInvite.id).where(TeamEmailInvite.token == token))
        assert client.delete(f"{TEAMS}/{env['tid']}/invites/{inv_id}",
                             headers=_auth("invtest_a")).status_code == 204
        with SessionLocal() as db:
            assert db.get(TeamEmailInvite, inv_id).status == InviteStatus.accepted  # 취소 안 됨
            assert db.get(TeamMember, (env["tid"], env["n"])) is not None           # 멤버 유지


class TestPreviewDynamic:
    def test_member_count_reflects_new_join(self, env):
        token = _insert_email_invite(env["tid"], "invtest_n@test.io")
        assert client.get(f"{TOKENS}/{token}").json()["member_count"] == 2  # A+B
        client.post(f"{TOKENS}/{token}/accept", headers=_auth("invtest_n"))
        # 같은 토큰은 이제 accepted라 미리보기 불가 → 새 토큰으로 카운트 재확인
        token2 = _insert_link(env["tid"])
        assert client.get(f"{TOKENS}/{token2}").json()["member_count"] == 3  # +N


class TestCrossTeamIsolation:
    def test_link_isolated_per_team(self, env):
        """B가 만든 다른 팀의 링크 회전이 이 팀 링크에 영향을 주지 않는다."""
        t2 = client.post(TEAMS, json={"name": "B팀"}, headers=_auth("invtest_b")).json()["id"]
        tok_t = client.post(f"{TEAMS}/{env['tid']}/invites/link",
                            headers=_auth("invtest_a")).json()["token"]
        tok_2 = client.post(f"{TEAMS}/{t2}/invites/link",
                            headers=_auth("invtest_b")).json()["token"]
        assert tok_t != tok_2
        # 각 팀 GET은 자기 팀 토큰을 반환
        assert client.get(f"{TEAMS}/{env['tid']}/invites/link",
                          headers=_auth("invtest_a")).json()["token"] == tok_t
        assert client.get(f"{TEAMS}/{t2}/invites/link",
                          headers=_auth("invtest_b")).json()["token"] == tok_2
        # 두 토큰 모두 각자 팀으로 유효
        assert client.get(f"{TOKENS}/{tok_t}").json()["team_id"] == env["tid"]
        assert client.get(f"{TOKENS}/{tok_2}").json()["team_id"] == t2

    def test_email_invite_list_isolated_per_team(self, env):
        t2 = client.post(TEAMS, json={"name": "B팀2"}, headers=_auth("invtest_b")).json()["id"]
        client.post(f"{TEAMS}/{env['tid']}/invites", json={"email": "t1@x.com"},
                    headers=_auth("invtest_a"))
        client.post(f"{TEAMS}/{t2}/invites", json={"email": "t2@x.com"},
                    headers=_auth("invtest_b"))
        t1_emails = {i["email"] for i in
                     client.get(f"{TEAMS}/{env['tid']}/invites", headers=_auth("invtest_a")).json()}
        assert t1_emails == {"t1@x.com"}  # 다른 팀 초대는 안 섞임
