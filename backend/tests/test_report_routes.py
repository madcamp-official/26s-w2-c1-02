"""리포트 라우트 회귀 테스트 (Step 4, api-spec §5.2).

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_report_routes.py -v

GET /report 응답 조립(파생 필드·상태별 형태), POST /report/generate 재생성 잡,
GET /users/me/report/growth 유저 스코프·range·team_id 필터를 검증한다.
LLM은 기본 mock 제공자(결정론) — GPU/키 없이 돈다.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.enums import (
    AnswerKind, AnswerStatus, AsyncStatus, QuestionerPersona, QuestionStrategy, SessionStatus,
)
from app.db.models import (
    Answer, Question, Recording, RehearsalSession, Report, ReportTypeScore,
    Team, TeamMember, Transcript, User,
)
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def _mkuser(u: str) -> str:
    r = client.post("/api/v1/auth/signup", json={"name": u, "username": u,
                    "password": "rept-pass-123", "email": f"{u}@t.io"})
    return r.json()["user"]["id"]


def _auth(u: str) -> dict:
    tok = client.post("/api/v1/auth/login", json={"username": u, "password": "rept-pass-123"},
                      headers={"X-Client-Platform": "ios"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _mksession(tid: str, who: str, name: str = "S") -> str:
    return client.post(f"/api/v1/teams/{tid}/sessions",
                       json={"name": name, "personas": ["egen"], "question_count": 2,
                             "time_limit_minutes": 10, "mode": "realtime"},
                       headers=_auth(who)).json()["id"]


@pytest.fixture()
def ctx():
    """completed 세션 1개 — 전사·녹음·답변된 질문 2개(전략 상이) 시드."""
    ids = {r: _mkuser(f"rept_{r}") for r in ("owner", "member", "outsider")}
    tid = client.post("/api/v1/teams", json={"name": "T"}, headers=_auth("rept_owner")).json()["id"]
    with SessionLocal() as db:
        db.add(TeamMember(team_id=tid, user_id=ids["member"]))
        db.commit()
    sid = _mksession(tid, "rept_owner")
    with SessionLocal() as db:
        ses = db.get(RehearsalSession, sid)
        ses.status = SessionStatus.completed
        db.add(Transcript(session_id=sid, status=AsyncStatus.ready, segments=[
            {"start": 0.0, "end": 5.0, "text": "음 안녕하세요 어 발표를 시작합니다"},
        ]))
        db.add(Recording(session_id=sid, status=AsyncStatus.ready, file_name="rec.m4a",
                         file_size_bytes=1, mime_type="audio/mp4", duration_seconds=663,
                         storage_key=f"sessions/{sid}/recording.m4a"))
        q1 = Question(session_id=sid, order_index=1, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.detail_probe, text="질문 1",
                      tts_status=AsyncStatus.ready)
        q2 = Question(session_id=sid, order_index=2, persona=QuestionerPersona.egen,
                      strategy=QuestionStrategy.big_picture, text="질문 2",
                      tts_status=AsyncStatus.ready)
        db.add_all([q1, q2])
        db.flush()
        db.add(Answer(question_id=q1.id, kind=AnswerKind.answered, status=AnswerStatus.ready,
                      text="구체적인 수치 근거를 들어 설명한 답변입니다"))
        db.add(Answer(question_id=q2.id, kind=AnswerKind.answered, status=AnswerStatus.ready,
                      text="전체 맥락과 연결해 설명한 답변입니다"))
        db.commit()
    yield sid, tid, ids
    with SessionLocal() as db:
        db.execute(delete(Team).where(Team.id == tid))
        db.execute(delete(User).where(User.username.ilike("rept_%")))
        db.commit()


def _seed_ready_report(sid: str, scores: dict[QuestionStrategy, float] | None = None) -> None:
    """라우트 조립 검증용 — 잡을 거치지 않고 reports+type_scores를 직접 시드."""
    with SessionLocal() as db:
        db.add(Report(session_id=sid, status=AsyncStatus.ready, words_per_minute=182.0,
                      filler_words=[{"word": "음", "count": 9}, {"word": "어", "count": 5}],
                      insight="필러 워드가 도입부에 몰려 있어요."))
        for s, v in (scores or {
            QuestionStrategy.detail_probe: 0.40,
            QuestionStrategy.big_picture: 0.85,
            QuestionStrategy.basic_concept: 0.80,
            QuestionStrategy.numeric_verification: 0.35,
        }).items():
            db.add(ReportTypeScore(report_session_id=sid, strategy=s, score=v))
        db.commit()


REPORT = "/api/v1/sessions/{}/report"
GENERATE = "/api/v1/sessions/{}/report/generate"
GROWTH = "/api/v1/users/me/report/growth"


class TestGetReport:
    def test_ready_shape_matches_spec(self, ctx):
        """§5.2 응답 예시와 필드 단위 일치 — 파생값(임계값 분류·초 환산) 포함."""
        sid, _, _ = ctx
        _seed_ready_report(sid)
        r = client.get(REPORT.format(sid), headers=_auth("rept_owner"))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["type_scores"] == {"detail_probe": 0.40, "big_picture": 0.85,
                                       "basic_concept": 0.80, "numeric_verification": 0.35}
        # 강 ≥0.7 · 약 <0.5 (응답 시 파생, 저장 안 함)
        assert body["answer_quality"] == {"strong_types": ["big_picture", "basic_concept"],
                                          "weak_types": ["detail_probe", "numeric_verification"]}
        assert body["speaking_habits"] == {
            "words_per_minute": 182.0,
            "filler_words": [{"word": "음", "count": 9}, {"word": "어", "count": 5}],
            "time_limit_seconds": 600,   # sessions.time_limit_minutes * 60
            "actual_seconds": 663,       # recordings.duration_seconds
        }
        assert body["insight"]
        assert "error" not in body       # exclude_none
        assert "over_time" not in body["speaking_habits"]  # 클라이언트 파생(§5.2)

    def test_member_can_view(self, ctx):
        sid, _, _ = ctx
        _seed_ready_report(sid)
        assert client.get(REPORT.format(sid), headers=_auth("rept_member")).status_code == 200

    def test_outsider_404(self, ctx):
        sid, _, _ = ctx
        _seed_ready_report(sid)
        r = client.get(REPORT.format(sid), headers=_auth("rept_outsider"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_no_report_yet_404(self, ctx):
        sid, _, _ = ctx
        r = client.get(REPORT.format(sid), headers=_auth("rept_owner"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "REPORT_NOT_FOUND"

    def test_processing_returns_status_only(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.add(Report(session_id=sid, status=AsyncStatus.processing))
            db.commit()
        body = client.get(REPORT.format(sid), headers=_auth("rept_owner")).json()
        assert body == {"status": "processing"}

    def test_failed_includes_error(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.add(Report(session_id=sid, status=AsyncStatus.failed,
                          error_code="GENERATION_FAILED", error_message="LLM 오류"))
            db.commit()
        body = client.get(REPORT.format(sid), headers=_auth("rept_owner")).json()
        assert body == {"status": "failed",
                        "error": {"code": "GENERATION_FAILED", "message": "LLM 오류"}}


class TestGenerate:
    def test_generate_builds_ready_report(self, ctx):
        """202 접수 → (TestClient는 백그라운드 잡을 응답 직후 실행) → ready 리포트."""
        sid, _, _ = ctx
        r = client.post(GENERATE.format(sid), headers=_auth("rept_owner"))
        assert r.status_code == 202
        assert r.json() == {"status": "queued"}

        body = client.get(REPORT.format(sid), headers=_auth("rept_owner")).json()
        assert body["status"] == "ready"
        # 정량(A): 전사 5어절 중 필러 2(음·어) 제외 3어절 / (663s/60분) → 0.3wpm
        assert body["speaking_habits"]["words_per_minute"] == pytest.approx(0.3)
        assert {f["word"] for f in body["speaking_habits"]["filler_words"]} == {"음", "어"}
        # 정성(B): 답변이 등장한 전략만, 값은 [0,1] (mock 결정론 — 값 자체는 계약 아님)
        assert set(body["type_scores"]) == {"detail_probe", "big_picture"}
        assert all(0.0 <= v <= 1.0 for v in body["type_scores"].values())
        assert body["insight"]

    def test_regenerate_replaces_scores(self, ctx):
        """재생성 시 report_type_scores 전량 교체 — PK 충돌 없이 두 번 돌아야 한다."""
        sid, _, _ = ctx
        assert client.post(GENERATE.format(sid), headers=_auth("rept_owner")).status_code == 202
        assert client.post(GENERATE.format(sid), headers=_auth("rept_owner")).status_code == 202
        body = client.get(REPORT.format(sid), headers=_auth("rept_owner")).json()
        assert body["status"] == "ready"
        assert set(body["type_scores"]) == {"detail_probe", "big_picture"}

    def test_member_not_owner_403(self, ctx):
        sid, _, _ = ctx
        r = client.post(GENERATE.format(sid), headers=_auth("rept_member"))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN_NOT_OWNER"

    def test_not_completed_409(self, ctx):
        sid, _, _ = ctx
        with SessionLocal() as db:
            db.get(RehearsalSession, sid).status = SessionStatus.qna
            db.commit()
        r = client.post(GENERATE.format(sid), headers=_auth("rept_owner"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SESSION_NOT_COMPLETED"


def _seed_completed_with_score(tid: str, who: str, name: str, day: int,
                               strategy: QuestionStrategy, score: float,
                               report_status: AsyncStatus = AsyncStatus.ready) -> str:
    """완료 세션 + ready 리포트 + 점수 1건. day로 ended_at 순서를 고정한다."""
    sid = _mksession(tid, who, name=name)
    with SessionLocal() as db:
        ses = db.get(RehearsalSession, sid)
        ses.status = SessionStatus.completed
        ses.ended_at = datetime(2026, 7, day, 12, 0, tzinfo=timezone.utc)
        db.add(Report(session_id=sid, status=report_status))
        if report_status == AsyncStatus.ready:
            db.add(ReportTypeScore(report_session_id=sid, strategy=strategy, score=score))
        db.commit()
    return sid


class TestGrowth:
    def test_series_user_scoped_and_ordered(self, ctx):
        """내(owner) 완료 세션만, ended_at 오름차순 — 멤버 세션은 섞이지 않는다(E)."""
        _, tid, _ = ctx
        s1 = _seed_completed_with_score(tid, "rept_owner", "1차 발표", 8,
                                        QuestionStrategy.detail_probe, 0.40)
        s2 = _seed_completed_with_score(tid, "rept_owner", "2차 발표", 9,
                                        QuestionStrategy.detail_probe, 0.62)
        _seed_completed_with_score(tid, "rept_member", "남의 발표", 8,
                                   QuestionStrategy.detail_probe, 0.99)

        body = client.get(GROWTH, headers=_auth("rept_owner")).json()
        assert body["range"] == "all"
        assert body["team_id"] is None
        assert [p["session_id"] for p in body["series"]] == [s1, s2]
        assert body["series"][0] == {"session_id": s1, "name": "1차 발표", "date": "2026-07-08",
                                     "type_scores": {"detail_probe": 0.40}}
        # 결정론 템플릿 인사이트 — 최다 상승 축 + 마지막 회차 0.5 미만 없음 → 한 문장
        assert body["insight"] == "디테일 추궁형 점수가 오르고 있어요."

    def test_not_ready_report_excluded(self, ctx):
        _, tid, _ = ctx
        _seed_completed_with_score(tid, "rept_owner", "실패 발표", 8,
                                   QuestionStrategy.detail_probe, 0.4,
                                   report_status=AsyncStatus.failed)
        body = client.get(GROWTH, headers=_auth("rept_owner")).json()
        assert body["series"] == []
        assert body["insight"] is None   # 회차 <2 → 인사이트 없음

    def test_recent5_takes_latest_five(self, ctx):
        _, tid, _ = ctx
        sids = [_seed_completed_with_score(tid, "rept_owner", f"{d}차", d,
                                           QuestionStrategy.big_picture, 0.5 + d / 100)
                for d in range(1, 7)]                      # 6회
        body = client.get(GROWTH, params={"range": "recent5"},
                          headers=_auth("rept_owner")).json()
        assert body["range"] == "recent5"
        assert [p["session_id"] for p in body["series"]] == sids[1:]  # 최근 5회, 시간순

    def test_team_filter(self, ctx):
        _, tid, ids = ctx
        other_tid = client.post("/api/v1/teams", json={"name": "T2"},
                                headers=_auth("rept_owner")).json()["id"]
        try:
            s_in = _seed_completed_with_score(tid, "rept_owner", "팀1", 8,
                                              QuestionStrategy.basic_concept, 0.8)
            _seed_completed_with_score(other_tid, "rept_owner", "팀2", 9,
                                       QuestionStrategy.basic_concept, 0.9)
            body = client.get(GROWTH, params={"team_id": tid},
                              headers=_auth("rept_owner")).json()
            assert body["team_id"] == tid
            assert [p["session_id"] for p in body["series"]] == [s_in]
        finally:  # ctx 티어다운은 tid만 지운다 — 두 번째 팀은 여기서 정리
            with SessionLocal() as db:
                db.execute(delete(Team).where(Team.id == other_tid))
                db.commit()

    def test_requires_auth(self, ctx):
        assert client.get(GROWTH).status_code == 401
