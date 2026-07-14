"""리포트 라우터 (Step 4, api-spec §5.2).

- GET  /sessions/{id}/report          : 단일 세션 리포트 (멤버) — reports+type_scores 조립
- POST /sessions/{id}/report/generate : 수동 재생성 접수 202 (owner). 기본은 qna/end 자동(A7)
- GET  /users/me/report/growth        : 내 성장 리포트 (본인 스코프, db-schema §8.1)

생성 로직 실체는 services/report_jobs.run_report — 여기는 접수·조립만 한다.
"""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_session_member, require_session_owner
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus, QuestionStrategy, SessionStatus
from app.db.session import get_db
from app.schemas.report import (
    AnswerQualityOut,
    FillerWordOut,
    GrowthPointOut,
    GrowthReportOut,
    ReportOut,
    SpeakingHabitsOut,
)
from app.schemas.session import ErrorInfo
from app.services import report_jobs

router = APIRouter(tags=["reports"])

# answer_quality 임계값 (§5.2 파생 — 저장 안 함). 스펙 예시(0.85/0.80 강 · 0.40/0.35 약)와
# 정합하는 보수적 경계: 사이(0.5~0.7)는 어느 쪽에도 넣지 않는다.
_STRONG_MIN = 0.7
_WEAK_MAX = 0.5

_STRATEGY_KO = {
    QuestionStrategy.detail_probe: "디테일 추궁형",
    QuestionStrategy.big_picture: "큰그림형",
    QuestionStrategy.basic_concept: "기초 개념형",
    QuestionStrategy.numeric_verification: "수치 검증형",
}


# ── 단일 세션 리포트 ──────────────────────────────────────────────────

@router.get(
    "/sessions/{session_id}/report",
    response_model=ReportOut,
    response_model_exclude_none=True,
)
def get_report(
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> ReportOut:
    """단일 세션 리포트 (멤버). ready 전에는 status(+error)만 — FE는 이걸로 폴링한다."""
    report = db.get(models.Report, session.id)
    if report is None:  # A7: 종료 전에는 리포트가 존재하지 않는다
        raise ApiError(404, "REPORT_NOT_FOUND",
                       "리포트가 아직 없어요. 질의응답을 끝내면 자동으로 만들어져요.")

    if report.status != AsyncStatus.ready:
        error = None
        if report.status == AsyncStatus.failed and report.error_code:
            error = ErrorInfo(code=report.error_code, message=report.error_message or "")
        return ReportOut(status=report.status, error=error)

    score_rows = db.scalars(
        select(models.ReportTypeScore)
        .where(models.ReportTypeScore.report_session_id == session.id)
    ).all()
    # 키 순서를 enum 정의 순으로 고정 — 응답 스냅샷 안정성
    present = {r.strategy: round(float(r.score), 2) for r in score_rows}
    type_scores = {s: present[s] for s in QuestionStrategy if s in present}

    habits = None
    if report.words_per_minute is not None:
        recording = db.get(models.Recording, session.id)
        habits = SpeakingHabitsOut(
            words_per_minute=report.words_per_minute,
            filler_words=[FillerWordOut(**f) for f in (report.filler_words or [])],
            time_limit_seconds=session.time_limit_minutes * 60,
            actual_seconds=recording.duration_seconds if recording is not None else 0,
        )

    return ReportOut(
        status=report.status,
        type_scores=type_scores,
        answer_quality=AnswerQualityOut(
            strong_types=[s for s, v in type_scores.items() if v >= _STRONG_MIN],
            weak_types=[s for s, v in type_scores.items() if v < _WEAK_MAX],
        ),
        speaking_habits=habits,
        insight=report.insight,
    )


@router.post("/sessions/{session_id}/report/generate", status_code=202)
def regenerate_report(
    background: BackgroundTasks,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> dict:
    """수동 재생성 접수 (owner) → 202. 실패 리포트의 '다시 생성' 버튼이 호출한다."""
    if session.status != SessionStatus.completed:
        raise ApiError(409, "SESSION_NOT_COMPLETED",
                       "질의응답이 끝난 뒤에 리포트를 만들 수 있어요.")

    report = db.get(models.Report, session.id)
    if report is None:
        db.add(models.Report(session_id=session.id, status=AsyncStatus.queued))
    else:
        report.status = AsyncStatus.queued
    db.commit()

    background.add_task(report_jobs.run_report, session.id)
    return {"status": AsyncStatus.queued.value}


# ── 성장 리포트 (유저 스코프, E) ──────────────────────────────────────

@router.get("/users/me/report/growth", response_model=GrowthReportOut)
def get_growth_report(
    range: Literal["all", "recent5"] = Query("all"),
    team_id: str | None = Query(None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GrowthReportOut:
    """내 완료 세션들의 전략별 점수 시계열 (db-schema §8.1). team_id는 선택 필터."""
    stmt = (
        select(models.RehearsalSession, models.ReportTypeScore)
        .join(models.Report,
              models.Report.session_id == models.RehearsalSession.id)
        .join(models.ReportTypeScore,
              models.ReportTypeScore.report_session_id == models.RehearsalSession.id)
        .where(
            models.RehearsalSession.owner_id == user.id,
            models.RehearsalSession.status == SessionStatus.completed,
            models.Report.status == AsyncStatus.ready,
        )
    )
    if team_id is not None:
        stmt = stmt.where(models.RehearsalSession.team_id == team_id)

    grouped: dict[str, GrowthPointOut] = {}
    order_key: dict[str, tuple] = {}
    for ses, rts in db.execute(stmt).all():
        point = grouped.get(ses.id)
        if point is None:
            when = ses.ended_at or ses.created_at
            point = GrowthPointOut(
                session_id=ses.id, name=ses.name,
                date=when.date().isoformat(), type_scores={},
            )
            grouped[ses.id] = point
            order_key[ses.id] = (when, ses.id)
        point.type_scores[rts.strategy] = round(float(rts.score), 2)

    series = sorted(grouped.values(), key=lambda p: order_key[p.session_id])
    if range == "recent5":
        series = series[-5:]  # 최근 5회, 표시 순서는 시간순 유지

    return GrowthReportOut(
        range=range, user_id=user.id, team_id=team_id,
        series=series, insight=_growth_insight(series),
    )


def _growth_insight(series: list[GrowthPointOut]) -> str | None:
    """회차 비교 결정론 템플릿 (report-eval-workflow 열린 질문 2 — LLM 없이 최소 구현).

    전략별 처음↔마지막 점수를 비교해 가장 오른 축을 짚고, 마지막 회차의 최저
    축(0.5 미만)을 보완점으로 덧붙인다. 비교할 회차(≥2)가 없으면 None."""
    if len(series) < 2:
        return None

    firsts: dict[QuestionStrategy, float] = {}
    lasts: dict[QuestionStrategy, float] = {}
    for point in series:
        for strategy, score in point.type_scores.items():
            firsts.setdefault(strategy, score)
            lasts[strategy] = score

    parts: list[str] = []
    deltas = {s: lasts[s] - firsts[s] for s in lasts}
    if deltas:
        best = max(deltas, key=lambda s: deltas[s])
        if deltas[best] >= 0.05:
            parts.append(f"{_STRATEGY_KO[best]} 점수가 오르고 있어요.")

    last_scores = series[-1].type_scores
    if last_scores:
        weakest = min(last_scores, key=lambda s: last_scores[s])
        if last_scores[weakest] < _WEAK_MAX:
            parts.append(f"{_STRATEGY_KO[weakest]}은 아직 준비가 필요해요.")

    return " ".join(parts) or None
