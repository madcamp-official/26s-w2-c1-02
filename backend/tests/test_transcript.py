"""전사 조회·재시도 회귀 테스트 (작업 4-3).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_transcript.py -v

STT를 모킹하고, 업로드 후 stt_queue.join()으로 큐 드레인을 기다린다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import storage
from app.db.models import RehearsalSession, Team, TeamMember, Transcript, User
from app.db.session import SessionLocal
from app.main import app
from app.services import stt_queue
from app.services.stt import SttError

client = TestClient(app)

# start=72.5초 → ts "01:12" 변환 확인용
FAKE_SEGMENTS = [
    {"start": 12.0, "end": 15.2, "text": "안녕하세요 발표를 시작합니다"},
    {"start": 72.5, "end": 75.0, "text": "성능은 두 배 개선됐습니다"},
]


@pytest.fixture(autouse=True)
def mock_stt(monkeypatch):
    monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                        lambda path, **kw: FAKE_SEGMENTS)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "trsc-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "trsc-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    ids = {r: _mkuser(f"trsc_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("trsc_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 3,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("trsc_owner")).json()["id"]
    yield sid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("trsc_%")))
        db.commit()
    storage.delete(storage.recording_key(sid, "m4a"))


def _upload(sid, who="trsc_owner", duration=120):
    r = client.post(f"/api/v1/sessions/{sid}/recording",
                    files={"file": ("r.m4a", b"audio", "audio/mp4")},
                    data={"duration_seconds": str(duration)}, headers=_auth(who))
    stt_queue.join()
    return r


TR = "/api/v1/sessions/{}/transcript"


class TestGetTranscript:
    def test_ready_transcript_ts_formatted(self, ctx):
        """저장은 초 float, 응답은 ts:'MM:SS'. 72.5초 → '01:12'."""
        sid, _ = ctx
        _upload(sid)
        r = client.get(TR.format(sid), headers=_auth("trsc_owner"))
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "ready"
        assert b["segments"][0]["ts"] == "00:12"
        assert b["segments"][1]["ts"] == "01:12"          # 72.5초 → 01:12
        assert "start" not in b["segments"][0]            # 응답엔 초 float 노출 안 함
        assert b["segments"][0]["text"] == FAKE_SEGMENTS[0]["text"]
        assert b["error"] is None

    def test_failed_transcript_returns_error(self, ctx, monkeypatch):
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("서버 오류")))
        sid, _ = ctx
        _upload(sid)
        b = client.get(TR.format(sid), headers=_auth("trsc_owner")).json()
        assert b["status"] == "failed"
        assert b["error"]["code"] == "STT_FAILED"
        assert b["segments"] is None

    def test_member_can_view(self, ctx):
        sid, _ = ctx
        _upload(sid)
        assert client.get(TR.format(sid), headers=_auth("trsc_member")).status_code == 200

    def test_outsider_404(self, ctx):
        sid, _ = ctx
        _upload(sid)
        assert client.get(TR.format(sid), headers=_auth("trsc_outsider")).status_code == 404

    def test_no_transcript_404(self, ctx):
        sid, _ = ctx  # 녹음 업로드 전
        r = client.get(TR.format(sid), headers=_auth("trsc_owner"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "TRANSCRIPT_NOT_FOUND"


class TestRetryTranscript:
    def test_retry_failed_recovers_to_ready(self, ctx, monkeypatch):
        """STT 실패 → retry(성공) → transcript ready + 세션 transcribing 복귀."""
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("fail")))
        sid, _ = ctx
        _upload(sid)
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid).status == "failed"
        # STT를 정상으로 바꾸고 retry
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: FAKE_SEGMENTS)
        r = client.post(TR.format(sid) + "/retry", headers=_auth("trsc_owner"))
        assert r.status_code == 202
        stt_queue.join()
        with SessionLocal() as db:
            assert db.get(Transcript, sid).status == "ready"
            assert db.get(RehearsalSession, sid).status == "transcribing"

    def test_retry_ready_409(self, ctx):
        sid, _ = ctx
        _upload(sid)  # ready
        r = client.post(TR.format(sid) + "/retry", headers=_auth("trsc_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "TRANSCRIPT_NOT_RETRYABLE"

    def test_retry_no_transcript_404(self, ctx):
        sid, _ = ctx
        assert client.post(TR.format(sid) + "/retry",
                           headers=_auth("trsc_owner")).status_code == 404

    def test_member_cannot_retry_403(self, ctx, monkeypatch):
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("fail")))
        sid, _ = ctx
        _upload(sid)
        assert client.post(TR.format(sid) + "/retry",
                           headers=_auth("trsc_member")).status_code == 403

    def test_concurrent_double_retry_no_500(self, ctx, monkeypatch):
        """동시 double retry — 500이 나지 않아야 한다. (잠금이 없어 결과는 비결정적:
        둘 다 failed를 읽으면 202/202, 한쪽이 먼저 queued로 바꾸면 202/409.
        double-enqueue돼도 워커가 직렬 처리하므로 무해.)"""
        from concurrent.futures import ThreadPoolExecutor
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("fail")))
        sid, _ = ctx
        _upload(sid)
        with ThreadPoolExecutor(max_workers=2) as ex:
            codes = sorted(f.result().status_code for f in
                           [ex.submit(client.post, TR.format(sid) + "/retry",
                                      headers=_auth("trsc_owner")) for _ in range(2)])
        stt_queue.join()
        assert 500 not in codes
        assert 202 in codes  # 적어도 하나는 재시도 접수

    def test_retry_genuinely_requeues_same_failure_stays_failed(self, ctx, monkeypatch):
        """같은 실패 STT로 retry하면 다시 failed — 재큐·재전사가 실제로 일어남을 증명."""
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("still")))
        sid, _ = ctx
        _upload(sid)
        client.post(TR.format(sid) + "/retry", headers=_auth("trsc_owner"))
        stt_queue.join()
        assert _get(sid, Transcript).status == "failed"


class TestFullPipeline:
    def test_upload_to_transcript_ready_ts_formatted(self, ctx):
        """녹음 업로드 → STT → GET transcript(ready, ts 변환)까지 한 흐름."""
        sid, _ = ctx
        assert _upload(sid).status_code == 202
        # 세션 transcribing 전이
        assert _get(sid, RehearsalSession).status == "transcribing"
        # transcript 폴링(여기선 join으로 이미 ready)
        b = client.get(TR.format(sid), headers=_auth("trsc_owner")).json()
        assert b["status"] == "ready"
        assert b["segments"][1]["ts"] == "01:12"  # 72.5초


def _get(sid, model):
    with SessionLocal() as db:
        return db.get(model, sid)
