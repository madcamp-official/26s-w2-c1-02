"""리포트 생성 잡 (Step 4, api-spec §5.2 · A7).

`run_report(session_id)` — 세션 종료(사용자/자동)·수동 재생성에서 트리거된다.
두 반쪽을 조립한다(report-eval-workflow.md 핵심 원칙: 숫자는 코드, 판단은 LLM):

- A. 정량: `compute_speaking_metrics()` → reports.words_per_minute · filler_words
- B. 정성: `LLMProvider.generate_report()` → report_type_scores 행들 · reports.insight

qna_jobs와 같은 규칙 — 자기 DB 세션(SessionLocal)을 열고 예외를 밖으로 던지지
않는다(전부 reports.failed로 흡수 → FE 폴링이 '다시 생성' UX로 회복).
"""

import asyncio
import logging
import threading

from sqlalchemy import delete, select

from app.db import models
from app.db.enums import AnswerKind, AnswerStatus, AsyncStatus
from app.db.session import SessionLocal
from app.services.llm.factory import get_llm_provider
from app.services.report import compute_speaking_metrics

logger = logging.getLogger("rehearsal.report_jobs")


def run_report(session_id: str) -> None:
    """세션 1개의 리포트를 생성해 reports·report_type_scores에 저장한다.

    재생성이면 기존 값을 덮어쓴다(점수 행은 전량 교체). 실패는 failed로 흡수."""
    with SessionLocal() as db:
        session = db.get(models.RehearsalSession, session_id)
        if session is None:  # 접수 후 세션이 삭제된 경우
            return
        report = db.get(models.Report, session_id)
        if report is None:  # 트리거가 큐 마커를 못 만든 경로 방어 (구 세션 수동 재생성 등)
            report = models.Report(session_id=session_id, status=AsyncStatus.processing)
            db.add(report)
        else:
            report.status = AsyncStatus.processing
        db.commit()

        try:
            _generate(db, session, report)
        except Exception as e:
            logger.exception("리포트 생성 실패: %s", session_id)
            report.status = AsyncStatus.failed
            report.error_code = "GENERATION_FAILED"
            report.error_message = str(e)[:500]
            db.commit()


def _generate(db, session: models.RehearsalSession, report: models.Report) -> None:
    # A. 정량 — 원문 transcript + 녹음 길이(권위값). 없으면 빈 지표로 계산(0 WPM).
    transcript = db.get(models.Transcript, session.id)
    recording = db.get(models.Recording, session.id)
    segments = transcript.segments if transcript is not None and transcript.segments else []
    duration = float(recording.duration_seconds) if recording is not None else 0.0
    metrics = compute_speaking_metrics(segments, duration, session.time_limit_minutes)

    # B. 정성 — 답변된 질문만 채점(패스·STT 실패 제외). base.py 계약:
    # answers = [{"strategy", "question", "answer"}], 전략별 평균은 build_type_scores 몫.
    rows = db.execute(
        select(models.Question, models.Answer)
        .join(models.Answer, models.Answer.question_id == models.Question.id)
        .where(
            models.Question.session_id == session.id,
            models.Answer.kind == AnswerKind.answered,
            models.Answer.status == AnswerStatus.ready,
        )
        .order_by(models.Question.order_index, models.Question.follow_up_depth)
    ).all()
    answers = [
        {"strategy": q.strategy, "question": q.text, "answer": a.text or ""}
        for q, a in rows
        if (a.text or "").strip()
    ]
    provider = get_llm_provider()
    draft = asyncio.run(provider.generate_report(answers=answers, speech_name=session.name))

    # 저장 — 재생성 대비 점수 행 전량 교체 (PK 충돌 방지)
    db.execute(
        delete(models.ReportTypeScore)
        .where(models.ReportTypeScore.report_session_id == session.id)
    )
    for strategy, score in draft.type_scores.items():
        db.add(models.ReportTypeScore(
            report_session_id=session.id, strategy=strategy, score=score,
        ))
    report.words_per_minute = metrics["words_per_minute"]
    report.filler_words = metrics["filler_words"]
    report.insight = draft.insight
    report.status = AsyncStatus.ready
    report.error_code = None
    report.error_message = None
    db.commit()


def recover() -> None:
    """서버 재시작으로 유실된 리포트 잡 복구 (stt_queue.recover와 동일 성격).

    queued(잡 실행 전 죽음)·processing(실행 중 죽음) 리포트를 데몬 스레드에서
    순차 재실행한다 — 안 하면 FE 폴링이 영원히 대기."""
    with SessionLocal() as db:
        ids = db.scalars(
            select(models.Report.session_id).where(
                models.Report.status.in_([AsyncStatus.queued, AsyncStatus.processing])
            )
        ).all()
    if not ids:
        return
    logger.info("미완료 리포트 %d건 복구", len(ids))

    def _run_all() -> None:
        for sid in ids:
            run_report(sid)

    threading.Thread(target=_run_all, name="report-recover", daemon=True).start()
