from pydantic import BaseModel, Field, field_validator

# 간단 이메일 형식 검사 (외부 패키지 없이). 완벽한 RFC 검증이 목적이 아니라 오타 방지용.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupRequest(BaseModel):
    """POST /auth/signup 요청 (api-spec §2). 비밀번호 확인(2회 입력)은 클라이언트 검증."""

    name: str = Field(min_length=1, max_length=30, description="닉네임")
    username: str = Field(
        min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$",
        description="로그인 아이디 (영문/숫자/._-)",
    )
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(max_length=254, pattern=_EMAIL_PATTERN)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        """닉네임 앞뒤 공백 제거 — 공백만 있는 닉네임("   ")은 빈 문자열이 되어
        min_length=1에 걸린다. 비밀번호는 공백도 유효 문자이므로 절대 스트립하지 않는다."""
        return v.strip() if isinstance(v, str) else v


class UserOut(BaseModel):
    """응답에 실어 보내는 유저 정보 (비밀번호 해시 등 내부 값 제외)."""

    id: str
    name: str
    username: str
    email: str
    email_verified: bool


class SignupResponse(BaseModel):
    user: UserOut


class LoginRequest(BaseModel):
    """POST /auth/login 요청 (api-spec §2)."""

    username: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=128)


class AuthUser(BaseModel):
    """로그인 응답의 user — spec §2 예시와 필드 단위 일치 (id·name·username·email만)."""

    id: str
    name: str
    username: str
    email: str | None


class TokenResponse(BaseModel):
    """로그인/refresh 응답 (spec §2).

    Web(쿠키 방식)은 refresh_token=None으로 두면 응답에서 필드 자체가 빠진다
    (라우터에서 response_model_exclude_none=True 사용).
    """

    access_token: str
    refresh_token: str | None = None  # Native 전용. Web은 Set-Cookie로만 전달
    token_type: str = "Bearer"
    expires_in: int
    user: AuthUser


class User(BaseModel):
    id: str
    name: str
    email: str | None = None


class LoginResponse(BaseModel):
    user: User
    # 지금은 Mock 토큰. 추후 실제 JWT로 교체.
    token: str
