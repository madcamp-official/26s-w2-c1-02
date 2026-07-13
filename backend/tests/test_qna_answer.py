"""답변 제출 + 꼬리질문 + 패스 회귀 테스트 (Step 3 작업 4, api-spec §4.4).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_answer.py -v

답변 STT는 stt_queue 워커에서 돌므로 transcribe_recording을 qna_jobs에서 모킹하고,
enqueue 후 stt_queue.join()으로 완료를 기다린다. 꼬리질문 LLM은 기본 mock 제공자
(depth 0 답변엔 꼬리질문 1개 생성, depth 1이면 None). 꼬리질문 TTS도 모킹.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import storage
from app.db.enums import AsyncStatus, QuestionerPersona, QuestionStrategy, SessionStatus
from app.db.models import (
    Answer, Question, RehearsalSession, Report, Team, TeamMember, User,
)
from app.db.session import SessionLocal
from app.main import app
from app.services import stt_queue
from app.services.stt import SttError, UnsupportedMediaError

client = TestClient(app)

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
FAKE_ANSWER = [{"start": 0.0, "end": 1.5, "text": "제 답변입니다"}]


@pytest.fixture(autouse=True)
def mock_stt_tts(monkeypatch):
    """기본: 답변 STT 성공 + 꼬리질문 TTS 성공. 개별 테스트가 STT를 재정의."""
    monkeypatch.setattr("app.services.qna_jobs.transcribe_recording", lambda p, **kw: FAKE_ANSWER)
    monkeypatch.setattr("app.services.qna_jobs.synthesize_question", lambda text, **kw: WAV)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "qans-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "qans-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    """qna 세션 + 1차 질문 2개(order 1·2, tts ready), current=Q1."""
    ids = {r: _mkuser(f"qans_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("qans_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen", "teto"], "question_count": 2,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("qans_owner")).json()["id"]
    with SessionLocal() as db:
        ses = db.get(RehearsalSession, sid)
        ses.status = SessionStatus.qna
        q1 = Question(session_id=sid, order_index=1, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.detail_probe, text="질문 1", tts_status=AsyncStatus.ready)
        q2 = Question(session_id=sid, order_index=2, persona=QuestionerPersona.teto,
                      strategy=QuestionStrategy.big_picture, text="질문 2", tts_status=AsyncStatus.ready)
        db.add_all([q1, q2])
        db.flush()
        ses.current_question_id = q1.id
        db.commit()
        qids = {"q1": q1.id, "q2": q2.id}
    yield sid, qids, ids
    with SessionLocal() as db:
        keys = []
        for q in db.scalars(select(Question).where(Question.session_id == sid)).all():
            keys.append(storage.tts_key(sid, q.id))
            a = db.get(Answer, q.id)
            if a is not None and a.audio_storage_key:
                keys.append(a.audio_storage_key)
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("qans_%")))
        db.commit()
    for k in keys:
        storage.delete(k)


ANS = "/api/v1/sessions/{}/qna/questions/{}/answer"
PASS = "/api/v1/sessions/{}/qna/questions/{}/pass"


def _answer(sid, qid, who="qans_owner", data=b"audio bytes",
            filename="a.m4a", ctype="audio/mp4", duration=30):
    r = client.post(ANS.format(sid, qid), files={"file": (filename, data, ctype)},
                    data={"duration_seconds": str(duration)}, headers=_auth(who))
    stt_queue.join()  # 답변 STT 잡 완료까지 대기
    return r


def _pass(sid, qid, reason=None, who="qans_owner"):
    return client.post(PASS.format(sid, qid),
                       json=({"reason": reason} if reason else None), headers=_auth(who))


def _answer_obj(qid):
    with SessionLocal() as db:
        return db.get(Answer, qid)


def _session(sid):
    with SessionLocal() as db:
        return db.get(RehearsalSession, sid)


def _children(qid):
    with SessionLocal() as db:
        return db.scalars(select(Question).where(Question.parent_id == qid)).all()


class TestSubmitAcceptance:
    def test_returns_202_processing(self, ctx):
        sid, q, _ = ctx
        r = _answer(sid, q["q1"])
        assert r.status_code == 202
        ans = r.json()["answer"]
        assert ans["status"] == "processing"        # 접수 시점 응답은 processing
        assert ans["follow_up_status"] == "pending"
        assert ans["text"] is None
        assert ans["audio_url"].startswith("/api/v1/files/")


class TestAnswerFlow:
    def test_answer_sets_ready_and_text(self, ctx):
        sid, q, _ = ctx
        _answer(sid, q["q1"])
        a = _answer_obj(q["q1"])
        assert a.status == "ready"
        assert a.text == "제 답변입니다"
        assert a.kind == "answered"

    def test_follow_up_generated_moves_current(self, ctx):
        sid, q, _ = ctx
        _answer(sid, q["q1"])
        children = _children(q["q1"])
        assert len(children) == 1                    # mock: depth 0 답변 → 꼬리질문 1개
        child = children[0]
        assert child.follow_up_depth == 1
        assert child.order_index == 1                # 부모와 같은 순번(부모 뒤 표시)
        assert child.tts_status == "ready"           # 꼬리질문 TTS 인라인 합성
        assert _answer_obj(q["q1"]).follow_up_status == "generated"
        assert _session(sid).current_question_id == child.id  # 꼬리질문으로 이동

    def test_answer_followup_advances_to_next_primary(self, ctx):
        sid, q, _ = ctx
        _answer(sid, q["q1"])
        child = _children(q["q1"])[0]
        _answer(sid, child.id)                       # 꼬리질문(depth 1) 답변
        ca = _answer_obj(child.id)
        assert ca.status == "ready"
        assert ca.follow_up_status == "none"         # 깊이 1 도달 → 꼬리질문 없음
        assert _children(child.id) == []
        assert _session(sid).current_question_id == q["q2"]  # 다음 1차 질문으로


class TestAnswerFailure:
    def test_stt_failure_marks_failed_current_unchanged(self, ctx, monkeypatch):
        monkeypatch.setattr("app.services.qna_jobs.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("STT 서버 오류")))
        sid, q, _ = ctx
        r = _answer(sid, q["q1"])
        assert r.status_code == 202                  # 접수는 성공
        a = _answer_obj(q["q1"])
        assert a.status == "failed"
        assert a.error_code == "STT_FAILED"
        assert _children(q["q1"]) == []              # 꼬리질문 안 만들어짐
        assert _session(sid).current_question_id == q["q1"]  # current 그대로

    def test_unsupported_media_in_job(self, ctx, monkeypatch):
        monkeypatch.setattr("app.services.qna_jobs.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(UnsupportedMediaError("디코드 불가")))
        sid, q, _ = ctx
        _answer(sid, q["q1"])
        assert _answer_obj(q["q1"]).error_code == "UNSUPPORTED_MEDIA"

    def test_resubmit_after_failure_recovers(self, ctx, monkeypatch):
        sid, q, _ = ctx
        monkeypatch.setattr("app.services.qna_jobs.transcribe_recording",
                            lambda p, **kw: (_ for _ in ()).throw(SttError("x")))
        _answer(sid, q["q1"])
        assert _answer_obj(q["q1"]).status == "failed"
        monkeypatch.setattr("app.services.qna_jobs.transcribe_recording", lambda p, **kw: FAKE_ANSWER)
        _answer(sid, q["q1"])                         # 같은 질문 재제출
        assert _answer_obj(q["q1"]).status == "ready"


class _NoFollowUp:
    async def generate_questions(self, **kw):
        return []

    async def follow_up(self, **kw):
        return None


class TestAutoEnd:
    def test_last_primary_no_followup_ends_count_reached(self, ctx, monkeypatch):
        """꼬리질문 없이 마지막 1차 질문까지 답하면 자동 종료(count_reached) + 리포트 큐."""
        monkeypatch.setattr("app.services.qna_jobs.get_llm_provider", lambda: _NoFollowUp())
        sid, q, _ = ctx
        _pass(sid, q["q1"])                           # Q1 패스 → current=Q2
        assert _session(sid).current_question_id == q["q2"]
        _answer(sid, q["q2"])                         # 마지막 1차 답변 (꼬리질문 없음)
        ses = _session(sid)
        assert ses.status == "completed"
        assert ses.qna_ended_reason == "count_reached"
        assert ses.current_question_id is None
        with SessionLocal() as db:
            assert db.get(Report, sid).status == "queued"  # 리포트 잡 트리거(Step 4)


class TestPass:
    def test_pass_advances_to_next(self, ctx):
        sid, q, _ = ctx
        r = _pass(sid, q["q1"])
        assert r.status_code == 200
        assert r.json()["current_question_id"] == q["q2"]
        a = _answer_obj(q["q1"])
        assert a.kind == "passed"
        assert a.status == "ready"
        assert a.audio_storage_key is None
        assert a.follow_up_status == "none"
        assert _session(sid).current_question_id == q["q2"]

    def test_pass_last_timeout_ends_timeout(self, ctx):
        sid, q, _ = ctx
        _pass(sid, q["q1"])                           # → Q2
        r = _pass(sid, q["q2"], reason="timeout")     # 마지막을 시간초과로 넘김
        assert r.status_code == 200
        ses = _session(sid)
        assert ses.status == "completed"
        assert ses.qna_ended_reason == "timeout"      # A12: 마지막이 timeout이면 timeout
        with SessionLocal() as db:
            assert db.get(Report, sid).status == "queued"

    def test_pass_last_user_ends_count_reached(self, ctx):
        sid, q, _ = ctx
        _pass(sid, q["q1"])
        _pass(sid, q["q2"])                           # reason 없음(user) → count_reached
        ses = _session(sid)
        assert ses.status == "completed"
        assert ses.qna_ended_reason == "count_reached"


class TestGuards:
    def test_answer_not_current_409(self, ctx):
        sid, q, _ = ctx
        r = _answer(sid, q["q2"])                     # current는 Q1
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "NOT_CURRENT_QUESTION"

    def test_answer_session_not_qna_409(self, ctx):
        sid, q, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.transcribing
            db.commit()
        r = _answer(sid, q["q1"])
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QNA_NOT_ACTIVE"

    def test_answer_unsupported_media_415(self, ctx):
        sid, q, _ = ctx
        r = _answer(sid, q["q1"], filename="a.txt", ctype="text/plain")
        assert r.status_code == 415

    def test_answer_empty_400(self, ctx):
        sid, q, _ = ctx
        assert _answer(sid, q["q1"], data=b"").status_code == 400

    def test_answer_unknown_question_404(self, ctx):
        sid, _, _ = ctx
        r = _answer(sid, "q_nonexistent")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUESTION_NOT_FOUND"

    def test_member_not_owner_403(self, ctx):
        sid, q, _ = ctx
        assert _answer(sid, q["q1"], who="qans_member").status_code == 403

    def test_outsider_404(self, ctx):
        sid, q, _ = ctx
        assert _answer(sid, q["q1"], who="qans_outsider").status_code == 404

    def test_requires_auth(self, ctx):
        sid, q, _ = ctx
        r = client.post(ANS.format(sid, q["q1"]), files={"file": ("a.m4a", b"x", "audio/mp4")},
                        data={"duration_seconds": "10"})
        assert r.status_code == 401

    def test_pass_not_current_409(self, ctx):
        sid, q, _ = ctx
        r = _pass(sid, q["q2"])                       # current는 Q1
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "NOT_CURRENT_QUESTION"
