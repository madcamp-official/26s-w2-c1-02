"""GET /qna 폴링 소스 회귀 테스트 (Step 3 작업 5-1, api-spec §4.4).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_get.py -v

DB에 질문·답변·꼬리질문을 직접 시드하고, GET /qna가 §4.4 형태(정렬·pending 파생·
evidence ts 포맷·status 매핑)로 직렬화하는지 검증한다. 파일 저장 없이 서명 URL만 파생.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.enums import (
    AnswerKind, AnswerStatus, AsyncStatus, EndedReason, FollowUpStatus,
    QuestionerPersona, QuestionStrategy, SessionStatus,
)
from app.db.models import Answer, Question, RehearsalSession, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "qget-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "qget-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    """qna 세션: Q1(답변 ready+꼬리 generated) → Q1.1(꼬리, 미답변) → Q2(tts queued, 미답변).
    current=Q1.1."""
    ids = {r: _mkuser(f"qget_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("qget_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen", "teto"], "question_count": 2,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("qget_owner")).json()["id"]
    with SessionLocal() as db:
        ses = db.get(RehearsalSession, sid)
        ses.status = SessionStatus.qna
        q1 = Question(session_id=sid, order_index=1, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.detail_probe, text="질문 1",
                      evidence={"slides": [3], "transcript_refs": [{"start": 252.0}]},
                      tts_status=AsyncStatus.ready, tts_storage_key="sessions/x/tts/q1.wav")
        q2 = Question(session_id=sid, order_index=2, persona=QuestionerPersona.kkondae,
                      strategy=QuestionStrategy.basic_concept, text="질문 2",
                      tts_status=AsyncStatus.queued)
        db.add_all([q1, q2])
        db.flush()
        child = Question(session_id=sid, parent_id=q1.id, order_index=1, follow_up_depth=1,
                         persona=QuestionerPersona.teto, strategy=QuestionStrategy.big_picture,
                         text="꼬리질문", tts_status=AsyncStatus.ready,
                         tts_storage_key="sessions/x/tts/c1.wav")
        db.add(child)
        db.flush()
        db.add(Answer(question_id=q1.id, kind=AnswerKind.answered, status=AnswerStatus.ready,
                      text="답변1", audio_storage_key="sessions/x/answers/q1.m4a",
                      follow_up_status=FollowUpStatus.generated))
        ses.current_question_id = child.id
        db.commit()
        qids = {"q1": q1.id, "q2": q2.id, "child": child.id}
    yield sid, qids, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("qget_%")))
        db.commit()


QNA = "/api/v1/sessions/{}/qna"
QDETAIL = "/api/v1/sessions/{}/qna/questions/{}"


class TestQnaShape:
    def test_top_level(self, ctx):
        sid, q, _ = ctx
        r = client.get(QNA.format(sid), headers=_auth("qget_owner"))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "in_progress"
        assert body["current_question_id"] == q["child"]
        assert body["ended_reason"] is None
        assert list(body.keys()) == ["status", "current_question_id", "ended_reason", "questions"]

    def test_ordering_parent_then_child(self, ctx):
        sid, q, _ = ctx
        qs = client.get(QNA.format(sid), headers=_auth("qget_owner")).json()["questions"]
        # order_index, follow_up_depth 순 → Q1(1,0) · 꼬리(1,1) · Q2(2,0)
        assert [x["id"] for x in qs] == [q["q1"], q["child"], q["q2"]]
        assert [(x["order"], x["follow_up_depth"]) for x in qs] == [(1, 0), (1, 1), (2, 0)]
        assert qs[1]["parent_id"] == q["q1"]

    def test_answered_question_fields(self, ctx):
        sid, q, _ = ctx
        qs = client.get(QNA.format(sid), headers=_auth("qget_owner")).json()["questions"]
        q1 = qs[0]
        assert q1["persona"] == "egen" and q1["strategy"] == "detail_probe"
        assert q1["parent_id"] is None
        assert q1["evidence"] == {"slides": [3], "transcript_refs": [{"ts": "04:12"}]}
        assert q1["tts"]["status"] == "ready"
        assert q1["tts"]["audio_url"].startswith("/api/v1/files/")
        ans = q1["answer"]
        assert ans["status"] == "ready"
        assert ans["text"] == "답변1"
        assert ans["audio_url"].startswith("/api/v1/files/")
        assert ans["follow_up_status"] == "generated"
        assert ans["error"] is None

    def test_pending_answer_via_row_absence(self, ctx):
        sid, q, _ = ctx
        qs = {x["id"]: x for x in client.get(QNA.format(sid), headers=_auth("qget_owner")).json()["questions"]}
        # 꼬리질문·Q2는 답변 row 없음 → status "pending"
        assert qs[q["child"]]["answer"]["status"] == "pending"
        assert qs[q["child"]]["answer"]["text"] is None
        assert qs[q["q2"]]["answer"]["status"] == "pending"

    def test_queued_tts_has_no_url(self, ctx):
        sid, q, _ = ctx
        qs = {x["id"]: x for x in client.get(QNA.format(sid), headers=_auth("qget_owner")).json()["questions"]}
        assert qs[q["q2"]]["tts"]["status"] == "queued"
        assert qs[q["q2"]]["tts"]["audio_url"] is None

    def test_failed_answer_error_populated(self, ctx):
        sid, q, _ = ctx
        with SessionLocal() as db:  # Q2에 실패 답변 추가
            db.add(Answer(question_id=q["q2"], kind=AnswerKind.answered,
                          status=AnswerStatus.failed, follow_up_status=FollowUpStatus.none,
                          error_code="STT_FAILED", error_message="STT 서버 오류"))
            db.commit()
        qs = {x["id"]: x for x in client.get(QNA.format(sid), headers=_auth("qget_owner")).json()["questions"]}
        ans = qs[q["q2"]]["answer"]
        assert ans["status"] == "failed"
        assert ans["error"] == {"code": "STT_FAILED", "message": "STT 서버 오류"}


class TestStatusMapping:
    def test_completed_maps_to_ended(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            ses = db.get(RehearsalSession, sid)
            ses.status = SessionStatus.completed
            ses.qna_ended_reason = EndedReason.user_end
            ses.current_question_id = None
            db.commit()
        body = client.get(QNA.format(sid), headers=_auth("qget_owner")).json()
        assert body["status"] == "ended"
        assert body["ended_reason"] == "user_end"

    def test_generating_questions_is_viewable(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.generating_questions
            db.commit()
        r = client.get(QNA.format(sid), headers=_auth("qget_owner"))
        assert r.status_code == 200
        assert r.json()["status"] == "in_progress"

    def test_before_generation_409(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.transcribing
            db.commit()
        r = client.get(QNA.format(sid), headers=_auth("qget_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QNA_NOT_STARTED"


class TestQuestionDetail:
    def test_get_single_question(self, ctx):
        sid, q, _ = ctx
        r = client.get(QDETAIL.format(sid, q["q1"]), headers=_auth("qget_owner"))
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == q["q1"]
        assert body["answer"]["text"] == "답변1"
        assert body["evidence"]["transcript_refs"] == [{"ts": "04:12"}]

    def test_unknown_question_404(self, ctx):
        sid, _, _ = ctx
        r = client.get(QDETAIL.format(sid, "q_nope"), headers=_auth("qget_owner"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "QUESTION_NOT_FOUND"


class TestPermissions:
    def test_member_can_view(self, ctx):
        sid, _, _ = ctx
        assert client.get(QNA.format(sid), headers=_auth("qget_member")).status_code == 200

    def test_outsider_404(self, ctx):
        sid, _, _ = ctx
        assert client.get(QNA.format(sid), headers=_auth("qget_outsider")).status_code == 404

    def test_requires_auth(self, ctx):
        sid, _, _ = ctx
        assert client.get(QNA.format(sid)).status_code == 401
