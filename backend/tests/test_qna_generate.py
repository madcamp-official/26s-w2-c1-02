"""질문 생성 엔드포인트 회귀 테스트 (Step 3 작업 2, api-spec §4.4).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_generate.py -v

LLM은 기본 mock 제공자(LLM_PROVIDER=mock)라 GPU/키 없이 count개 질문을 만든다.
TTS(synthesize_question)는 qna_jobs에서 모킹해 서버 없이 검증한다.
TestClient는 BackgroundTasks를 응답 후 동기 실행하므로, POST 반환 뒤 DB를 바로 확인한다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import storage
from app.db.enums import AsyncStatus, SessionStatus
from app.db.models import (
    Material, Question, RehearsalSession, Team, TeamMember, Transcript, User,
)
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified
from app.services.tts import TtsError

client = TestClient(app)

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
QCOUNT = 3  # 세션 question_count


@pytest.fixture(autouse=True)
def mock_tts(monkeypatch):
    """기본: TTS 성공(가짜 wav). qna_jobs가 import한 이름을 패치. 개별 테스트가 재정의 가능."""
    monkeypatch.setattr("app.services.qna_jobs.synthesize_question", lambda text, **kw: WAV)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "qgen-pass-123", "email": f"{u}@t.io"})
    mark_email_verified(u)  # 로그인 차단(403) 우회 — email-verification-plan 작업 6
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "qgen-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ready_session():
    """owner·member·outsider + 팀 + 세션(question_count=3). 전사 ready + 세션 transcribing 시드."""
    ids = {r: _mkuser(f"qgen_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("qgen_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen", "teto"], "question_count": QCOUNT,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("qgen_owner")).json()["id"]
    # STT까지 끝난 상태를 시드 (transcribing + transcript ready)
    with SessionLocal() as db:
        db.get(RehearsalSession, sid).status = SessionStatus.transcribing
        db.add(Transcript(session_id=sid, status=AsyncStatus.ready,
                          segments=[{"start": 0.0, "end": 2.0, "text": "안녕하세요 발표입니다"}]))
        db.commit()
    yield sid, ids
    with SessionLocal() as db:
        qids = db.scalars(select(Question.id).where(Question.session_id == sid)).all()
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("qgen_%")))
        db.commit()
    for qid in qids:
        storage.delete(storage.tts_key(sid, qid))


GEN = "/api/v1/sessions/{}/qna/generate"


def _questions(sid):
    with SessionLocal() as db:
        return db.scalars(
            select(Question).where(Question.session_id == sid).order_by(Question.order_index)
        ).all()


class TestGenerateSuccess:
    def test_generates_questions_and_moves_to_qna(self, ready_session):
        sid, _ = ready_session
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 202
        assert r.json()["status"] == "generating_questions"

        with SessionLocal() as db:
            ses = db.get(RehearsalSession, sid)
            assert ses.status == "qna"                       # 백그라운드 잡이 qna로 전이
            qs = db.scalars(select(Question).where(Question.session_id == sid)
                            .order_by(Question.order_index)).all()
            assert len(qs) == QCOUNT
            assert [q.order_index for q in qs] == [1, 2, 3]
            assert all(q.parent_id is None and q.follow_up_depth == 0 for q in qs)
            assert ses.current_question_id == qs[0].id        # 첫 질문으로 이동

    def test_personas_assigned_from_session_pool(self, ready_session):
        sid, _ = ready_session
        client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        personas = {q.persona for q in _questions(sid)}
        assert personas <= {"egen", "teto"}                   # 세션이 고른 목록 안에서만 배정

    def test_tts_synthesized_and_saved(self, ready_session):
        sid, _ = ready_session
        client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        for q in _questions(sid):
            assert q.tts_status == "ready"
            assert q.tts_storage_key is not None
            assert storage.exists(storage.tts_key(sid, q.id))


class TestGenerateFailures:
    def test_tts_failure_keeps_qna_marks_tts_failed(self, ready_session, monkeypatch):
        """TTS가 실패해도 질문 생성 자체는 성공(qna) — tts만 failed로 폴링 노출."""
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question",
                            lambda text, **kw: (_ for _ in ()).throw(TtsError("tts 서버 다운")))
        sid, _ = ready_session
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 202
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid).status == "qna"
        for q in _questions(sid):
            assert q.tts_status == "failed"
            assert q.tts_error_code == "TTS_FAILED"

    def test_llm_failure_marks_session_failed(self, ready_session, monkeypatch):
        """LLM 생성 실패 → 세션 failed(재시도 경로), 질문 0개."""
        class BoomProvider:
            async def generate_questions(self, **kw):
                raise RuntimeError("LLM 다운")

            async def follow_up(self, **kw):
                return None

        monkeypatch.setattr("app.services.qna_jobs.get_llm_provider", lambda: BoomProvider())
        sid, _ = ready_session
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 202                            # 접수 자체는 성공
        with SessionLocal() as db:
            assert db.get(RehearsalSession, sid).status == "failed"
        assert _questions(sid) == []


class TestGeneratePreconditions:
    def test_transcript_not_ready_409(self, ready_session):
        sid, _ = ready_session
        with SessionLocal() as db:
            db.get(Transcript, sid).status = AsyncStatus.processing
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"
        assert _questions(sid) == []

    def test_no_transcript_409(self, ready_session):
        sid, _ = ready_session
        with SessionLocal() as db:
            db.execute(delete(Transcript).where(Transcript.session_id == sid))
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"

    def test_material_not_ready_409(self, ready_session):
        sid, _ = ready_session
        with SessionLocal() as db:
            db.add(Material(session_id=sid, status=AsyncStatus.processing,
                            file_name="d.pdf", file_size_bytes=1000, storage_key="k"))
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "MATERIAL_NOT_READY"

    def test_ready_material_allows_generate(self, ready_session):
        sid, _ = ready_session
        with SessionLocal() as db:
            db.add(Material(session_id=sid, status=AsyncStatus.ready, file_name="d.pdf",
                            file_size_bytes=1000, storage_key="k", page_count=2,
                            slides=[{"page": 1, "text": "표지"}, {"page": 2, "text": "본문"}]))
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 202
        assert len(_questions(sid)) == QCOUNT

    def test_already_qna_409(self, ready_session):
        sid, _ = ready_session
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.qna
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QNA_ALREADY_STARTED"

    def test_draft_session_cannot_generate(self, ready_session):
        """전사 없는 draft 세션은 생성 불가 (전사 검사에서 먼저 막힘)."""
        sid, _ = ready_session
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.draft
            db.execute(delete(Transcript).where(Transcript.session_id == sid))
            db.commit()
        r = client.post(GEN.format(sid), headers=_auth("qgen_owner"))
        assert r.status_code == 409


class TestGeneratePermissions:
    def test_member_not_owner_403(self, ready_session):
        sid, _ = ready_session
        assert client.post(GEN.format(sid), headers=_auth("qgen_member")).status_code == 403

    def test_outsider_404(self, ready_session):
        sid, _ = ready_session
        assert client.post(GEN.format(sid), headers=_auth("qgen_outsider")).status_code == 404

    def test_requires_auth(self, ready_session):
        sid, _ = ready_session
        assert client.post(GEN.format(sid)).status_code == 401
