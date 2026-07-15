"""SQLAlchemy 모델 16개 (db-schema.md v1.0 DDL과 1:1).

스키마의 진실은 backend/migrations/001_init.sql — 여기는 그 매핑만 한다.
따라서 CHECK 제약·부분 유니크 인덱스·트리거는 모델에 다시 선언하지 않는다
(DB가 이미 강제하고 있고, 중복 선언은 어긋날 위험만 만든다).

규칙:
- PK는 app.core.ids.new_id()로 자동 생성 (1:1 자식 테이블은 부모 PK 재사용이라 예외)
- ENUM은 DDL이 이미 만든 타입에 매핑 (create_type=False)
- created_at/updated_at 등 DB DEFAULT가 있는 컬럼은 값을 안 주면 DB가 채운다
  (updated_at 갱신도 DB 트리거 담당 — 파이썬에서 만지지 않는다)
"""

from datetime import datetime

from sqlalchemy import (
    REAL,
    Enum as SAEnum,
    FetchedValue,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import new_id
from app.db.enums import (
    AnswerKind,
    AnswerStatus,
    AsyncStatus,
    ClientPlatform,
    EndedReason,
    FollowUpStatus,
    InviteStatus,
    QuestionerPersona,
    QuestionStrategy,
    SessionMode,
    SessionStatus,
    SocialProvider,
)


def pg_enum(py_enum: type, name: str) -> SAEnum:
    """DDL이 만든 PostgreSQL ENUM 타입에 매핑 (새로 만들지 않음)."""
    return SAEnum(py_enum, name=name, create_type=False)


timestamptz = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


# ============================================================
# 유저 · 인증 (§3.1)
# ============================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("usr"))
    username: Mapped[str | None] = mapped_column(Text)        # 소셜 전용 가입자는 NULL
    password_hash: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)            # 탈퇴 시 NULL
    email: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(timestamptz)
    deleted_at: Mapped[datetime | None] = mapped_column(timestamptz)  # D4: 익명화 마커
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("soc"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[SocialProvider] = mapped_column(pg_enum(SocialProvider, "social_provider"))
    provider_user_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("rt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text)             # SHA-256 — 원문 저장 금지
    platform: Mapped[ClientPlatform] = mapped_column(pg_enum(ClientPlatform, "client_platform"))
    expires_at: Mapped[datetime] = mapped_column(timestamptz)
    revoked_at: Mapped[datetime | None] = mapped_column(timestamptz)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("emv"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(timestamptz)
    consumed_at: Mapped[datetime | None] = mapped_column(timestamptz)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class PasswordReset(Base):
    """비밀번호 재설정 코드 (migrations/003). email_verifications와 구조는 같지만
    목적이 달라(비밀번호 교체 vs 이메일 인증) 테이블을 분리한다 — 003 주석 참고."""

    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("pwr"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(timestamptz)
    consumed_at: Mapped[datetime | None] = mapped_column(timestamptz)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


# ============================================================
# 팀 · 멤버십 · 초대 (§3.2)
# ============================================================

class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("team"))
    name: Mapped[str] = mapped_column(Text)
    leader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())  # D5: 승계 순서 기준


class TeamEmailInvite(Base):
    __tablename__ = "team_email_invites"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("inv"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[InviteStatus] = mapped_column(
        pg_enum(InviteStatus, "invite_status"), server_default=FetchedValue()
    )
    expires_at: Mapped[datetime] = mapped_column(timestamptz)
    responded_at: Mapped[datetime | None] = mapped_column(timestamptz)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class TeamInviteLink(Base):
    __tablename__ = "team_invite_links"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("lnk"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(timestamptz)
    revoked_at: Mapped[datetime | None] = mapped_column(timestamptz)  # G: 회전 시 즉시 무효
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


# ============================================================
# 세션 (§3.3)
# ============================================================

class RehearsalSession(Base):
    """발표 1회. 이름이 Session이 아닌 이유: SQLAlchemy의 DB세션(Session)과 혼동 방지."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("ses"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))  # F
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[SessionStatus] = mapped_column(
        pg_enum(SessionStatus, "session_status"), server_default=FetchedValue()
    )
    mode: Mapped[SessionMode] = mapped_column(
        pg_enum(SessionMode, "session_mode"), server_default=FetchedValue()
    )
    personas: Mapped[list[QuestionerPersona]] = mapped_column(
        ARRAY(pg_enum(QuestionerPersona, "questioner_persona"))
    )
    question_count: Mapped[int] = mapped_column(SmallInteger)      # 1차 질문 수만 (§4.1)
    time_limit_minutes: Mapped[int] = mapped_column(SmallInteger)
    current_question_id: Mapped[str | None] = mapped_column(Text)  # FK는 DDL에서 deferred
    qna_ended_reason: Mapped[EndedReason | None] = mapped_column(pg_enum(EndedReason, "ended_reason"))
    started_at: Mapped[datetime | None] = mapped_column(timestamptz)  # A9: 클라이언트 권위
    ended_at: Mapped[datetime | None] = mapped_column(timestamptz)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


# ============================================================
# 세션 1:1 자식 — 자료 · 녹음 · 전사 (§3.4, PK = 부모 세션 ID)
# ============================================================

class Material(Base):
    __tablename__ = "materials"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    progress: Mapped[float] = mapped_column(REAL, server_default=FetchedValue())
    file_name: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(SmallInteger)
    storage_key: Mapped[str] = mapped_column(Text)
    slides: Mapped[list | None] = mapped_column(JSONB)   # [{"page":1,"text":"..."}]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class Recording(Base):
    __tablename__ = "recordings"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    file_name: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(timestamptz)
    ended_at: Mapped[datetime | None] = mapped_column(timestamptz)
    total_chunks: Mapped[int | None] = mapped_column(Integer)  # 청크 완료 시 기대 청크 수(§4.3.1); 일괄 업로드는 NULL
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class RecordingChunk(Base):
    """실시간 녹음 청크 (api-spec §4.3.1). (session_id, seq) 멱등 upsert.

    segments는 청크-로컬 타임스탬프 그대로 — /recording/complete 병합 시
    offset_seconds/overlap_seconds로 절대 시각 보정 + 앞겹침 절단(③·④)."""

    __tablename__ = "recording_chunks"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    offset_seconds: Mapped[float] = mapped_column(REAL)
    overlap_seconds: Mapped[float] = mapped_column(REAL, server_default=FetchedValue())
    duration_seconds: Mapped[float] = mapped_column(REAL)
    storage_key: Mapped[str] = mapped_column(Text)
    status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    segments: Mapped[list | None] = mapped_column(JSONB)  # 청크-로컬 [{"start":..,"end":..,"text":..}]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class Transcript(Base):
    __tablename__ = "transcripts"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    segments: Mapped[list | None] = mapped_column(JSONB)  # [{"start":12.0,"end":15.2,"text":"..."}]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


# ============================================================
# 질문 · 답변 (§3.5)
# ============================================================

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: new_id("q"))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE")
    )  # 꼬리질문의 부모 (부모당 1개 — DDL 부분 유니크)
    follow_up_depth: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())  # A11: 0|1
    order_index: Mapped[int] = mapped_column(SmallInteger)
    persona: Mapped[QuestionerPersona] = mapped_column(pg_enum(QuestionerPersona, "questioner_persona"))
    strategy: Mapped[QuestionStrategy] = mapped_column(pg_enum(QuestionStrategy, "question_strategy"))
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, server_default=FetchedValue())
    tts_status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    tts_storage_key: Mapped[str | None] = mapped_column(Text)
    tts_error_code: Mapped[str | None] = mapped_column(Text)
    tts_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class Answer(Base):
    __tablename__ = "answers"

    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[AnswerKind] = mapped_column(pg_enum(AnswerKind, "answer_kind"))
    status: Mapped[AnswerStatus] = mapped_column(
        pg_enum(AnswerStatus, "answer_status"), server_default=FetchedValue()
    )
    audio_storage_key: Mapped[str | None] = mapped_column(Text)  # passed면 NULL
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)               # raw STT 원문 (v0.3)
    follow_up_status: Mapped[FollowUpStatus] = mapped_column(
        pg_enum(FollowUpStatus, "follow_up_status"), server_default=FetchedValue()
    )
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


# ============================================================
# 리포트 (§3.6)
# ============================================================

class Report(Base):
    __tablename__ = "reports"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[AsyncStatus] = mapped_column(
        pg_enum(AsyncStatus, "async_status"), server_default=FetchedValue()
    )
    words_per_minute: Mapped[float | None] = mapped_column(REAL)  # 원문 기준·필러 포함 (07-11 확정)
    filler_words: Mapped[list | None] = mapped_column(JSONB)      # [{"word":"음","count":9}]
    insight: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column(timestamptz, server_default=FetchedValue())


class ReportTypeScore(Base):
    __tablename__ = "report_type_scores"

    report_session_id: Mapped[str] = mapped_column(
        ForeignKey("reports.session_id", ondelete="CASCADE"), primary_key=True
    )
    strategy: Mapped[QuestionStrategy] = mapped_column(
        pg_enum(QuestionStrategy, "question_strategy"), primary_key=True
    )
    score: Mapped[float] = mapped_column(REAL)  # 0.0~1.0
