"""발표 세션 스키마 (작업 2-1, api-spec §4.1 · db-schema §3.3).

요청/응답 형태는 api-spec §4.1 예시와 필드 단위로 일치시킨다 (팀원1 폴링이 의존).
파생 값(audio_url·slide_count)은 라우터(작업 2-2)가 ORM에서 채운다 — 여기선 형태만.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import AsyncStatus, QuestionerPersona, SessionMode, SessionStatus


# ── 요청 ──────────────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    """POST /teams/{teamId}/sessions — 발표 설정 (api-spec §4.1)."""

    # 알 수 없는 필드는 거부(422) — FE 계약의 오타(question_cont 등)를 조용히 삼키지 않는다.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    personas: list[QuestionerPersona] = Field(min_length=1)  # 중복 선택(≥1)
    question_count: int = Field(ge=1, le=20)                  # 1차 질문 수만 (§4.1)
    time_limit_minutes: int = Field(ge=1, le=120)
    mode: SessionMode = SessionMode.realtime

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("personas", mode="after")
    @classmethod
    def _dedupe_personas(cls, v: list[QuestionerPersona]) -> list[QuestionerPersona]:
        """중복 제거(순서 보존). 협의사항(6): 저장은 중복 없는 집합, 질의 수에 걸친
        페르소나 배분은 Step 3 질문 생성에서 처리."""
        seen: dict[QuestionerPersona, None] = {}
        for p in v:
            seen.setdefault(p, None)
        return list(seen)


class SessionUpdateRequest(BaseModel):
    """PATCH /sessions/{id} — draft 상태에서만. 모든 필드 선택적(부분 수정)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=50)
    personas: list[QuestionerPersona] | None = Field(default=None, min_length=1)
    question_count: int | None = Field(default=None, ge=1, le=20)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=120)
    mode: SessionMode | None = None

    _strip_name = field_validator("name", mode="before")(
        lambda v: v.strip() if isinstance(v, str) else v
    )

    @field_validator("personas", mode="after")
    @classmethod
    def _dedupe(cls, v):
        if v is None:
            return v
        seen: dict = {}
        for p in v:
            seen.setdefault(p, None)
        return list(seen)


# ── 하위 리소스 상태 (세션 상세에 중첩) ───────────────────────────────

class MaterialStatusOut(BaseModel):
    status: AsyncStatus
    slide_count: int | None = None   # ready 시 페이지 수


class ErrorInfo(BaseModel):
    code: str
    message: str


class MaterialDetail(BaseModel):
    """GET /sessions/{id}/material 응답 (api-spec §4.2)."""

    status: AsyncStatus
    progress: float
    file_name: str
    page_count: int | None = None
    slides: list | None = None       # ready 시 [{"page":1,"text":"..."}]
    error: ErrorInfo | None = None   # failed 시 {code, message}


class RecordingStatusOut(BaseModel):
    status: AsyncStatus
    duration_seconds: int | None = None
    audio_url: str | None = None     # storage.signed_url(storage_key) 파생 (A10)


class TranscriptStatusOut(BaseModel):
    status: AsyncStatus


class TranscriptSegmentOut(BaseModel):
    ts: str      # "MM:SS" — 저장은 초 float, 응답 시 seconds_to_ts로 변환 (§4.3)
    text: str


class TranscriptDetail(BaseModel):
    """GET /sessions/{id}/transcript 응답 (api-spec §4.3)."""

    status: AsyncStatus
    segments: list[TranscriptSegmentOut] | None = None
    error: ErrorInfo | None = None


# ── 응답 ──────────────────────────────────────────────────────────────

class SessionDetail(BaseModel):
    """GET /sessions/{id} 상세 (api-spec §4.1 응답 예시와 필드 단위 일치).

    material/recording/transcript는 아직 없으면 None. report는 qna 종료 전 항상 None(A7)."""

    id: str
    team_id: str
    owner_id: str
    name: str
    status: SessionStatus
    personas: list[QuestionerPersona]
    question_count: int
    time_limit_minutes: int
    mode: SessionMode
    material: MaterialStatusOut | None = None
    recording: RecordingStatusOut | None = None
    transcript: TranscriptStatusOut | None = None
    report: None = None              # 리포트는 Step 4 — 종료 전엔 항상 null
    created_at: datetime


class SessionCard(BaseModel):
    """GET /teams/{teamId}/sessions 목록 항목 (요약)."""

    id: str
    name: str
    status: SessionStatus
    mode: SessionMode
    persona_count: int
    question_count: int
    time_limit_minutes: int
    created_at: datetime
