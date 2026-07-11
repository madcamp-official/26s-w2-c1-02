import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import PasswordTooLongError, hash_password
from app.db import models
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    User,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("rehearsal.auth")

# 이메일 인증코드 유효시간 (스코프 컷: 발송은 생략, 코드 저장 + 로그 출력만)
_VERIFY_CODE_TTL = timedelta(minutes=10)

# 지금은 Mock 인증. 추후 카카오/구글 OAuth 또는 이메일 로그인으로 교체.
_MOCK_USER = User(id="u_1", name="user", email="user@rehearsal.io")


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> SignupResponse:
    """회원가입 (api-spec §2): 미인증 유저 생성 + 인증코드 저장.

    - username/email 중복은 대소문자 무시 (DB 부분 유니크 인덱스와 동일 기준)
    - 인증코드는 발송 없이 해시로 저장하고 개발용 로그로만 출력 (스코프 컷 합의)
    """
    # 1) 중복 선검사 — 명확한 에러 코드를 주기 위해 (레이스는 아래 IntegrityError가 최종 방어)
    if db.scalar(select(models.User.id).where(func.lower(models.User.username) == body.username.lower())):
        raise ApiError(409, "USERNAME_TAKEN", "이미 사용 중인 아이디예요.")
    if db.scalar(select(models.User.id).where(func.lower(models.User.email) == body.email.lower())):
        raise ApiError(409, "EMAIL_TAKEN", "이미 가입된 이메일이에요.")

    # 2) 비밀번호 해시 (bcrypt 72바이트 상한 초과 → 400)
    try:
        password_hash = hash_password(body.password)
    except PasswordTooLongError as e:
        raise ApiError(400, "PASSWORD_TOO_LONG", str(e))

    # 3) 미인증 유저 + 인증코드 생성 (한 트랜잭션)
    user = models.User(
        username=body.username, password_hash=password_hash,
        name=body.name, email=body.email,
    )
    db.add(user)
    db.flush()

    code = f"{secrets.randbelow(1_000_000):06d}"  # 000000~999999
    db.add(models.EmailVerification(
        user_id=user.id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + _VERIFY_CODE_TTL,
    ))

    try:
        db.commit()
    except IntegrityError as e:  # 동시 가입 레이스 — 부분 유니크 인덱스가 잡아줌
        db.rollback()
        taken = "EMAIL_TAKEN" if "users_email_key" in str(e.orig) else "USERNAME_TAKEN"
        raise ApiError(409, taken, "이미 사용 중인 아이디 또는 이메일이에요.")

    # SMTP 미도입(스코프 컷) — 개발 중에는 서버 로그에서 코드를 확인한다
    logger.info("이메일 인증코드(발송 생략, 개발용): %s -> %s", body.email, code)

    return SignupResponse(user=UserOut(
        id=user.id, name=user.name, username=user.username,
        email=user.email, email_verified=user.email_verified_at is not None,
    ))


@router.post("/login", response_model=LoginResponse)
async def login(_: LoginRequest) -> LoginResponse:
    return LoginResponse(user=_MOCK_USER, token="mock-token")


@router.post("/login/{provider}", response_model=LoginResponse)
async def login_with_provider(provider: str) -> LoginResponse:
    user = User(id=f"u_{provider}", name="user", email=f"user@{provider}.com")
    return LoginResponse(user=user, token=f"mock-token-{provider}")
