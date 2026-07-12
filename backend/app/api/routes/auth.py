import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, Header, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import (
    PasswordTooLongError,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db import models
from app.db.enums import ClientPlatform
from app.db.session import get_db
from app.schemas.auth import (
    AuthUser,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    User,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("rehearsal.auth")

# 이메일 인증코드 유효시간 (스코프 컷: 발송은 생략, 코드 저장 + 로그 출력만)
_VERIFY_CODE_TTL = timedelta(minutes=10)



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


# refresh 토큰 쿠키 설정 (spec §2 Web 응답 예시 그대로)
_REFRESH_COOKIE = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"

# 타이밍 공격 방어용 더미 해시: 아이디가 없을 때도 이 해시로 bcrypt 검증을 한 번 수행해
# "없는 아이디(즉시 401)"와 "틀린 비밀번호(bcrypt 후 401)"의 응답 시간을 같게 만든다.
# (재검증에서 실측: 방어 전 9ms vs 421ms — 시간만 재면 계정 존재 여부가 노출됐음)
_TIMING_DUMMY_HASH = hash_password("timing-equalizer-dummy")


def _parse_platform(header_value: str | None) -> ClientPlatform:
    """X-Client-Platform 헤더 → enum. 없거나 이상한 값이면 web으로 간주 (spec §1: '권장' 헤더)."""
    try:
        return ClientPlatform(header_value)
    except ValueError:
        return ClientPlatform.web


def _issue_tokens(
    user: models.User, platform: ClientPlatform, db: Session, response: Response
) -> TokenResponse:
    """access + refresh 발급 공통 로직. refresh 전달은 플랫폼 분기(spec B 수정):
    Web = httpOnly 쿠키(본문에 없음) / Native(ios·android) = 응답 본문."""
    access_token, expires_in = create_access_token(user.id)

    refresh_raw = generate_refresh_token()
    db.add(models.RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_raw),  # 원문 저장 금지
        platform=platform,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_expires_seconds),
    ))
    db.commit()

    auth_user = AuthUser(id=user.id, name=user.name, username=user.username, email=user.email)

    if platform is ClientPlatform.web:
        response.set_cookie(
            key=_REFRESH_COOKIE,
            value=refresh_raw,
            max_age=settings.refresh_expires_seconds,
            httponly=True,
            secure=True,
            samesite="strict",
            path=_REFRESH_COOKIE_PATH,
        )
        return TokenResponse(access_token=access_token, expires_in=expires_in, user=auth_user)

    return TokenResponse(
        access_token=access_token, refresh_token=refresh_raw,
        expires_in=expires_in, user=auth_user,
    )


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    x_client_platform: str | None = Header(default=None),
) -> TokenResponse:
    """로그인 (api-spec §2): 아이디/비밀번호 검증 → access + refresh 발급.

    아이디가 없든 비밀번호가 틀리든 같은 401을 준다 (계정 존재 여부 노출 방지).
    """
    user = db.scalar(select(models.User).where(
        func.lower(models.User.username) == body.username.lower(),
        models.User.deleted_at.is_(None),          # 탈퇴(익명화) 유저 로그인 불가
    ))
    if user is None or user.password_hash is None:
        # 소셜 전용(해시 NULL)/미가입 — 더미 검증으로 시간을 맞춘 뒤 같은 401
        verify_password(body.password, _TIMING_DUMMY_HASH)
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않아요.")
    if not verify_password(body.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않아요.")

    return _issue_tokens(user, _parse_platform(x_client_platform), db, response)


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
def refresh(
    response: Response,
    body: RefreshRequest | None = None,
    refresh_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
    x_client_platform: str | None = Header(default=None),
) -> TokenResponse:
    """access 재발급 (api-spec §2, 자동 로그인).

    refresh 원문 출처: Web = httpOnly 쿠키(자동 전송) / Native = 본문 {refresh_token}.
    **회전(rotation)**: 쓴 토큰은 즉시 폐기하고 새 refresh를 발급한다 —
    탈취된 토큰이 재사용되면 401이 나므로 피해가 1회로 제한된다.
    실패는 전부 같은 401 → FE는 재로그인으로 보낸다.
    """
    platform = _parse_platform(x_client_platform)
    raw = refresh_cookie if platform is ClientPlatform.web else (body.refresh_token if body else None)
    if not raw:  # 관용: 반대쪽 출처에 있으면 그것이라도 사용
        raw = (body.refresh_token if body else None) or refresh_cookie
    if not raw:
        raise ApiError(401, "UNAUTHORIZED", "refresh 토큰이 없어요. 다시 로그인해주세요.")

    now = datetime.now(timezone.utc)
    # 원자적 소비(claim): "유효하면 폐기하면서 가져오기"를 UPDATE 한 방으로.
    # 같은 토큰으로 동시에 2요청이 와도 DB 행 잠금이 정확히 하나만 성공시킨다
    # (재검증 실측: SELECT 후 폐기 방식은 10회 중 8회 이중 성공 — 회전 보장 깨짐).
    claimed = db.execute(
        update(models.RefreshToken)
        .where(
            models.RefreshToken.token_hash == hash_refresh_token(raw),
            models.RefreshToken.revoked_at.is_(None),
            models.RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(models.RefreshToken.user_id, models.RefreshToken.platform)
    ).one_or_none()
    if claimed is None:  # 없음 · 이미 폐기됨 · 만료 — 전부 같은 401
        raise ApiError(401, "UNAUTHORIZED", "세션이 만료됐어요. 다시 로그인해주세요.")

    user = db.get(models.User, claimed.user_id)
    if user is None or user.deleted_at is not None:
        raise ApiError(401, "UNAUTHORIZED", "세션이 만료됐어요. 다시 로그인해주세요.")

    # 새 토큰 전달 방식은 헤더가 아니라 '이 토큰이 발급됐던 기기'(claimed.platform)를 따른다.
    # 위 UPDATE(폐기)와 새 토큰 INSERT는 _issue_tokens의 commit에 한 트랜잭션으로 묶인다.
    return _issue_tokens(user, claimed.platform, db, response)


@router.get("/me", response_model=AuthUser)
def me(current_user: models.User = Depends(get_current_user)) -> AuthUser:
    """현재 유저 조회 (api-spec §2, 자동 로그인 확인용).

    access 만료 시 get_current_user가 401 TOKEN_EXPIRED를 내고,
    FE는 그걸 신호로 /auth/refresh 후 재시도한다.
    """
    return AuthUser(
        id=current_user.id, name=current_user.name,
        username=current_user.username, email=current_user.email,
    )


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    body: RefreshRequest | None = None,
    refresh_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
    x_client_platform: str | None = Header(default=None),
) -> None:
    """로그아웃 (api-spec §2): 제시된 refresh 폐기 + Web은 쿠키 삭제.

    멱등(idempotent): 이미 폐기됐거나 가짜 토큰이어도 204 — 로그아웃 버튼은
    항상 성공해야 하고, 폐기 여부를 응답으로 구분해주면 토큰 유효성 탐색에 악용된다.
    이 기기의 세션만 끊는다 — 다른 기기(다른 refresh 행)는 영향 없음.
    """
    platform = _parse_platform(x_client_platform)
    raw = refresh_cookie if platform is ClientPlatform.web else (body.refresh_token if body else None)
    if not raw:  # 관용: 반대쪽 출처 폴백 (refresh와 동일 규칙)
        raw = (body.refresh_token if body else None) or refresh_cookie
    if not raw:
        raise ApiError(401, "UNAUTHORIZED", "로그아웃할 세션 정보(refresh 토큰)가 없어요.")

    db.execute(
        update(models.RefreshToken)
        .where(
            models.RefreshToken.token_hash == hash_refresh_token(raw),
            models.RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()

    if refresh_cookie is not None or platform is ClientPlatform.web:
        # 쿠키 삭제는 설정 때와 같은 path/속성이어야 브라우저가 지운다
        response.delete_cookie(
            key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH,
            secure=True, httponly=True, samesite="strict",
        )


# 소셜 로그인은 아직 Mock (spec 경로는 /auth/login/social/{provider} — 실구현 시 교체)
@router.post("/login/{provider}", response_model=LoginResponse)
async def login_with_provider(provider: str) -> LoginResponse:
    user = User(id=f"u_{provider}", name="user", email=f"user@{provider}.com")
    return LoginResponse(user=user, token=f"mock-token-{provider}")
