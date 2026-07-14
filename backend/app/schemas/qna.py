"""Q&A 스키마 (Step 3, api-spec §4.4 · db-schema §3.5·§6.3).

두 축:
- LLM 계약: `QuestionDraft`/`Evidence`/`TranscriptRef` — 팀원3의 generate_questions·follow_up
  반환형. 팀원2 라우터가 id·order_index·tts를 붙여 questions 행으로 저장한다.
- FE 응답 계약: `QnaStateOut`/`QuestionOut`/... — `GET /qna` 폴링 응답. api-spec §4.4 예시와
  필드 단위로 일치시킨다(팀원1 폴링이 의존). 저장은 초 float, 응답은 ts:"MM:SS"로 포맷.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.db.enums import (
    AsyncStatus,
    EndedReason,
    FollowUpStatus,
    QuestionerPersona,
    QuestionStrategy,
)
from app.schemas.session import ErrorInfo


class QnaStatus(StrEnum):
    """Q&A 진행 상태 (api-spec §6.1). DB enum이 아니라 sessions.status에서 파생 (db-schema §5)."""

    in_progress = "in_progress"
    ended = "ended"
    failed = "failed"        # 질문 생성 실패(session.failed) — 재생성으로 복구


# ── LLM 계약 (generate_questions·follow_up 반환형) ────────────────────

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


# ── FE 응답 계약 (GET /qna 폴링) ──────────────────────────────────────

class TranscriptRefOut(BaseModel):
    """전사 근거 (응답용) — 저장은 초 float(start), 응답은 ts:"MM:SS" (§4.4·db-schema §6.3)."""

    ts: str                               # "04:12" (seconds_to_ts 파생)


class EvidenceOut(BaseModel):
    """질문 근거 (응답용) — transcript_refs의 초 float를 ts:"MM:SS"로 포맷 (§4.4)."""

    slides: list[int] = Field(default_factory=list)
    transcript_refs: list[TranscriptRefOut] = Field(default_factory=list)


class TtsOut(BaseModel):
    """질문 음성 상태 + 서명 URL (§4.4)."""

    status: AsyncStatus
    audio_url: str | None = None          # tts_storage_key → signed_url 파생


class AnswerOut(BaseModel):
    """답변 상태 (§4.4). 출력 전용 — status는 문자열로 서빙한다.

    api-spec의 pending|processing|ready|failed 중 **pending은 answers row 부재로 파생**
    (db-schema §5, DB enum엔 없음)이라, 라우터가 문자열로 채운다. 유니온 대신 str로 두어
    스마트 유니온 모호성·enum 강제 실패를 원천 차단한다."""

    status: str                           # pending | processing | ready | failed
    text: str | None = None
    audio_url: str | None = None
    follow_up_status: FollowUpStatus = FollowUpStatus.none
    error: ErrorInfo | None = None


class QuestionOut(BaseModel):
    """질문 1건 (§4.4 questions[] 원소)."""

    id: str
    order: int
    persona: QuestionerPersona
    strategy: QuestionStrategy
    parent_id: str | None = None
    follow_up_depth: int
    text: str
    evidence: EvidenceOut
    tts: TtsOut
    answer: AnswerOut


class QnaStateOut(BaseModel):
    """GET /qna 응답 — 폴링 단일 소스 (§4.4)."""

    status: QnaStatus                     # sessions.status 파생 (qna→in_progress, completed→ended)
    current_question_id: str | None = None
    ended_reason: EndedReason | None = None
    questions: list[QuestionOut] = Field(default_factory=list)


# ── 요청 ──────────────────────────────────────────────────────────────

class PassRequest(BaseModel):
    """POST .../pass 선택 바디 (§4.4 v0.4-draft). 마지막 질문의 종료 사유 판정에 사용."""

    reason: Literal["user", "timeout"] = "user"
