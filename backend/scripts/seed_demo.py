"""데모 시드 — 로컬 구동 확인·시연용 계정/데이터 (workflow Step 5 "시드/데모 계정").

실행:
    cd backend
    .venv/bin/python -m scripts.seed_demo

만드는 것 (재실행 시 기존 데모 데이터를 지우고 다시 만든다 — 멱등):
- 계정  demo / demo-pass-1234  (FE 로그인 화면에서 그대로 사용)
- 팀    "말꼬리 스터디" (demo가 팀장)
- 완료 세션 3개 — ready 리포트 + 회차별 상승 점수(성장 리포트 시연용)
- 완료 세션 1개 — failed 리포트 ("다시 생성" 버튼 → 리포트 잡 라이브 시연용.
  전사·답변이 시드돼 있어 LLM_PROVIDER=mock으로도 실제 잡이 돈다)

GPU 서버(STT/TTS) 없이도 리포트 화면·성장 리포트를 바로 볼 수 있게
파이프라인 산출물(전사·답변·점수)을 직접 심는다. 오디오 파일은 없다(재생 버튼 제외).
"""

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db import models
from app.db.enums import (
    AnswerKind, AnswerStatus, AsyncStatus, EndedReason, QuestionerPersona,
    QuestionStrategy, SessionMode, SessionStatus,
)
from app.db.session import SessionLocal

USERNAME = "demo"
PASSWORD = "demo-pass-1234"

# 회차별 전략 점수 — 성장 리포트에서 상승 곡선이 보이게 (§5.2 예시값 기반)
SESSIONS = [
    ("1차 발표 — 아이디어 피칭", 8,
     {QuestionStrategy.detail_probe: 0.40, QuestionStrategy.big_picture: 0.55,
      QuestionStrategy.basic_concept: 0.60, QuestionStrategy.numeric_verification: 0.35},
     171.0, [{"word": "음", "count": 9}, {"word": "어", "count": 5}],
     "필러 워드가 도입부에 몰려 있어요. 첫 1분 대본을 미리 정해두면 좋아요."),
    ("2차 발표 — 중간 점검", 11,
     {QuestionStrategy.detail_probe: 0.62, QuestionStrategy.big_picture: 0.70,
      QuestionStrategy.basic_concept: 0.72, QuestionStrategy.numeric_verification: 0.45},
     158.0, [{"word": "음", "count": 4}, {"word": "어", "count": 3}],
     "근거 수치를 묻는 질문에서 답이 짧아져요. 핵심 숫자 3개를 미리 외워두세요."),
    ("3차 발표 — 최종 리허설", 13,
     {QuestionStrategy.detail_probe: 0.75, QuestionStrategy.big_picture: 0.85,
      QuestionStrategy.basic_concept: 0.80, QuestionStrategy.numeric_verification: 0.58},
     149.0, [{"word": "음", "count": 2}],
     "발화 속도가 안정됐어요. 수치 검증형 답변에 출처를 붙이면 완성도가 올라가요."),
]

TRANSCRIPT = [
    {"start": 0.0, "end": 6.5, "text": "음 안녕하세요 오늘 발표를 맡은 데모입니다"},
    {"start": 6.5, "end": 14.0, "text": "저희 서비스는 발표 연습을 어 AI 질의응답으로 도와주는 도구입니다"},
    {"start": 14.0, "end": 21.0, "text": "핵심 지표는 주간 활성 사용자 천 명을 목표로 하고 있습니다"},
]

QNA = [
    (QuestionerPersona.kkondae, QuestionStrategy.detail_probe,
     "주간 활성 사용자 천 명이라는 목표의 산출 근거가 뭔가요?",
     "초기 베타 테스터 백 명의 재방문율 사십 퍼센트를 기준으로 잡았습니다"),
    (QuestionerPersona.teto, QuestionStrategy.big_picture,
     "이 서비스가 기존 발표 코칭 시장과 다른 지점은 어디라고 보나요?",
     "사람 코치 없이 질의응답 리허설까지 자동화한 것이 가장 큰 차별점입니다"),
]


