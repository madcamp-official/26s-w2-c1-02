from fastapi import APIRouter

from app.schemas.auth import LoginRequest, LoginResponse, User

router = APIRouter(prefix="/auth", tags=["auth"])

# 지금은 Mock 인증. 추후 카카오/구글 OAuth 또는 이메일 로그인으로 교체.
_MOCK_USER = User(id="u_1", name="user", email="user@rehearsal.io")


@router.post("/login", response_model=LoginResponse)
async def login(_: LoginRequest) -> LoginResponse:
    return LoginResponse(user=_MOCK_USER, token="mock-token")


@router.post("/login/{provider}", response_model=LoginResponse)
async def login_with_provider(provider: str) -> LoginResponse:
    user = User(id=f"u_{provider}", name="user", email=f"user@{provider}.com")
    return LoginResponse(user=user, token=f"mock-token-{provider}")
