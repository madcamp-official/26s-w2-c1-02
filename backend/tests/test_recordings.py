"""녹음 업로드 + STT 잡 회귀 테스트 (작업 4-1).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_recordings.py -v

STT 클라이언트(transcribe_recording)를 모킹해 GPU 서버 없이 검증한다.
TestClient는 BackgroundTasks를 응답 후 동기 실행하므로, POST 반환 뒤 transcript를 바로 확인.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import storage
from app.db.models import RehearsalSession, Recording, Team, TeamMember, Transcript, User
from app.db.session import SessionLocal
from app.main import app
from app.services.stt import SttError, UnsupportedMediaError

client = TestClient(app)

FAKE_SEGMENTS = [{"start": 0.0, "end": 1.5, "text": "안녕하세요 발표를 시작합니다"}]


@pytest.fixture(autouse=True)
def mock_stt(monkeypatch):
    """기본: STT 성공(가짜 세그먼트 반환). 개별 테스트가 필요 시 재정의."""
    monkeypatch.setattr("app.api.routes.recordings.transcribe_recording",
                        lambda path, **kw: FAKE_SEGMENTS)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "recu-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "recu-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    ids = {r: _mkuser(f"recu_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("recu_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 3,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("recu_owner")).json()["id"]
    yield sid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("recu_%")))
        db.commit()
    for ext in ("mp3", "wav", "m4a"):
        storage.delete(storage.recording_key(sid, ext))


REC = "/api/v1/sessions/{}/recording"


def _upload(sid, who="recu_owner", data=b"fake audio bytes", filename="rec.m4a",
            ctype="audio/mp4", duration=120):
    return client.post(REC.format(sid),
                       files={"file": (filename, data, ctype)},
                       data={"duration_seconds": str(duration)}, headers=_auth(who))


def _get(sid, model):
    with SessionLocal() as db:
        return db.get(model, sid)


class TestUploadSuccess:
    def test_upload_transcribes_and_sets_states(self, ctx):
        sid, _ = ctx
        r = _upload(sid)
        assert r.status_code == 202
        assert r.json()["status"] == "queued"
        # STT 잡(BackgroundTask) 이미 실행됨
        rec = _get(sid, Recording)
        assert rec.status == "ready" and rec.duration_seconds == 120
        tr = _get(sid, Transcript)
        assert tr.status == "ready"
        assert tr.segments[0]["text"] == FAKE_SEGMENTS[0]["text"]
        ses = _get(sid, RehearsalSession)
        assert ses.status == "transcribing"  # 세션 전이됨

    def test_file_saved_to_storage(self, ctx):
        sid, _ = ctx
        _upload(sid)
        assert storage.exists(storage.recording_key(sid, "m4a"))

    def test_wav_and_mp3_accepted(self, ctx):
        sid, _ = ctx
        assert _upload(sid, filename="r.wav", ctype="audio/wav").status_code == 202
        assert _upload(sid, filename="r.mp3", ctype="audio/mpeg").status_code == 202

    def test_reupload_overwrites_and_requeues(self, ctx):
        sid, _ = ctx
        _upload(sid, duration=100)
        _upload(sid, duration=200)  # 재업로드
        assert _get(sid, Recording).duration_seconds == 200
        assert _get(sid, Transcript).status == "ready"


class TestSttFailure:
    def test_stt_failure_marks_failed(self, ctx, monkeypatch):
        def boom(path, **kw):
            raise SttError("STT 서버 오류")
        monkeypatch.setattr("app.api.routes.recordings.transcribe_recording", boom)
        sid, _ = ctx
        r = _upload(sid)
        assert r.status_code == 202  # 업로드 자체는 성공
        assert _get(sid, Transcript).status == "failed"
        assert _get(sid, Transcript).error_code == "STT_FAILED"
        assert _get(sid, RehearsalSession).status == "failed"  # 세션도 failed

    def test_unsupported_media_in_job(self, ctx, monkeypatch):
        def boom(path, **kw):
            raise UnsupportedMediaError("디코드 불가")
        monkeypatch.setattr("app.api.routes.recordings.transcribe_recording", boom)
        sid, _ = ctx
        _upload(sid)
        assert _get(sid, Transcript).error_code == "UNSUPPORTED_MEDIA"


class TestValidation:
    def test_non_audio_415(self, ctx):
        sid, _ = ctx
        r = _upload(sid, filename="notes.txt", ctype="text/plain")
        assert r.status_code == 415

    def test_empty_file_400(self, ctx):
        sid, _ = ctx
        assert _upload(sid, data=b"").status_code == 400

    def test_duration_over_3600_400(self, ctx):
        sid, _ = ctx
        r = _upload(sid, duration=3601)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "RECORDING_TOO_LONG"

    def test_missing_duration_422(self, ctx):
        sid, _ = ctx
        r = client.post(REC.format(sid),
                        files={"file": ("r.m4a", b"x", "audio/mp4")}, headers=_auth("recu_owner"))
        assert r.status_code == 422


class TestPermissionAndState:
    def test_member_not_owner_403(self, ctx):
        sid, _ = ctx
        assert _upload(sid, who="recu_member").status_code == 403

    def test_outsider_404(self, ctx):
        sid, _ = ctx
        assert _upload(sid, who="recu_outsider").status_code == 404

    def test_requires_auth(self, ctx):
        sid, _ = ctx
        r = client.post(REC.format(sid), files={"file": ("r.m4a", b"x", "audio/mp4")},
                        data={"duration_seconds": "10"})
        assert r.status_code == 401

    def test_upload_blocked_after_qna(self, ctx):
        """질의응답 단계(qna) 세션엔 녹음 업로드 불가 → 409."""
        sid, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = "qna"
            db.commit()
        r = _upload(sid)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "RECORDING_NOT_ALLOWED"

    def test_concurrent_first_upload_no_500(self, ctx):
        """같은 세션 첫 업로드가 동시에 와도 500 없이 둘 다 202.
        재검증에서 발견: storage._resolve의 .resolve() 레이스로 간헐 500 → 컴포넌트 검증으로 수정."""
        from concurrent.futures import ThreadPoolExecutor
        sid, _ = ctx
        with ThreadPoolExecutor(max_workers=2) as ex:
            codes = sorted(f.result().status_code for f in
                           [ex.submit(_upload, sid) for _ in range(2)])
        assert codes == [202, 202]

    def test_reupload_different_ext_cleans_old_file(self, ctx):
        """m4a → wav 재업로드 시 옛 m4a 파일이 스토리지에서 정리된다 (고아 방지)."""
        sid, _ = ctx
        _upload(sid, filename="r.m4a", ctype="audio/mp4")
        old = storage.recording_key(sid, "m4a")
        assert storage.exists(old)
        _upload(sid, filename="r.wav", ctype="audio/wav")
        assert not storage.exists(old)                      # 옛 파일 정리됨
        assert storage.exists(storage.recording_key(sid, "wav"))

    def test_started_ended_at_stored(self, ctx):
        sid, _ = ctx
        client.post(REC.format(sid), files={"file": ("r.m4a", b"a", "audio/mp4")},
                    data={"duration_seconds": "60", "started_at": "2026-07-12T01:00:00Z",
                          "ended_at": "2026-07-12T01:02:00Z"}, headers=_auth("recu_owner"))
        rec = _get(sid, Recording)
        assert rec.started_at is not None and rec.ended_at is not None

    def test_invalid_started_at_422(self, ctx):
        sid, _ = ctx
        r = client.post(REC.format(sid), files={"file": ("r.m4a", b"a", "audio/mp4")},
                        data={"duration_seconds": "60", "started_at": "not-a-date"},
                        headers=_auth("recu_owner"))
        assert r.status_code == 422

    def test_octet_stream_with_audio_ext_accepted(self, ctx):
        sid, _ = ctx
        assert _upload(sid, filename="r.m4a", ctype="application/octet-stream").status_code == 202

    def test_duration_zero_ok_negative_400(self, ctx):
        sid, _ = ctx
        assert _upload(sid, duration=0).status_code == 202
        assert _upload(sid, duration=-5).status_code == 400

    def test_reupload_after_stt_failure_recovers(self, ctx, monkeypatch):
        """STT 실패로 session=failed → 재업로드(성공 STT)로 transcribing 복귀."""
        sid, _ = ctx
        monkeypatch.setattr("app.api.routes.recordings.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("x")))
        _upload(sid)
        assert _get(sid, RehearsalSession).status == "failed"
        monkeypatch.setattr("app.api.routes.recordings.transcribe_recording",
                            lambda p, **kw: FAKE_SEGMENTS)
        _upload(sid)
        assert _get(sid, RehearsalSession).status == "transcribing"
        assert _get(sid, Transcript).status == "ready"
