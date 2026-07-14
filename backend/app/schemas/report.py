from pydantic import BaseModel, Field, field_validator

from app.db.enums import AsyncStatus, QuestionStrategy
from app.schemas.session import ErrorInfo


class ReportDraft(BaseModel):
    """리포트 정성 평가 1건 — LLM 산출(report-eval-workflow.md §B).

    팀원2 라우터가 `type_scores` → report_type_scores 행들, `insight` → reports.insight로 저장.
    정량 지표(WPM·filler·over_time)는 services/report.py(§A)에서 별도 계산 — 여기 없음.
    """

    # 전략별 답변 점수 0.0~1.0 (성장 리포트의 원천, api-spec §5.2).
    # 답변이 등장한 전략만 포함(0개인 전략 키는 생략).
    type_scores: dict[QuestionStrategy, float] = Field(default_factory=dict)
    insight: str = ""

    @field_validator("type_scores")
    @classmethod
    def _clamp_scores(cls, v: dict[QuestionStrategy, float]) -> dict[QuestionStrategy, float]:
        # DDL CHECK(score BETWEEN 0 AND 1) 위반 방어 — 범위 밖 값은 잘라낸다.
        return {k: max(0.0, min(1.0, float(s))) for k, s in v.items()}


# ── 응답 (리포트 라우트, api-spec §5.2) ────────────────────────────────
# time_limit_seconds·actual_seconds·answer_quality는 저장 컬럼이 없고 서빙 시
# 파생(db-schema §5). over_time·filler_word_count는 클라이언트 파생이라 응답에 없음.


class FillerWordOut(BaseModel):
    word: str
    count: int


class SpeakingHabitsOut(BaseModel):
    """발표 습관 — 수치는 services/report.py(§A) 저장값 + sessions·recordings 파생."""

    words_per_minute: float
    filler_words: list[FillerWordOut]
    time_limit_seconds: int   # sessions.time_limit_minutes * 60
    actual_seconds: int       # recordings.duration_seconds


class AnswerQualityOut(BaseModel):
    """type_scores 임계값 분류 — 저장하지 않고 응답 시 파생 (§5.2)."""

    strong_types: list[QuestionStrategy]
    weak_types: list[QuestionStrategy]


class ReportOut(BaseModel):
    """GET /sessions/{id}/report 응답 (§5.2). ready 전에는 status(+error)만 채워진다."""

    status: AsyncStatus
    type_scores: dict[QuestionStrategy, float] | None = None
    answer_quality: AnswerQualityOut | None = None
    speaking_habits: SpeakingHabitsOut | None = None
    insight: str | None = None
    error: ErrorInfo | None = None   # failed 시 {code, message}


class GrowthPointOut(BaseModel):
    """성장 리포트 시리즈 1점 = 완료 세션 1개의 전략별 점수."""

    session_id: str
    name: str
    date: str                        # "YYYY-MM-DD" (ended_at 없으면 created_at)
    type_scores: dict[QuestionStrategy, float]


class GrowthReportOut(BaseModel):
    """GET /users/me/report/growth 응답 (§5.2, E: 유저 스코프)."""

    range: str
    user_id: str
    team_id: str | None = None
    series: list[GrowthPointOut]
    insight: str | None = None
