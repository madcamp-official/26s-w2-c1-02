from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, Response
from sqlalchemy import func, or_, select, update
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
    VerifyBody,
    VerifyRequestBody,
    VerifyResponse,
)
from app.services.email import send_verification_email
from app.services.email_verification import (
    MAX_ATTEMPTS,
    RESEND_COOLDOWN,
    issue_verification_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _reclaim_stale_unverified(db: Session, *, username: str, email: str) -> None:
    """미인증인 채 인증 창까지 만료된 계정이 username/email을 점유 중이면 삭제한다.

    미인증 유저는 로그인이 막혀 있어(email_verified_at 필수) 팀·세션 등 딸린 데이터를
    만들 수 없다 → 하드 삭제해도 잃을 게 없고, 붙잡고 있던 아이디/이메일이 부분 유니크
    인덱스(WHERE ... IS NOT NULL)에서 풀려 재가입이 가능해진다. email_verifications는
    FK CASCADE로 함께 사라진다.

    '인증 창이 아직 열림'(소비 안 된 미만료 코드가 하나라도 존재)은 진행 중인 가입이므로
    회수하지 않는다 — 그 경우 아래 중복 검사가 그대로 409를 낸다. username·email이 서로
    다른 두 stale 계정에 걸쳐 있어도 둘 다 정리한다.
    """
    now = datetime.now(timezone.utc)
    has_live_code = (
        select(models.EmailVerification.id)
        .where(
            models.EmailVerification.user_id == models.User.id,
            models.EmailVerification.consumed_at.is_(None),
            models.EmailVerification.expires_at > now,
        )
        .exists()
    )
    stale = db.scalars(
        select(models.User).where(
            or_(
                func.lower(models.User.username) == username.lower(),
                func.lower(models.User.email) == email.lower(),
            ),
            models.User.email_verified_at.is_(None),
            models.User.deleted_at.is_(None),
            ~has_live_code,
        )
    ).all()
    if not stale:
        return
    for user in stale:
        db.delete(user)  # DB의 ON DELETE CASCADE가 email_verifications도 정리
    db.commit()


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(
    body: SignupRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SignupResponse:
    """회원가입 (api-spec §2): 미인증 유저 생성 + 인증코드 발송.

    - username/email 중복은 대소문자 무시 (DB 부분 유니크 인덱스와 동일 기준)
    - 발송은 BackgroundTasks(응답 무영향) — 실패해도 가입은 성공, 재발송으로 복구
    """
    # 0) 인증 창까지 만료된 미인증 계정이 아이디/이메일을 쥐고 있으면 회수 — 재가입 허용
    _reclaim_stale_unverified(db, username=body.username, email=body.email)

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

    # 3) 미인증 유저 생성
    user = models.User(
        username=body.username, password_hash=password_hash,
        name=body.name, email=body.email,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:  # 동시 가입 레이스 — 부분 유니크 인덱스가 잡아줌
        db.rollback()
        taken = "EMAIL_TAKEN" if "users_email_key" in str(e.orig) else "USERNAME_TAKEN"
        raise ApiError(409, taken, "이미 사용 중인 아이디 또는 이메일이에요.")

    # 4) 인증코드 발급(커밋 포함) + 발송. 발송이 느리거나 실패해도 응답은 그대로 201
    code = issue_verification_code(db, user)
    background_tasks.add_task(send_verification_email, user.email, code)

    return SignupResponse(user=UserOut(
        id=user.id, name=user.name, username=user.username,
        email=user.email, email_verified=user.email_verified_at is not None,
    ))


def _find_user_by_email(db: Session, email: str) -> models.User | None:
    """이메일로 활성 유저 조회 (대소문자 무시 — signup 중복 검사와 동일 기준)."""
    return db.scalar(select(models.User).where(
        func.lower(models.User.email) == email.lower(),
        models.User.deleted_at.is_(None),
    ))


@router.post("/email/verify-request", status_code=204)
def request_verification_code(
    body: VerifyRequestBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> None:
    """인증코드 재발송 (api-spec §2): 유저가 없어도·이미 인증돼도 같은 204.

    204로 통일하는 이유 — 응답이 갈리면 "이 이메일이 가입돼 있나"를 무제한
    조회할 수 있게 된다(계정 열거). 절대 404를 내지 말 것.
    """
    user = _find_user_by_email(db, body.email)
    if user is None or user.email_verified_at is not None:
        return  # 204 — 존재 여부·인증 여부 비노출 (멱등)

    # 재발송 쿨다운: 마지막 발급(소비 여부 무관) 후 60초. 발송 스팸·Gmail 쿼터 보호
    latest = db.scalar(
        select(func.max(models.EmailVerification.created_at))
        .where(models.EmailVerification.user_id == user.id)
    )
    if latest is not None:
        remaining = RESEND_COOLDOWN - (datetime.now(timezone.utc) - latest)
        if remaining.total_seconds() > 0:
            retry_after = int(remaining.total_seconds()) + 1  # 올림 — 과소 안내 방지
            raise ApiError(
                429, "RATE_LIMITED", "잠시 후 다시 시도해주세요.",
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    code = issue_verification_code(db, user)
    background_tasks.add_task(send_verification_email, user.email, code)


@router.post("/email/verify", response_model=VerifyResponse)
def verify_email(body: VerifyBody, db: Session = Depends(get_db)) -> VerifyResponse:
    """이메일 인증 (api-spec §2): 코드 대조 → email_verified_at 설정. 멱등.

    유저 없음도 INVALID_CODE(400) — verify-request의 204와 같은 이유로 존재 여부를
    숨긴다. attempt 검사는 반드시 대조보다 먼저(아니면 5회 초과 후에도 대조 시도 허용).
    """
    user = _find_user_by_email(db, body.email)
    if user is None:
        # 더미 bcrypt 1회로 "없는 이메일(즉시 400)"과 "틀린 코드(대조 후 400)"의
        # 응답 시간을 맞춘다 — login의 타이밍 공격 방어와 동일 규율
        verify_password(body.code, _TIMING_DUMMY_HASH)
        raise ApiError(400, "INVALID_CODE", "코드가 올바르지 않아요.")
    if user.email_verified_at is not None:
        return VerifyResponse(email_verified=True)  # 멱등 — 이미 인증 완료

    now = datetime.now(timezone.utc)
    row = db.scalar(
        select(models.EmailVerification)
        .where(
            models.EmailVerification.user_id == user.id,
            models.EmailVerification.consumed_at.is_(None),
            models.EmailVerification.expires_at > now,
        )
        .order_by(models.EmailVerification.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise ApiError(400, "CODE_EXPIRED", "코드가 만료됐어요. 재발송해주세요.")
    if row.attempt_count >= MAX_ATTEMPTS:  # 소진 — 만료와 동일 취급 (재발송 유도)
        raise ApiError(400, "CODE_EXPIRED", "시도 횟수를 초과했어요. 재발송해주세요.")

    if not verify_password(body.code, row.code_hash):
        row.attempt_count += 1
        db.commit()
        raise ApiError(400, "INVALID_CODE", "코드가 올바르지 않아요.")

    row.consumed_at = now
    user.email_verified_at = now
    db.commit()
    return VerifyResponse(email_verified=True)


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

    # 미인증 차단은 반드시 비밀번호 검증 **후** — 403은 "비밀번호는 맞는데 미인증"의
    # 신호라서, FE가 재로그인 없이 곧바로 코드 입력 화면으로 보낼 수 있다 (spec §2).
    # 비밀번호가 틀리면 위의 기존 401. refresh는 로그인을 통과한 세션만 도달하므로
    # 검사 지점은 여기 한 곳뿐.
    if user.email_verified_at is None:
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "이메일 인증을 완료해주세요.")

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
