"""질문 TTS 잡 회귀 테스트 (Step 3 작업 3) — qna_jobs의 TTS 합성 함수를 직접 겨냥.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_tts.py -v

TTS 서버 없이 synthesize_question(qna_jobs가 import한 이름)을 모킹해 검증한다.
검증 축(계획서 3-2): queued→processing→ready 전이·wav 저장, queued만 처리(ready 스킵),
TtsError·예상외 예외 → failed(stuck 방지), 실패 후 재합성 복구, 세션 내 단일 클라이언트 공유.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import storage
from app.db.enums import AsyncStatus, QuestionerPersona, QuestionStrategy
from app.db.models import Question, Team, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import mark_email_verified
from app.services import qna_jobs
from app.services.tts import TtsError

client = TestClient(app)

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "qtts-pass-123", "email": f"{u}@t.io"})
    mark_email_verified(u)  # 로그인 차단(403) 우회 — email-verification-plan 작업 6
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "qtts-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def session_with_questions():
    """세션 + queued TTS 질문 2개(order 1·2)를 DB에 직접 시드. (session 상태는 무관)"""
    _mkuser("qtts_owner")
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("qtts_owner")).json()["id"]
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 3,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("qtts_owner")).json()["id"]
    with SessionLocal() as db:
        qs = [Question(session_id=sid, order_index=i, persona=QuestionerPersona.egen,
                       strategy=QuestionStrategy.detail_probe, text=f"질문 {i}") for i in (1, 2)]
        db.add_all(qs)
        db.commit()
        qids = [q.id for q in qs]
    yield sid, qids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("qtts_%")))
        db.commit()
    for qid in qids:
        storage.delete(storage.tts_key(sid, qid))


def _get(qid):
    with SessionLocal() as db:
        return db.get(Question, qid)


class TestSynthesizeOne:
    def test_success_sets_ready_and_saves_wav(self, session_with_questions, monkeypatch):
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question", lambda text, **kw: WAV)
        sid, qids = session_with_questions
        with SessionLocal() as db:
            qna_jobs._synthesize_one(db, db.get(Question, qids[0]))
        q = _get(qids[0])
        assert q.tts_status == "ready"
        assert q.tts_storage_key == storage.tts_key(sid, qids[0])
        assert q.tts_error_code is None
        assert storage.exists(storage.tts_key(sid, qids[0]))

    def test_tts_error_marks_failed(self, session_with_questions, monkeypatch):
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question",
                            lambda text, **kw: (_ for _ in ()).throw(TtsError("서버 다운")))
        sid, qids = session_with_questions
        with SessionLocal() as db:
            qna_jobs._synthesize_one(db, db.get(Question, qids[0]))
        q = _get(qids[0])
        assert q.tts_status == "failed"
        assert q.tts_error_code == "TTS_FAILED"
        assert q.tts_storage_key is None
        assert not storage.exists(storage.tts_key(sid, qids[0]))

    def test_unexpected_exception_not_stuck(self, session_with_questions, monkeypatch):
        """TtsError가 아닌 예외도 failed로 확정 — processing에 영원히 멈추면 FE 무한 폴링."""
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question",
                            lambda text, **kw: (_ for _ in ()).throw(ValueError("예상 못한 버그")))
        _sid, qids = session_with_questions
        with SessionLocal() as db:
            qna_jobs._synthesize_one(db, db.get(Question, qids[0]))
        q = _get(qids[0])
        assert q.tts_status == "failed"          # processing 아님
        assert q.tts_error_code == "TTS_FAILED"

    def test_recovers_after_failure(self, session_with_questions, monkeypatch):
        """실패로 failed가 된 질문을 다시 합성하면 ready + 에러 클리어."""
        sid, qids = session_with_questions
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question",
                            lambda text, **kw: (_ for _ in ()).throw(TtsError("일시 오류")))
        with SessionLocal() as db:
            qna_jobs._synthesize_one(db, db.get(Question, qids[0]))
        assert _get(qids[0]).tts_status == "failed"

        monkeypatch.setattr("app.services.qna_jobs.synthesize_question", lambda text, **kw: WAV)
        with SessionLocal() as db:
            qna_jobs._synthesize_one(db, db.get(Question, qids[0]))
        q = _get(qids[0])
        assert q.tts_status == "ready"
        assert q.tts_error_code is None
        assert q.tts_error_message is None


class TestSynthesizeSession:
    def test_all_queued_synthesized(self, session_with_questions, monkeypatch):
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question", lambda text, **kw: WAV)
        sid, qids = session_with_questions
        with SessionLocal() as db:
            qna_jobs._synthesize_session_tts(db, sid)
        for qid in qids:
            assert _get(qid).tts_status == "ready"
            assert storage.exists(storage.tts_key(sid, qid))

    def test_only_queued_processed_and_shares_client(self, session_with_questions, monkeypatch):
        """이미 ready인 질문은 재합성하지 않고, 남은 것만 하나의 공유 클라이언트로 처리."""
        seen_clients = []

        def fake(text, **kw):
            seen_clients.append(kw.get("client"))
            return WAV

        monkeypatch.setattr("app.services.qna_jobs.synthesize_question", fake)
        sid, qids = session_with_questions
        # qids[0]은 이미 합성 완료 상태로 만들어 둔다
        with SessionLocal() as db:
            done = db.get(Question, qids[0])
            done.tts_status = AsyncStatus.ready
            done.tts_storage_key = "preexisting-key"
            db.commit()

        with SessionLocal() as db:
            qna_jobs._synthesize_session_tts(db, sid)

        # queued였던 qids[1] 하나만 합성, 공유 httpx.Client가 전달됨
        assert len(seen_clients) == 1
        import httpx
        assert isinstance(seen_clients[0], httpx.Client)
        assert _get(qids[1]).tts_status == "ready"
        # 기존 ready 질문은 건드리지 않음
        assert _get(qids[0]).tts_storage_key == "preexisting-key"

    def test_no_queued_is_noop(self, session_with_questions, monkeypatch):
        called = []
        monkeypatch.setattr("app.services.qna_jobs.synthesize_question",
                            lambda text, **kw: called.append(1) or WAV)
        sid, qids = session_with_questions
        with SessionLocal() as db:
            for qid in qids:
                db.get(Question, qid).tts_status = AsyncStatus.ready
            db.commit()
        with SessionLocal() as db:
            qna_jobs._synthesize_session_tts(db, sid)
        assert called == []                       # 합성 호출 없음
