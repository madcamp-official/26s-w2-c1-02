"""자료 조회·재시도·삭제 회귀 테스트 (작업 3-3).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_materials_crud.py -v
"""

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import storage
from app.db.models import Material, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified

client = TestClient(app)


def _pdf(page_texts: list[str]) -> bytes:
    doc = fitz.open()
    for t in page_texts:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t)
    data = doc.tobytes()
    doc.close()
    return data


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "mcru-pass-123", "email": f"{u}@t.io"})
    mark_email_verified(u)  # 로그인 차단(403) 우회 — email-verification-plan 작업 6
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "mcru-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    ids = {r: _mkuser(f"mcru_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("mcru_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 3,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("mcru_owner")).json()["id"]
    yield sid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("mcru_%")))
        db.commit()
    storage.delete(storage.material_key(sid))


def _upload(sid, data, who="mcru_owner"):
    return client.post(f"/api/v1/sessions/{sid}/material",
                       files={"file": ("d.pdf", data, "application/pdf")}, headers=_auth(who))


MAT = "/api/v1/sessions/{}/material"


class TestGetMaterial:
    def test_ready_material_returns_slides(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["Cover text", "Body text"]))
        r = client.get(MAT.format(sid), headers=_auth("mcru_owner"))
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "ready"
        assert b["page_count"] == 2
        assert b["progress"] == 1.0
        assert b["slides"][0]["page"] == 1 and "Cover" in b["slides"][0]["text"]
        assert b["error"] is None

    def test_failed_material_returns_error(self, ctx):
        sid, _ = ctx
        _upload(sid, b"not a pdf")
        b = client.get(MAT.format(sid), headers=_auth("mcru_owner")).json()
        assert b["status"] == "failed"
        assert b["error"]["code"] == "PDF_PARSE_ERROR"
        assert b["slides"] is None

    def test_member_can_view(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        assert client.get(MAT.format(sid), headers=_auth("mcru_member")).status_code == 200

    def test_outsider_404(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        assert client.get(MAT.format(sid), headers=_auth("mcru_outsider")).status_code == 404

    def test_no_material_404(self, ctx):
        sid, _ = ctx
        r = client.get(MAT.format(sid), headers=_auth("mcru_owner"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "MATERIAL_NOT_FOUND"


class TestRetryMaterial:
    def test_retry_failed_reparses_to_ready(self, ctx):
        """손상본으로 failed → (파일을 정상 PDF로 바꾼 뒤) retry → ready.

        retry는 storage의 파일을 다시 읽으므로, 파일을 정상본으로 교체해두면 복구된다."""
        sid, _ = ctx
        _upload(sid, b"broken")
        with SessionLocal() as db:
            assert db.get(Material, sid).status == "failed"
        # storage의 파일을 정상 PDF로 교체 (retry가 이 파일을 다시 읽음)
        storage.save(storage.material_key(sid), _pdf(["recovered by retry"]))
        r = client.post(MAT.format(sid) + "/retry", headers=_auth("mcru_owner"))
        assert r.status_code == 202
        with SessionLocal() as db:
            assert db.get(Material, sid).status == "ready"

    def test_retry_ready_material_409(self, ctx):
        """정상(ready) 자료 재시도는 막는다 (중복 잡 방지)."""
        sid, _ = ctx
        _upload(sid, _pdf(["ok"]))
        r = client.post(MAT.format(sid) + "/retry", headers=_auth("mcru_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "MATERIAL_NOT_RETRYABLE"

    def test_retry_no_material_404(self, ctx):
        sid, _ = ctx
        assert client.post(MAT.format(sid) + "/retry",
                           headers=_auth("mcru_owner")).status_code == 404

    def test_member_cannot_retry_403(self, ctx):
        sid, _ = ctx
        _upload(sid, b"broken")
        assert client.post(MAT.format(sid) + "/retry",
                           headers=_auth("mcru_member")).status_code == 403


class TestDeleteMaterial:
    def test_owner_deletes_row_and_file(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        assert storage.exists(storage.material_key(sid))
        r = client.delete(MAT.format(sid), headers=_auth("mcru_owner"))
        assert r.status_code == 204
        with SessionLocal() as db:
            assert db.get(Material, sid) is None
        assert not storage.exists(storage.material_key(sid))

    def test_delete_allows_reupload_after(self, ctx):
        """삭제 후 다시 업로드 가능 (자료 없이 진행하다 다시 올리는 흐름)."""
        sid, _ = ctx
        _upload(sid, _pdf(["first"]))
        client.delete(MAT.format(sid), headers=_auth("mcru_owner"))
        assert _upload(sid, _pdf(["again"])).status_code == 202

    def test_member_cannot_delete_403(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        assert client.delete(MAT.format(sid), headers=_auth("mcru_member")).status_code == 403

    def test_delete_no_material_404(self, ctx):
        sid, _ = ctx
        assert client.delete(MAT.format(sid), headers=_auth("mcru_owner")).status_code == 404


class TestMaterialHardening:
    """재검증(2차) — retry 진위·동시성·delete 상호작용·라이프사이클."""

    def test_retry_genuinely_reparses_same_bad_file_stays_failed(self, ctx):
        """retry가 상태만 뒤집는 게 아니라 실제 재파싱하는지 —
        같은 손상 파일로 retry하면 다시 failed여야 한다."""
        sid, _ = ctx
        _upload(sid, b"still broken")
        r = client.post(MAT.format(sid) + "/retry", headers=_auth("mcru_owner"))
        assert r.status_code == 202
        with SessionLocal() as db:
            assert db.get(Material, sid).status == "failed"  # 재파싱 후에도 실패

    def test_concurrent_double_retry_no_500(self, ctx):
        from concurrent.futures import ThreadPoolExecutor
        sid, _ = ctx
        _upload(sid, b"broken")
        with ThreadPoolExecutor(max_workers=2) as ex:
            codes = sorted(f.result().status_code for f in
                           [ex.submit(client.post, MAT.format(sid) + "/retry",
                                      headers=_auth("mcru_owner")) for _ in range(2)])
        assert 500 not in codes  # 202/202 또는 202/409, 어떤 경우든 500 없음

    def test_retry_after_delete_404(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        client.delete(MAT.format(sid), headers=_auth("mcru_owner"))
        assert client.post(MAT.format(sid) + "/retry",
                           headers=_auth("mcru_owner")).status_code == 404

    def test_get_after_delete_404(self, ctx):
        sid, _ = ctx
        _upload(sid, _pdf(["x"]))
        client.delete(MAT.format(sid), headers=_auth("mcru_owner"))
        assert client.get(MAT.format(sid), headers=_auth("mcru_owner")).status_code == 404

    def test_full_material_lifecycle(self, ctx):
        """upload → GET(ready) → delete → GET(404) → reupload → GET(ready)."""
        sid, _ = ctx
        _upload(sid, _pdf(["life"]))
        assert client.get(MAT.format(sid), headers=_auth("mcru_owner")).json()["status"] == "ready"
        client.delete(MAT.format(sid), headers=_auth("mcru_owner"))
        assert client.get(MAT.format(sid), headers=_auth("mcru_owner")).status_code == 404
        _upload(sid, _pdf(["again"]))
        assert client.get(MAT.format(sid), headers=_auth("mcru_owner")).json()["status"] == "ready"
