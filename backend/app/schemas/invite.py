"""초대 스키마 (작업 4-5, api-spec §3.1).

이메일 초대(단일 사용·상태 있음)와 링크 초대(재사용·팀당 활성 1개)를 구분한다.
`/invites/{token}` 미리보기/수락/거절은 두 종류 토큰을 모두 받는다.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# auth 스키마와 동일한 간이 이메일 검사 (외부 패키지 없이 오타 방지용)
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class EmailInviteRequest(BaseModel):
    """POST /teams/{id}/invites 요청."""

    email: str = Field(max_length=254, pattern=_EMAIL_PATTERN)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: object) -> object:
        # 소문자화 — team_email_invites_pending_key가 lower(email) 기준이라 일관성 유지
        return v.strip().lower() if isinstance(v, str) else v


class EmailInviteOut(BaseModel):
    """이메일 초대 응답. 발송을 생략하므로 token·url을 그대로 노출한다(스코프 컷)."""

    id: str
    email: str
    status: str
    token: str
    url: str
    expires_at: datetime
    created_at: datetime


class InviteLinkOut(BaseModel):
    """링크 초대 응답 (api-spec §3.1: { token, url, expires_at })."""

    token: str
    url: str
    expires_at: datetime


class InvitePreview(BaseModel):
    """GET /invites/{token} 미리보기 (인증 불필요) — 팀명·인원·발표 수."""

    team_id: str
    team_name: str
    member_count: int
    session_count: int


class AcceptResponse(BaseModel):
    """수락 결과 — FE가 팀 화면으로 이동할 team_id."""

    team_id: str
