from pydantic import BaseModel, Field

from app.db.enums import QuestionerPersona, QuestionStrategy


class TranscriptRef(BaseModel):
    """전사 근거 1건. 저장은 초 단위 float(start), API 응답에서 ts:"MM:SS"로 포맷 (db-schema §6.3)."""

    start: float


class Evidence(BaseModel):
    """질문 근거 — questions.evidence JSONB와 1:1 (db-schema §6.3)."""

    slides: list[int] = Field(default_factory=list)          # materials.slides[].page 참조
    transcript_refs: list[TranscriptRef] = Field(default_factory=list)


class QuestionDraft(BaseModel):
    """LLM이 생성한 질문 1건의 내용. 팀원2 라우터가 id·order_index·tts를 붙여 questions 행으로 저장.

    api-spec §4.4 / db-schema §6.1·§6.3 계약. index/parent_id/order는 여기 없음(라우터 몫).
    """

    text: str
    persona: QuestionerPersona
    strategy: QuestionStrategy
    evidence: Evidence = Field(default_factory=Evidence)
    follow_up_depth: int = 0  # 0=1차 질문, 1=꼬리질문 (A11: ≤1)


class QnaItem(BaseModel):
    index: int  # 1-based (Q1, Q2 ...)
    question: str
    answer: str | None = None
    follow_up_depth: int = 0  # 꼬리물기 단계 (A11: 0|1)


class QnaAnswer(BaseModel):
    index: int
    answer: str
