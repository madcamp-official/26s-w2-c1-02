from pydantic import BaseModel


class LoginRequest(BaseModel):
    id: str | None = None
    password: str | None = None


class User(BaseModel):
    id: str
    name: str
    email: str | None = None


class LoginResponse(BaseModel):
    user: User
    # 지금은 Mock 토큰. 추후 실제 JWT로 교체.
    token: str
