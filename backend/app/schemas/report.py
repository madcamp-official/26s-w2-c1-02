from pydantic import BaseModel, Field, field_validator

from app.db.enums import QuestionStrategy


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
