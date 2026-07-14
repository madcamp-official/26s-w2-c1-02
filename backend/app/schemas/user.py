from pydantic import BaseModel, ConfigDict, Field, field_validator

# GET /users/me 응답은 auth의 UserOut을 그대로 재사용한다 (id·name·username·email·email_verified).
# UserOut은 username·email을 non-null로 본다. 이게 안전한 근거:
#   - DDL은 활성 유저의 name만 NOT NULL로 강제한다(§3.1 CHECK). username·email은
#     소셜 전용 유저의 경우 NULL이 될 수 있다.
#   - 그러나 현재 소셜 로그인은 목 스텁(auth.login_with_provider)이라 실제 access
#     토큰을 발급하지 않는다. get_current_user가 인정하는 실 유저는 signup 경유뿐이고,
#     signup은 username·email을 필수로 받는다 → 실제로 도달 가능한 활성 유저는 둘 다 존재.
# ⚠️ 실 소셜 로그인을 붙이면(username NULL 유저가 JWT를 받게 되면) 이 재사용은 500을
#    낸다. 그때는 username·email을 Optional로 둔 전용 MeOut로 교체할 것.
from app.schemas.auth import UserOut

__all__ = ["UserOut", "ProfileUpdateRequest", "PasswordChangeRequest"]


class ProfileUpdateRequest(BaseModel):
    """PATCH /users/me 요청 (api-spec §2.1). 프로필(닉네임) 수정.

    스코프 한정: 닉네임(name)만 변경 대상. username·email 변경은 유니크·재인증
    이슈로 이번 범위 밖(§8 후속). SignupRequest와 동일한 name 제약을 따른다."""

    model_config = ConfigDict(extra="forbid")  # 오타 필드(nmae 등) 조용히 무시 말고 422

    name: str = Field(min_length=1, max_length=30, description="닉네임")

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        """닉네임 앞뒤 공백 제거 — 공백만 있는 닉네임("   ")은 빈 문자열이 되어
        min_length=1에 걸린다 (SignupRequest.strip_name과 동일 규약)."""
        return v.strip() if isinstance(v, str) else v


class PasswordChangeRequest(BaseModel):
    """PATCH /users/me/password 요청 (api-spec §2.1).

    current_password는 현재 비밀번호 확인용이라 형식 제약을 두지 않는다(길이만 방어).
    new_password는 SignupRequest.password와 동일 제약(8~128자). 비밀번호는
    공백도 유효 문자이므로 절대 스트립하지 않는다."""

    model_config = ConfigDict(extra="forbid")  # new_pasword 같은 오타를 조용히 흘리면 위험 → 422

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