def main() -> None:
    with SessionLocal() as db:
        # 멱등: 이전 데모 데이터 제거 (팀 삭제가 세션·리포트까지 cascade)
        old = db.scalar(select(models.User).where(models.User.username == USERNAME))
        if old is not None:
            db.execute(delete(models.Team).where(models.Team.leader_id == old.id))
            db.execute(delete(models.User).where(models.User.id == old.id))
            db.commit()

        user = models.User(username=USERNAME, name="데모 발표자",
                           email="demo@rehearsal.io",
                           password_hash=hash_password(PASSWORD),
                           # demo@rehearsal.io는 실재하지 않는 주소라 코드 수신 불가 —
                           # 로그인 차단(403)에 안 걸리게 생성 시점에 인증 처리 (plan §7-2)
                           email_verified_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        team = models.Team(name="말꼬리 스터디", leader_id=user.id)
        db.add(team)
        db.flush()
        db.add(models.TeamMember(team_id=team.id, user_id=user.id))

        for name, day, scores, wpm, fillers, insight in SESSIONS:
            sid = _completed_session(db, team.id, user.id, name, day)
            db.add(models.Report(session_id=sid, status=AsyncStatus.ready,
                                 words_per_minute=wpm, filler_words=fillers,
                                 insight=insight))
            for strategy, score in scores.items():
                db.add(models.ReportTypeScore(report_session_id=sid,
                                              strategy=strategy, score=score))

        # failed 리포트 세션 — FE "다시 생성" → POST /report/generate 라이브 시연
        sid = _completed_session(db, team.id, user.id, "4차 발표 — 리포트 재생성 데모", 14)
        db.add(models.Report(session_id=sid, status=AsyncStatus.failed,
                             error_code="GENERATION_FAILED",
                             error_message="시연용 실패 상태 — '다시 생성'을 눌러보세요"))
        db.commit()

    print(f"시드 완료 — 로그인: {USERNAME} / {PASSWORD}")


def _completed_session(db, team_id: str, owner_id: str, name: str, day: int) -> str:
    """완료 세션 1개 + 전사·녹음·답변된 Q&A 시드 (리포트 잡 재실행 가능 상태)."""
    when = datetime(2026, 7, day, 14, 0, tzinfo=timezone.utc)
    ses = models.RehearsalSession(
        team_id=team_id, owner_id=owner_id, name=name,
        status=SessionStatus.completed, mode=SessionMode.upload,
        personas=[QuestionerPersona.kkondae, QuestionerPersona.teto],
        question_count=len(QNA), time_limit_minutes=10,
        qna_ended_reason=EndedReason.user_end, ended_at=when,
    )
    db.add(ses)
    db.flush()
    db.add(models.Transcript(session_id=ses.id, status=AsyncStatus.ready,
                             segments=TRANSCRIPT))
    db.add(models.Recording(session_id=ses.id, status=AsyncStatus.ready,
                            file_name="demo.m4a", file_size_bytes=1,
                            mime_type="audio/mp4", duration_seconds=612,
                            storage_key=f"sessions/{ses.id}/recording.m4a"))
    for i, (persona, strategy, q_text, a_text) in enumerate(QNA, start=1):
        q = models.Question(session_id=ses.id, order_index=i, persona=persona,
                            strategy=strategy, text=q_text,
                            tts_status=AsyncStatus.failed,  # 오디오 없음(시연 범위 밖)
                            tts_error_code="TTS_FAILED",
                            tts_error_message="시드 데이터 — 음성 없음")
        db.add(q)
        db.flush()
        db.add(models.Answer(question_id=q.id, kind=AnswerKind.answered,
                             status=AnswerStatus.ready, text=a_text,
                             duration_seconds=25))
    return ses.id


if __name__ == "__main__":
    main()
