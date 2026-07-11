"""DB ENUM 12종 (db-schema.md §2 · api-spec.md §6.1과 1:1).

멤버 이름과 값을 동일하게 유지한다 — SQLAlchemy가 기본적으로 멤버 '이름'을
DB에 저장하므로, 이름=값이면 혼동 여지가 없다.
"""

from enum import StrEnum


class ClientPlatform(StrEnum):
    web = "web"
    ios = "ios"
    android = "android"


class SocialProvider(StrEnum):
    google = "google"
    kakao = "kakao"
    naver = "naver"


class InviteStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    canceled = "canceled"


class SessionStatus(StrEnum):
    draft = "draft"
    recording_in_progress = "recording_in_progress"
    transcribing = "transcribing"
    generating_questions = "generating_questions"
    qna = "qna"
    completed = "completed"
    failed = "failed"


class SessionMode(StrEnum):
    realtime = "realtime"
    upload = "upload"


class QuestionerPersona(StrEnum):
    egen = "egen"
    teto = "teto"
    kkondae = "kkondae"
    mungcheong = "mungcheong"
    jammin = "jammin"


class QuestionStrategy(StrEnum):
    detail_probe = "detail_probe"
    big_picture = "big_picture"
    basic_concept = "basic_concept"
    numeric_verification = "numeric_verification"


class AsyncStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class AnswerStatus(StrEnum):
    # 'pending'은 answers row 부재로 표현 (db-schema §5)
    processing = "processing"
    ready = "ready"
    failed = "failed"


class AnswerKind(StrEnum):
    answered = "answered"
    passed = "passed"


class FollowUpStatus(StrEnum):
    pending = "pending"
    generated = "generated"
    none = "none"


class EndedReason(StrEnum):
    user_end = "user_end"
    count_reached = "count_reached"
    timeout = "timeout"
