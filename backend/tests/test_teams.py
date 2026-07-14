"""팀 CRUD 회귀 테스트 (작업 4-1, api-spec §3).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_teams.py -v

두 명의 유저(리더 tmtest_a, 타인 tmtest_b)를 만들어 권한 경계를 검증한다.
테스트 종료 시 tmtest 유저를 지우면 팀은 owner RESTRICT가 아니라
team CASCADE로 함께 사라진다 (팀 먼저 정리).
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.db.enums import QuestionerPersona
from app.db.models import RehearsalSession, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

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
    mark_email_verified(username)  # 로그인 차단(403) 우회
    return res.json()["user"]["id"]


def _token(username: str) -> str:
    return client.post(LOGIN_URL, json={"username": username, "password": "team-pass-123"},
                       headers={"X-Client-Platform": "ios"}).json()["access_token"]


def _auth(username: str) -> dict:
    return {"Authorization": f"Bearer {_token(username)}"}


def _purge_tmtest() -> None:
    """tmtest_* 유저와 그들이 리더인 팀 정리. 팀을 먼저 지워야 users RESTRICT에 안 걸림.
    (팀장이 이미 tmtest면 그 팀도 잡히고, 세션은 팀 CASCADE로 함께 사라진다.)"""
    with SessionLocal() as db:
        team_ids = db.scalars(select(Team.id).join(
            User, User.id == Team.leader_id).where(User.username.ilike("tmtest%"))).all()
        for tid in team_ids:
            db.delete(db.get(Team, tid))
        db.commit()
        db.execute(delete(User).where(User.username.ilike("tmtest%")))
        db.commit()


@pytest.fixture()
def two_users():
    a = _make_user("tmtest_a", "리더A")
    b = _make_user("tmtest_b", "타인B")
    yield {"a": a, "b": b}
    _purge_tmtest()


@pytest.fixture()
def three_users():
    a = _make_user("tmtest_a", "리더A")
    b = _make_user("tmtest_b", "멤버B")
    c = _make_user("tmtest_c", "멤버C")
    yield {"a": a, "b": b, "c": c}
    _purge_tmtest()


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
        a_list = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()["items"]
        names = {t["name"] for t in a_list}
        assert "A의팀" in names and "B의팀" not in names

    def test_card_has_preview_and_count(self, two_users):
        client.post(TEAMS_URL, json={"name": "미리보기팀"}, headers=_auth("tmtest_a"))
        card = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()["items"][0]
        assert set(card.keys()) == {"id", "name", "session_count", "members_preview"}
        assert card["members_preview"] == "리더A"  # 멤버 1명
        assert card["session_count"] == 0

    def test_empty_when_no_teams(self, two_users):
        assert client.get(TEAMS_URL, headers=_auth("tmtest_b")).json() == {"items": []}


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

    def test_delete_removes_storage_files_across_sessions(self, two_users):
        """팀 삭제 → 소속 모든 세션의 파일(자료·녹음·청크·질문TTS·답변오디오)이
        스토리지에서도 정리된다 (db-schema §7.3, 세션 단건 삭제와 동일 규약)."""
        from app.core import storage
        from app.core.ids import new_id
        from app.db import models
        owner = two_users["a"]
        tid = client.post(TEAMS_URL, json={"name": "파일팀"}, headers=_auth("tmtest_a")).json()["id"]
        s1 = _add_session(tid, owner, "발표1")
        s2 = _add_session(tid, owner, "발표2")

        # s1: 자료 + 녹음 + 실시간 청크
        mkey = storage.material_key(s1)
        rkey = storage.recording_key(s1, "m4a")
        ckey = storage.recording_chunk_key(s1, 0)
        # s2: 질문 TTS + 답변 오디오
        qid = new_id("q")
        tts_key = storage.tts_key(s2, qid)
        ans_key = storage.answer_key(s2, qid, "m4a")
        all_keys = [mkey, rkey, ckey, tts_key, ans_key]
        for k in all_keys:
            storage.save(k, b"x")

        with SessionLocal() as db:
            db.add(models.Material(session_id=s1, status="ready", progress=1.0,
                                   file_name="d.pdf", file_size_bytes=1, storage_key=mkey))
            db.add(models.Recording(session_id=s1, status="ready", file_name="r.m4a",
                                    file_size_bytes=1, mime_type="audio/mp4",
                                    duration_seconds=10, storage_key=rkey))
            db.add(models.RecordingChunk(session_id=s1, seq=0, offset_seconds=0.0,
                                         duration_seconds=60.0, storage_key=ckey))
            db.add(models.Question(id=qid, session_id=s2, order_index=1, persona="egen",
                                   strategy="detail_probe", text="?", tts_storage_key=tts_key,
                                   evidence={"slides": [], "transcript_refs": []}))
            db.flush()
            db.add(models.Answer(question_id=qid, kind="answered", status="ready",
                                 audio_storage_key=ans_key, follow_up_status="none"))
            db.commit()
        assert all(storage.exists(k) for k in all_keys)

        assert client.delete(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_a")).status_code == 204
        assert not any(storage.exists(k) for k in all_keys)  # 파일 전부 정리


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


def _add_member_at(team_id: str, user_id: str, joined_at: datetime) -> None:
    """승계 순서(joined_at, user_id) 테스트를 위해 가입 시각을 명시 삽입."""
    with SessionLocal() as db:
        db.add(TeamMember(team_id=team_id, user_id=user_id, joined_at=joined_at))
        db.commit()


def _set_joined_at(team_id: str, user_id: str, when: datetime) -> None:
    """기존 멤버(예: 생성자=팀장)의 가입 시각을 조정 — 팀장이 최고참인 실제 상황 재현."""
    with SessionLocal() as db:
        db.get(TeamMember, (team_id, user_id)).joined_at = when
        db.commit()


class TestSessionCount:
    """발표 수 집계 — db-schema §8.3 서브쿼리 + ARRAY(ENUM) 라운드트립."""

    def test_list_and_detail_reflect_sessions(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "집계팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_session(tid, two_users["a"], "발표1")
        _add_session(tid, two_users["a"], "발표2")

        card = client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()["items"][0]
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
        card = next(c for c in client.get(TEAMS_URL, headers=_auth("tmtest_a")).json()["items"]
                    if c["id"] == tid)
        assert card["members_preview"] == "리더A, 타인B"

    def test_member_sees_shared_team_in_list(self, two_users):
        """멤버로 합류하면 (팀장이 아니어도) 내 목록에 나온다."""
        tid = client.post(TEAMS_URL, json={"name": "공유팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        assert tid in {t["id"] for t in client.get(TEAMS_URL, headers=_auth("tmtest_b")).json()["items"]}


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
        names = [t["name"] for t in client.get(TEAMS_URL, headers=h).json()["items"]]
        assert names.index("나중") < names.index("먼저")  # created_at DESC (§8.3)


class TestAuthRequired:
    """전 엔드포인트 무인증 401 — deps.get_current_user 계약."""

    @pytest.mark.parametrize("method,path,body", [
        ("get", "", None),
        ("post", "", {"name": "팀"}),
        ("get", "/team_x", None),
        ("patch", "/team_x", {"name": "팀"}),
        ("delete", "/team_x", None),
        ("get", "/team_x/members", None),
        ("delete", "/team_x/members/usr_y", None),
    ])
    def test_401_without_token(self, method, path, body):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(f"{TEAMS_URL}{path}", **kwargs)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


# ── 작업 4-3: 멤버 조회·내보내기 ──────────────────────────────────────

class TestListMembers:
    """GET /teams/{id}/members — 멤버 누구나."""

    def test_leader_sees_members_sorted_with_flags(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "멤버조회"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        res = client.get(f"{TEAMS_URL}/{tid}/members", headers=_auth("tmtest_a"))
        assert res.status_code == 200
        members = res.json()
        assert [m["id"] for m in members] == [two_users["a"], two_users["b"]]  # 가입순
        assert [m["is_leader"] for m in members] == [True, False]
        assert set(members[0].keys()) == {"id", "name", "username", "is_leader"}

    def test_non_leader_member_can_view(self, two_users):
        """권한이 '멤버'이므로 팀장이 아니어도 조회된다."""
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        res = client.get(f"{TEAMS_URL}/{tid}/members", headers=_auth("tmtest_b"))
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_matches_detail_members(self, two_users):
        """GET /members 결과가 GET /teams/{id}의 members와 동일해야 한다."""
        tid = client.post(TEAMS_URL, json={"name": "일치확인"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        h = _auth("tmtest_a")
        via_members = client.get(f"{TEAMS_URL}/{tid}/members", headers=h).json()
        via_detail = client.get(f"{TEAMS_URL}/{tid}", headers=h).json()["members"]
        assert via_members == via_detail

    def test_outsider_gets_404(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "비밀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.get(f"{TEAMS_URL}/{tid}/members", headers=_auth("tmtest_b"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_nonexistent_team_404(self, two_users):
        res = client.get(f"{TEAMS_URL}/team_ghost/members", headers=_auth("tmtest_a"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_solo_team_lists_only_leader(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "혼자팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        members = client.get(f"{TEAMS_URL}/{tid}/members", headers=_auth("tmtest_a")).json()
        assert len(members) == 1 and members[0]["is_leader"] is True


class TestRemoveMember:
    """DELETE /teams/{id}/members/{userId} — 팀장 전용."""

    def test_leader_removes_member(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "내보내기"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 204
        with SessionLocal() as db:
            assert db.get(TeamMember, (tid, two_users["b"])) is None
        # 목록에서도 사라짐
        left = client.get(f"{TEAMS_URL}/{tid}/members", headers=_auth("tmtest_a")).json()
        assert [m["id"] for m in left] == [two_users["a"]]

    def test_removed_member_loses_access(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "축출"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}",
                      headers=_auth("tmtest_a"))
        # 쫓겨난 B는 더 이상 팀을 못 봄 (목록에도 없고 상세는 404)
        assert tid not in {t["id"] for t in client.get(TEAMS_URL, headers=_auth("tmtest_b")).json()["items"]}
        assert client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_b")).status_code == 404

    def test_non_leader_member_forbidden(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        # B(비팀장 멤버)가 팀장 A를 내보내려 시도 → 403
        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['a']}",
                            headers=_auth("tmtest_b"))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN_NOT_LEADER"

    def test_outsider_gets_404_not_403(self, two_users):
        """비멤버는 팀장 가드 이전에 멤버 가드가 먼저 걸려 404 (존재 은닉)."""
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        # B는 팀에 넣지 않음 → 완전한 외부인
        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['a']}",
                            headers=_auth("tmtest_b"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_leader_cannot_remove_self(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "자기제거"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['a']}",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "CANNOT_REMOVE_LEADER"
        with SessionLocal() as db:  # 여전히 팀장이자 멤버
            assert db.get(TeamMember, (tid, two_users["a"])) is not None
            assert db.get(Team, tid).leader_id == two_users["a"]

    def test_remove_non_member_404(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        # B는 멤버가 아님 → 내보낼 대상 없음
        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_remove_unknown_user_404(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = client.delete(f"{TEAMS_URL}/{tid}/members/usr_ghost000000000000",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_nonexistent_team_404(self, two_users):
        res = client.delete(f"{TEAMS_URL}/team_ghost/members/{two_users['b']}",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_remove_member_who_owns_sessions(self, two_users):
        """숨은 뒷탈 확인: 세션을 소유한 멤버를 내보내도 sessions.owner_id RESTRICT가
        발동하지 않는다 (유저가 아니라 team_members 행만 삭제하므로). 세션은 보존."""
        tid = client.post(TEAMS_URL, json={"name": "세션보유팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        sid = _add_session(tid, two_users["b"], "B의 발표")  # B가 owner인 세션

        res = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}",
                            headers=_auth("tmtest_a"))
        assert res.status_code == 204  # FK 에러(500) 없이 정상
        with SessionLocal() as db:
            assert db.get(TeamMember, (tid, two_users["b"])) is None      # 멤버십은 사라짐
            assert db.get(RehearsalSession, sid) is not None              # 세션은 남음(이력 보존)
            assert db.get(RehearsalSession, sid).owner_id == two_users["b"]

    def test_double_removal_second_is_404(self, two_users):
        """멱등성 결여 확인: 같은 멤버를 두 번 내보내면 두 번째는 MEMBER_NOT_FOUND."""
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        h = _auth("tmtest_a")
        assert client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}", headers=h).status_code == 204
        r2 = client.delete(f"{TEAMS_URL}/{tid}/members/{two_users['b']}", headers=h)
        assert r2.status_code == 404 and r2.json()["error"]["code"] == "MEMBER_NOT_FOUND"


# ── 작업 4-4: 팀 나가기 + 팀장 자동 승계 (db-schema §7.2) ────────────────

def _leave(team_id: str, username: str):
    return client.post(f"{TEAMS_URL}/{team_id}/leave", headers=_auth(username))


class TestLeaveNonLeader:
    """비팀장이 나가면 멤버십만 삭제되고 팀·팀장은 그대로."""

    def test_member_leaves_membership_only(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "탈퇴팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        assert _leave(tid, "tmtest_b").status_code == 204
        with SessionLocal() as db:
            assert db.get(TeamMember, (tid, two_users["b"])) is None   # 나감
            assert db.get(TeamMember, (tid, two_users["a"])) is not None
            assert db.get(Team, tid).leader_id == two_users["a"]       # 팀장 불변

    def test_left_member_loses_access(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "탈퇴팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        _leave(tid, "tmtest_b")
        assert tid not in {t["id"] for t in client.get(TEAMS_URL, headers=_auth("tmtest_b")).json()["items"]}
        assert client.get(f"{TEAMS_URL}/{tid}", headers=_auth("tmtest_b")).status_code == 404

    def test_outsider_404(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        res = _leave(tid, "tmtest_b")  # B는 멤버가 아님
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"

    def test_requires_auth(self):
        assert client.post(f"{TEAMS_URL}/team_x/leave").status_code == 401

    def test_double_leave_second_404(self, two_users):
        """한 번 나간 뒤 또 나가려 하면 이미 비멤버라 404 (멤버 가드가 차단)."""
        tid = client.post(TEAMS_URL, json={"name": "팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member(tid, two_users["b"])
        assert _leave(tid, "tmtest_b").status_code == 204
        res = _leave(tid, "tmtest_b")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "TEAM_NOT_FOUND"


class TestLeaderSuccession:
    """팀장이 나가면 최고참(joined_at→user_id)이 자동 승계 (D5·§7.2)."""

    def test_transfers_to_earliest_joiner(self, three_users):
        tid = client.post(TEAMS_URL, json={"name": "승계팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        # B가 C보다 먼저 합류 → B가 후임이어야 함
        _add_member_at(tid, three_users["b"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        _add_member_at(tid, three_users["c"], datetime(2026, 2, 1, tzinfo=timezone.utc))

        assert _leave(tid, "tmtest_a").status_code == 204
        with SessionLocal() as db:
            team = db.get(Team, tid)
            assert team is not None
            assert team.leader_id == three_users["b"]                 # B 승계
            assert db.get(TeamMember, (tid, three_users["a"])) is None  # A는 나감
            assert db.get(TeamMember, (tid, team.leader_id)) is not None  # 팀장 ∈ 멤버(FK)

    def test_tiebreak_by_user_id_when_same_joined_at(self, three_users):
        tid = client.post(TEAMS_URL, json={"name": "동률팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        same = datetime(2026, 1, 1, tzinfo=timezone.utc)
        _add_member_at(tid, three_users["b"], same)
        _add_member_at(tid, three_users["c"], same)

        assert _leave(tid, "tmtest_a").status_code == 204
        with SessionLocal() as db:
            # 기대 후임 = DB 콜레이션 기준 user_id 최소. Python min()은 코드포인트 순서라
            # DB(예: Korean_Korea.utf8)와 불일치 → 랜덤 ID에서 간헐 실패했음.
            # 승계 쿼리와 동일한 ORDER BY user_id로 기댓값을 뽑아 콜레이션을 일치시킨다.
            expected = db.execute(
                text("SELECT x FROM (VALUES (:b), (:c)) t(x) ORDER BY x LIMIT 1"),
                {"b": three_users["b"], "c": three_users["c"]},
            ).scalar()
            assert db.get(Team, tid).leader_id == expected

    def test_new_leader_gains_leader_powers(self, three_users):
        """승계 후 새 팀장이 실제로 팀장 권한(이름 변경)을 갖는지."""
        tid = client.post(TEAMS_URL, json={"name": "권한이전"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member_at(tid, three_users["b"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        _leave(tid, "tmtest_a")
        # 이제 B가 팀장 → PATCH 성공해야 함
        res = client.patch(f"{TEAMS_URL}/{tid}", json={"name": "B가바꿈"},
                           headers=_auth("tmtest_b"))
        assert res.status_code == 200 and res.json()["name"] == "B가바꿈"
        assert res.json()["leader_id"] == three_users["b"]

    def test_successor_excludes_self_even_when_leader_is_earliest(self, three_users):
        """실사용 조건: 팀장(=생성자)이 항상 최고참이다. 승계 쿼리의 user_id<>나
        필터가 없으면 팀장이 자기 자신을 후임으로 뽑아 FK가 터진다 —
        팀장을 확실히 제외하고 '비팀장 중 최고참'을 뽑는지 검증."""
        tid = client.post(TEAMS_URL, json={"name": "팀장최고참"},
                          headers=_auth("tmtest_a")).json()["id"]
        # A(팀장)를 전체에서 가장 이른 가입자로 만든다
        _set_joined_at(tid, three_users["a"], datetime(2025, 1, 1, tzinfo=timezone.utc))
        _add_member_at(tid, three_users["b"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        _add_member_at(tid, three_users["c"], datetime(2026, 2, 1, tzinfo=timezone.utc))

        assert _leave(tid, "tmtest_a").status_code == 204
        with SessionLocal() as db:
            # A가 전체 최고참이지만 후임은 비팀장 중 최고참 B (A 자신은 제외)
            assert db.get(Team, tid).leader_id == three_users["b"]

    def test_leader_with_sessions_succession_preserves_sessions(self, three_users):
        """숨은 뒷탈: 세션을 소유한 팀장이 승계로 나가도 owner_id RESTRICT가 안 걸리고
        세션은 보존된다 (멤버십 행만 삭제 + leader_id UPDATE)."""
        tid = client.post(TEAMS_URL, json={"name": "세션보유팀장"},
                          headers=_auth("tmtest_a")).json()["id"]
        _add_member_at(tid, three_users["b"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        sid = _add_session(tid, three_users["a"], "팀장 발표")  # A가 owner인 세션

        assert _leave(tid, "tmtest_a").status_code == 204  # RESTRICT(500) 없이 정상
        with SessionLocal() as db:
            assert db.get(Team, tid).leader_id == three_users["b"]        # 승계됨
            assert db.get(TeamMember, (tid, three_users["a"])) is None    # A 멤버십 삭제
            assert db.get(RehearsalSession, sid) is not None              # 세션 보존
            assert db.get(RehearsalSession, sid).owner_id == three_users["a"]


class TestLastMemberLeave:
    """마지막 1인(팀장 혼자)이 나가면 팀 자체가 삭제되고 하위 리소스 CASCADE."""

    def test_solo_leader_leave_deletes_team(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "혼자팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        assert _leave(tid, "tmtest_a").status_code == 204
        with SessionLocal() as db:
            assert db.get(Team, tid) is None
            assert db.get(TeamMember, (tid, two_users["a"])) is None

    def test_cascades_sessions(self, two_users):
        tid = client.post(TEAMS_URL, json={"name": "세션팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        sid = _add_session(tid, two_users["a"])
        assert _leave(tid, "tmtest_a").status_code == 204
        with SessionLocal() as db:
            assert db.get(Team, tid) is None
            assert db.get(RehearsalSession, sid) is None  # 팀 삭제 → 세션 CASCADE

    def test_leaver_user_survives(self, two_users):
        """팀은 사라져도 나간 유저 계정 자체는 남는다 (팀 나가기 ≠ 회원 탈퇴)."""
        tid = client.post(TEAMS_URL, json={"name": "혼자팀"},
                          headers=_auth("tmtest_a")).json()["id"]
        _leave(tid, "tmtest_a")
        with SessionLocal() as db:
            assert db.get(User, two_users["a"]) is not None
