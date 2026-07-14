"""세션 CRUD 회귀 테스트 (작업 2-2, api-spec §4.1).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_sessions.py -v

등장인물(전부 sesr_ 접두사): owner(발표자), leader(팀장), member(그냥 멤버), outsider(비멤버).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.models import RehearsalSession, Team, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)

SIGNUP = "/api/v1/auth/signup"
LOGIN = "/api/v1/auth/login"


def _mkuser(u: str) -> str:
    r = client.post(SIGNUP, json={"name": u, "username": u,
                                  "password": "sess-pass-123", "email": f"{u}@t.io"})
    assert r.status_code == 201
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post(LOGIN, json={"username": u, "password": "sess-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _body(**over):
    b = {"name": "1차 발표", "personas": ["egen", "teto"],
         "question_count": 5, "time_limit_minutes": 10, "mode": "realtime"}
    b.update(over)
    return b


@pytest.fixture()
def team_ctx():
    """leader가 팀장인 팀에 owner·member 합류. outsider는 팀 밖. → team_id 반환."""
    ids = {r: _mkuser(f"sesr_{r}") for r in ("leader", "owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "세션팀"},
                      headers=_auth("sesr_leader")).json()["id"]
    from app.db.models import TeamMember
    with SessionLocal() as db:
        db.add_all([TeamMember(team_id=tid, user_id=ids["owner"]),
                    TeamMember(team_id=tid, user_id=ids["member"])])
        db.commit()
    yield tid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("sesr_%")))
        db.commit()


def _create(tid) -> str:
    r = client.post(f"/api/v1/teams/{tid}/sessions", json=_body(), headers=_auth("sesr_owner"))
    assert r.status_code == 201
    return r.json()["id"]


class TestCreate:
    def test_create_sets_owner_and_draft(self, team_ctx):
        tid, ids = team_ctx
        r = client.post(f"/api/v1/teams/{tid}/sessions", json=_body(),
                        headers=_auth("sesr_owner"))
        assert r.status_code == 201
        b = r.json()
        assert b["id"].startswith("ses_")
        assert b["owner_id"] == ids["owner"]
        assert b["team_id"] == tid
        assert b["status"] == "draft"
        assert b["personas"] == ["egen", "teto"]
        assert b["material"] is None and b["recording"] is None and b["report"] is None

    def test_member_can_create(self, team_ctx):
        tid, _ = team_ctx
        assert client.post(f"/api/v1/teams/{tid}/sessions", json=_body(),
                           headers=_auth("sesr_member")).status_code == 201

    def test_outsider_cannot_create_404(self, team_ctx):
        tid, _ = team_ctx
        assert client.post(f"/api/v1/teams/{tid}/sessions", json=_body(),
                           headers=_auth("sesr_outsider")).status_code == 404

    def test_requires_auth(self, team_ctx):
        tid, _ = team_ctx
        assert client.post(f"/api/v1/teams/{tid}/sessions", json=_body()).status_code == 401

    def test_invalid_body_422(self, team_ctx):
        tid, _ = team_ctx
        assert client.post(f"/api/v1/teams/{tid}/sessions", json=_body(question_count=99),
                           headers=_auth("sesr_owner")).status_code == 422


class TestList:
    def test_lists_team_sessions_newest_first(self, team_ctx):
        tid, _ = team_ctx
        client.post(f"/api/v1/teams/{tid}/sessions", json=_body(name="A"), headers=_auth("sesr_owner"))
        client.post(f"/api/v1/teams/{tid}/sessions", json=_body(name="B"), headers=_auth("sesr_owner"))
        rows = client.get(f"/api/v1/teams/{tid}/sessions", headers=_auth("sesr_member")).json()["items"]
        assert [r["name"] for r in rows] == ["B", "A"]  # created_at DESC
        # 항목 = 상세와 동일 형태 (FE Session.fromJson이 team_id·owner_id·personas 요구)
        assert set(rows[0]) == {"id", "team_id", "owner_id", "name", "status", "personas",
                                "question_count", "time_limit_minutes", "mode",
                                "material", "recording", "transcript", "report", "created_at"}
        assert len(rows[0]["personas"]) == 2

    def test_outsider_list_404(self, team_ctx):
        tid, _ = team_ctx
        assert client.get(f"/api/v1/teams/{tid}/sessions",
                          headers=_auth("sesr_outsider")).status_code == 404


class TestGetDetail:
    def test_member_can_view(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.get(f"/api/v1/sessions/{sid}", headers=_auth("sesr_member"))
        assert r.status_code == 200 and r.json()["id"] == sid

    def test_outsider_404(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        assert client.get(f"/api/v1/sessions/{sid}",
                          headers=_auth("sesr_outsider")).status_code == 404


class TestUpdate:
    def test_owner_updates_draft(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.patch(f"/api/v1/sessions/{sid}",
                         json={"name": "수정됨", "question_count": 8},
                         headers=_auth("sesr_owner"))
        assert r.status_code == 200
        assert r.json()["name"] == "수정됨" and r.json()["question_count"] == 8

    def test_partial_update_keeps_others(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        client.patch(f"/api/v1/sessions/{sid}", json={"name": "새"}, headers=_auth("sesr_owner"))
        b = client.get(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner")).json()
        assert b["name"] == "새" and b["question_count"] == 5  # 안 건드린 값 유지

    def test_non_owner_member_403(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.patch(f"/api/v1/sessions/{sid}", json={"name": "X"},
                         headers=_auth("sesr_member"))
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_NOT_OWNER"

    def test_leader_not_owner_403(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        assert client.patch(f"/api/v1/sessions/{sid}", json={"name": "X"},
                            headers=_auth("sesr_leader")).status_code == 403

    def test_non_draft_409(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        with SessionLocal() as db:  # 상태를 transcribing으로 강제
            db.get(RehearsalSession, sid).status = "transcribing"
            db.commit()
        r = client.patch(f"/api/v1/sessions/{sid}", json={"name": "X"},
                         headers=_auth("sesr_owner"))
        assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_NOT_DRAFT"


class TestDelete:
    def test_owner_deletes(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        assert client.delete(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner")).status_code == 204
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid) is None

    def test_leader_can_delete_others_session(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        assert client.delete(f"/api/v1/sessions/{sid}",
                             headers=_auth("sesr_leader")).status_code == 204

    def test_plain_member_cannot_delete_403(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.delete(f"/api/v1/sessions/{sid}", headers=_auth("sesr_member"))
        assert r.status_code == 403
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid) is not None  # 안 지워짐

    def test_delete_removes_storage_files(self, team_ctx):
        """세션에 자료 파일이 있으면 삭제 시 스토리지에서도 사라진다 (db-schema §7.3)."""
        from app.core import storage
        from app.db.models import Material
        tid, _ = team_ctx
        sid = _create(tid)
        key = storage.material_key(sid)
        storage.save(key, b"%PDF fake")
        with SessionLocal() as db:  # material 행 추가 (업로드 API는 2-3)
            db.add(Material(session_id=sid, status="ready", progress=1.0, file_name="d.pdf",
                            file_size_bytes=9, storage_key=key, slides=[{"page": 1, "text": "x"}]))
            db.commit()
        assert storage.exists(key) is True
        client.delete(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner"))
        assert storage.exists(key) is False  # 파일도 정리됨

    def test_delete_removes_all_file_types(self, team_ctx):
        """삭제 시 자료·녹음·질문TTS·답변오디오 4종 파일이 전부 정리된다 (join 경로)."""
        from app.core import storage
        from app.core.ids import new_id
        from app.db import models
        tid, _ = team_ctx
        sid = _create(tid)
        mkey = storage.material_key(sid)
        rkey = storage.recording_key(sid, "m4a")
        qid = new_id("q")
        tts_key = storage.tts_key(sid, qid)
        ans_key = storage.answer_key(sid, qid, "m4a")
        for k in (mkey, rkey, tts_key, ans_key):
            storage.save(k, b"x")
        with SessionLocal() as db:
            db.add(models.Material(session_id=sid, status="ready", progress=1.0,
                                   file_name="d.pdf", file_size_bytes=1, storage_key=mkey))
            db.add(models.Recording(session_id=sid, status="ready", file_name="r.m4a",
                                    file_size_bytes=1, mime_type="audio/mp4",
                                    duration_seconds=10, storage_key=rkey))
            db.add(models.Question(id=qid, session_id=sid, order_index=1, persona="egen",
                                   strategy="detail_probe", text="?", tts_storage_key=tts_key,
                                   evidence={"slides": [], "transcript_refs": []}))
            db.flush()
            db.add(models.Answer(question_id=qid, kind="answered", status="ready",
                                 audio_storage_key=ans_key, follow_up_status="none"))
            db.commit()
        client.delete(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner"))
        assert not any(storage.exists(k) for k in (mkey, rkey, tts_key, ans_key))


class TestLifecycle:
    """작업 2 통합 — 생성→목록→상세→수정→삭제가 한 흐름으로 이어진다 (capstone)."""

    def test_full_session_lifecycle(self, team_ctx):
        tid, ids = team_ctx
        H = _auth("sesr_owner")

        # 1) 생성
        created = client.post(f"/api/v1/teams/{tid}/sessions",
                              json=_body(name="발표", question_count=5), headers=H)
        assert created.status_code == 201
        sid = created.json()["id"]
        assert created.json()["status"] == "draft"

        # 2) 목록에 등장
        listed = client.get(f"/api/v1/teams/{tid}/sessions", headers=H).json()["items"]
        assert any(s["id"] == sid for s in listed)

        # 3) 상세 조회
        assert client.get(f"/api/v1/sessions/{sid}", headers=H).json()["name"] == "발표"

        # 4) draft에서 수정 → 반영 확인
        client.patch(f"/api/v1/sessions/{sid}",
                     json={"name": "발표(수정)", "question_count": 8}, headers=H)
        after = client.get(f"/api/v1/sessions/{sid}", headers=H).json()
        assert after["name"] == "발표(수정)" and after["question_count"] == 8

        # 5) 삭제 → 이후 조회 404, 목록에서도 사라짐
        assert client.delete(f"/api/v1/sessions/{sid}", headers=H).status_code == 204
        assert client.get(f"/api/v1/sessions/{sid}", headers=H).status_code == 404
        listed2 = client.get(f"/api/v1/teams/{tid}/sessions", headers=H).json()["items"]
        assert all(s["id"] != sid for s in listed2)


class TestDetailDerivation:
    """재검증(2차) — 하위 리소스 파생(slide_count·audio_url) 정확성."""

    def _populate(self, sid):
        from app.core import storage
        from app.db import models
        mkey = storage.material_key(sid)
        rkey = storage.recording_key(sid, "m4a")
        storage.save(mkey, b"%PDF x")
        storage.save(rkey, b"audio")
        with SessionLocal() as db:
            db.add(models.Material(session_id=sid, status="ready", progress=1.0,
                                   file_name="d.pdf", file_size_bytes=6, page_count=10,
                                   storage_key=mkey, slides=[{"page": i, "text": "t"} for i in range(1, 11)]))
            db.add(models.Recording(session_id=sid, status="ready", file_name="r.m4a",
                                    file_size_bytes=5, mime_type="audio/mp4",
                                    duration_seconds=663, storage_key=rkey))
            db.add(models.Transcript(session_id=sid, status="ready",
                                     segments=[{"start": 0, "end": 1, "text": "안녕"}]))
            db.commit()

    def test_detail_derives_subresources(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        self._populate(sid)
        d = client.get(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner")).json()
        assert d["material"]["slide_count"] == 10
        assert d["material"]["status"] == "ready"
        assert d["recording"]["duration_seconds"] == 663
        assert d["transcript"]["status"] == "ready"

    def test_audio_url_is_downloadable(self, team_ctx):
        """파생된 audio_url이 실제로 /files에서 200으로 내려받아진다."""
        tid, _ = team_ctx
        sid = _create(tid)
        self._populate(sid)
        d = client.get(f"/api/v1/sessions/{sid}", headers=_auth("sesr_owner")).json()
        assert client.get(d["recording"]["audio_url"]).status_code == 200


class TestUpdateHardening:
    """재검증(2차) — PATCH로 서버 통제 필드를 주입할 수 없어야 한다."""

    def test_cannot_inject_status(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.patch(f"/api/v1/sessions/{sid}", json={"status": "completed"},
                         headers=_auth("sesr_owner"))
        assert r.status_code == 422  # extra=forbid

    def test_cannot_inject_owner_or_team(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        assert client.patch(f"/api/v1/sessions/{sid}", json={"owner_id": "usr_hacker"},
                            headers=_auth("sesr_owner")).status_code == 422

    def test_patch_personas_replaces_and_dedupes(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.patch(f"/api/v1/sessions/{sid}",
                         json={"personas": ["kkondae", "jammin", "kkondae"]},
                         headers=_auth("sesr_owner"))
        assert r.json()["personas"] == ["kkondae", "jammin"]

    def test_empty_patch_is_noop_200(self, team_ctx):
        tid, _ = team_ctx
        sid = _create(tid)
        r = client.patch(f"/api/v1/sessions/{sid}", json={}, headers=_auth("sesr_owner"))
        assert r.status_code == 200 and r.json()["name"] == "1차 발표"
