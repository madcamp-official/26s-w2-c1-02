"""실시간 녹음 청크 파이프라인 테스트 (api-spec §4.3.1).

POST /recording/chunks · POST /recording/complete + 병합(merge_chunk_segments).
STT 클라이언트(transcribe_recording)를 모킹해 GPU 서버 없이 검증한다.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_recording_chunks.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import storage
from app.db.models import (
    Recording,
    RecordingChunk,
    RehearsalSession,
    Team,
    TeamMember,
    Transcript,
    User,
)
from app.db.session import SessionLocal
from app.main import app
from app.services import stt_queue
from app.services.stt import merge_chunk_segments

client = TestClient(app)

FAKE_SEGMENTS = [{"start": 0.0, "end": 1.5, "text": "안녕하세요 청크입니다"}]


@pytest.fixture(autouse=True)
def mock_stt(monkeypatch):
    """기본: STT 성공(가짜 세그먼트). 청크·complete 폴백 모두 stt_queue의
    transcribe_recording을 거치므로 여기서 패치한다."""
    monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                        lambda path, **kw: FAKE_SEGMENTS)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "rchk-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "rchk-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    ids = {r: _mkuser(f"rchk_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("rchk_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 3,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("rchk_owner")).json()["id"]
    yield sid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("rchk_%")))
        db.commit()
    for ext in ("mp3", "wav", "m4a"):
        storage.delete(storage.recording_key(sid, ext))


CHUNKS = "/api/v1/sessions/{}/recording/chunks"
COMPLETE = "/api/v1/sessions/{}/recording/complete"


def _chunk(sid, seq, who="rchk_owner", *, offset=0.0, overlap=0.0, duration=5.0,
           data=b"chunkdata", ctype="audio/wav", filename=None):
    r = client.post(CHUNKS.format(sid),
                    files={"file": (filename or f"c{seq}.wav", data, ctype)},
                    data={"seq": str(seq), "offset_seconds": str(offset),
                          "overlap_seconds": str(overlap), "duration_seconds": str(duration)},
                    headers=_auth(who))
    stt_queue.join()  # 청크 STT 잡 완료 대기
    return r


def _complete(sid, total, who="rchk_owner", *, duration=120,
              data=b"fullfile", ctype="audio/wav", filename="rec.wav"):
    r = client.post(COMPLETE.format(sid),
                    files={"file": (filename, data, ctype)},
                    data={"total_chunks": str(total), "duration_seconds": str(duration)},
                    headers=_auth(who))
    stt_queue.join()  # 병합/폴백 잡 완료 대기
    return r


def _get(sid, model, pk=None):
    with SessionLocal() as db:
        return db.get(model, pk if pk is not None else sid)


def _chunk_rows(sid):
    with SessionLocal() as db:
        return db.scalars(
            select(RecordingChunk).where(RecordingChunk.session_id == sid)
            .order_by(RecordingChunk.seq)
        ).all()


class TestChunkUpload:
    def test_chunk_accepted_and_transcribed(self, ctx):
        sid, _ = ctx
        r = _chunk(sid, 0, offset=0.0, overlap=0.0)
        assert r.status_code == 202
        assert r.json() == {"received_seq": 0}
        chunk = _get(sid, RecordingChunk, (sid, 0))
        assert chunk.status == "ready"
        assert chunk.segments == FAKE_SEGMENTS
        assert chunk.offset_seconds == 0.0
        # 청크 수신 중: transcript processing, 세션 recording_in_progress
        assert _get(sid, Transcript).status == "processing"
        assert _get(sid, RehearsalSession).status == "recording_in_progress"

    def test_first_chunk_transitions_draft(self, ctx):
        sid, _ = ctx
        assert _get(sid, RehearsalSession).status == "draft"
        _chunk(sid, 0)
        assert _get(sid, RehearsalSession).status == "recording_in_progress"

    def test_resend_same_seq_is_idempotent(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, offset=0.0).json()["received_seq"] == 0
        assert _chunk(sid, 0, offset=99.0).json()["received_seq"] == 0
        rows = _chunk_rows(sid)
        assert len(rows) == 1              # 덮어쓰기 — 행 하나
        assert rows[0].offset_seconds == 99.0  # 최신 메타로 갱신

    def test_multiple_seqs_stored(self, ctx):
        sid, _ = ctx
        _chunk(sid, 0, offset=0.0, overlap=0.0)
        _chunk(sid, 1, offset=56.0, overlap=4.0)
        rows = _chunk_rows(sid)
        assert [r.seq for r in rows] == [0, 1]

    def test_seq_negative_400(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, -1).status_code == 400

    def test_bad_metadata_400(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, duration=0).status_code == 400

    def test_non_audio_415(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, ctype="text/plain", filename="c.txt").status_code == 415

    def test_empty_chunk_400(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, data=b"").status_code == 400

    def test_member_not_owner_403(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, who="rchk_member").status_code == 403

    def test_outsider_404(self, ctx):
        sid, _ = ctx
        assert _chunk(sid, 0, who="rchk_outsider").status_code == 404

    def test_requires_auth(self, ctx):
        sid, _ = ctx
        r = client.post(CHUNKS.format(sid), files={"file": ("c0.wav", b"x", "audio/wav")},
                        data={"seq": "0", "offset_seconds": "0", "overlap_seconds": "0",
                              "duration_seconds": "5"})
        assert r.status_code == 401


class TestComplete:
    def test_complete_all_present_merges(self, ctx, monkeypatch):
        """모든 청크가 도착하면 저장된 청크 세그먼트를 병합(전체 파일 재전사 아님)."""
        merged = [{"start": 9.9, "end": 9.9, "text": "MERGED"}]
        monkeypatch.setattr("app.services.stt_queue.merge_chunk_segments",
                            lambda chunks: merged)
        sid, _ = ctx
        _chunk(sid, 0, offset=0.0, overlap=0.0)
        _chunk(sid, 1, offset=56.0, overlap=4.0)
        r = _complete(sid, total=2)
        assert r.status_code == 202
        assert _get(sid, Transcript).status == "ready"
        assert _get(sid, Transcript).segments == merged   # 병합 경로 탐
        rec = _get(sid, Recording)
        assert rec.total_chunks == 2
        assert _get(sid, RehearsalSession).status == "transcribing"

    def test_complete_missing_chunk_falls_back_to_full_file(self, ctx):
        """청크 누락 시 complete의 전체 파일을 재전사(안전망 ②)."""
        sid, _ = ctx
        _chunk(sid, 0, offset=0.0, overlap=0.0)   # seq 1 누락
        r = _complete(sid, total=2)
        assert r.status_code == 202
        tr = _get(sid, Transcript)
        assert tr.status == "ready"
        assert tr.segments == FAKE_SEGMENTS        # 전체 파일 폴백 결과

    def test_complete_failed_chunk_falls_back(self, ctx, monkeypatch):
        """청크 STT 실패가 섞여도 complete는 전체 파일로 복구된다(세션 failed 아님)."""
        def boom(path, **kw):
            raise ValueError("청크 STT 실패")
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording", boom)
        sid, _ = ctx
        _chunk(sid, 0)
        assert _get(sid, RecordingChunk, (sid, 0)).status == "failed"
        # 세션·transcript는 청크 실패로 죽지 않는다
        assert _get(sid, RehearsalSession).status == "recording_in_progress"

        # complete: 전체 파일은 성공 STT로 복구
        monkeypatch.setattr("app.services.stt_queue.transcribe_recording",
                            lambda path, **kw: FAKE_SEGMENTS)
        _complete(sid, total=1)
        assert _get(sid, Transcript).status == "ready"
        assert _get(sid, Transcript).segments == FAKE_SEGMENTS

    def test_complete_member_not_owner_403(self, ctx):
        sid, _ = ctx
        assert _complete(sid, total=0, who="rchk_member").status_code == 403


class TestMergeChunkSegments:
    """merge_chunk_segments 순수 로직 (③ 앞겹침 절단 + 오프셋 보정)."""

    def test_overlap_dedup_and_offset_shift(self):
        # chunk0=[0,60) offset0 overlap0 ; chunk1=[56,120) offset56 overlap4
        # 경계 절단 = chunk1.offset + overlap/2 = 58
        chunks = [
            {"offset": 0, "overlap": 0, "segments": [
                {"start": 10, "end": 12, "text": "A"},
                {"start": 57, "end": 59, "text": "DUP"}]},   # abs[57,59] mid58 → 배제(hi0=58)
            {"offset": 56, "overlap": 4, "segments": [
                {"start": 1, "end": 3, "text": "DUP"},        # abs[57,59] mid58 → 채택(lo1=58)
                {"start": 10, "end": 12, "text": "B"}]},      # abs[66,68]
        ]
        out = merge_chunk_segments(chunks)
        assert [s["text"] for s in out] == ["A", "DUP", "B"]  # DUP 한 번만
        assert out[0] == {"start": 10.0, "end": 12.0, "text": "A"}
        assert out[1] == {"start": 57.0, "end": 59.0, "text": "DUP"}
        assert out[2] == {"start": 66.0, "end": 68.0, "text": "B"}

    def test_single_chunk_passthrough(self):
        out = merge_chunk_segments(
            [{"offset": 0, "overlap": 0, "segments": [{"start": 1, "end": 2, "text": "X"}]}])
        assert out == [{"start": 1.0, "end": 2.0, "text": "X"}]

    def test_empty(self):
        assert merge_chunk_segments([]) == []
