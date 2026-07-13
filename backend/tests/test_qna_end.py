"""질의응답 사용자 종료 회귀 테스트 (Step 3 작업 5-2, api-spec §4.4·A12).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_end.py -v

POST /qna/end가 세션을 completed로 종료(ended_reason=user_end)하고 리포트를 큐에
올리는지, 종료 후 GET /qna가 ended로 보이고 답변이 막히는지 검증한다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.enums import AsyncStatus, QuestionerPersona, QuestionStrategy, SessionStatus
from app.db.models import Question, RehearsalSession, Report, Team, TeamMember, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "qend-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "qend-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def ctx():
    """qna 세션 + 1차 질문 2개, current=Q1 (아직 답 안 한 중간 종료 시나리오)."""
    ids = {r: _mkuser(f"qend_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("qend_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = client.post(f"/api/v1/teams/{tid}/sessions",
                      json={"name": "S", "personas": ["egen"], "question_count": 2,
                            "time_limit_minutes": 10, "mode": "realtime"},
                      headers=_auth("qend_owner")).json()["id"]
    with SessionLocal() as db:
        ses = db.get(RehearsalSession, sid)
        ses.status = SessionStatus.qna
        q1 = Question(session_id=sid, order_index=1, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.detail_probe, text="질문 1", tts_status=AsyncStatus.ready)
        q2 = Question(session_id=sid, order_index=2, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.big_picture, text="질문 2", tts_status=AsyncStatus.ready)
        db.add_all([q1, q2])
        db.flush()
        ses.current_question_id = q1.id
        db.commit()
        qids = {"q1": q1.id, "q2": q2.id}
    yield sid, qids, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("qend_%")))
        db.commit()


END = "/api/v1/sessions/{}/qna/end"
QNA = "/api/v1/sessions/{}/qna"
ANS = "/api/v1/sessions/{}/qna/questions/{}/answer"


def _session(sid):
    with SessionLocal() as db:
        return db.get(RehearsalSession, sid)


class TestEndSuccess:
    def test_end_completes_with_user_end(self, ctx):
        sid, _, _ = ctx
        r = client.post(END.format(sid), headers=_auth("qend_owner"))
        assert r.status_code == 200
        assert r.json() == {"status": "completed", "ended_reason": "user_end"}
        ses = _session(sid)
        assert ses.status == "completed"
        assert ses.qna_ended_reason == "user_end"       # A12: 사용자 종료 최우선
        assert ses.current_question_id is None

    def test_report_queued_on_end(self, ctx):
        sid, _, _ = ctx
        client.post(END.format(sid), headers=_auth("qend_owner"))
        with SessionLocal() as db:
            report = db.get(Report, sid)
            assert report is not None and report.status == "queued"  # 리포트 잡 트리거(Step 4)


class TestEndIntegration:
    def test_qna_shows_ended_after_end(self, ctx):
        sid, _, _ = ctx
        client.post(END.format(sid), headers=_auth("qend_owner"))
        body = client.get(QNA.format(sid), headers=_auth("qend_owner")).json()
        assert body["status"] == "ended"
        assert body["ended_reason"] == "user_end"

    def test_answer_blocked_after_end(self, ctx):
        sid, q, _ = ctx
        client.post(END.format(sid), headers=_auth("qend_owner"))
        r = client.post(ANS.format(sid, q["q1"]), files={"file": ("a.m4a", b"x", "audio/mp4")},
                        data={"duration_seconds": "10"}, headers=_auth("qend_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QNA_NOT_ACTIVE"


class TestEndGuards:
    def test_end_when_not_qna_409(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.transcribing
            db.commit()
        r = client.post(END.format(sid), headers=_auth("qend_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "QNA_NOT_ACTIVE"

    def test_end_twice_second_409(self, ctx):
        sid, _, _ = ctx
        assert client.post(END.format(sid), headers=_auth("qend_owner")).status_code == 200
        assert client.post(END.format(sid), headers=_auth("qend_owner")).status_code == 409

    def test_member_not_owner_403(self, ctx):
        sid, _, _ = ctx
        assert client.post(END.format(sid), headers=_auth("qend_member")).status_code == 403

    def test_outsider_404(self, ctx):
        sid, _, _ = ctx
        assert client.post(END.format(sid), headers=_auth("qend_outsider")).status_code == 404

    def test_requires_auth(self, ctx):
        sid, _, _ = ctx
        assert client.post(END.format(sid)).status_code == 401
