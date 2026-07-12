"""라우터 공통 의존성 (작업 3-6).

사용법 — 보호가 필요한 모든 엔드포인트에서:

    from app.api.deps import get_current_user

    @router.get("/teams")
    def list_teams(user: models.User = Depends(get_current_user)):
        ...  # user = 검증된 현재 유저 (ORM 객체)

에러 계약 (api-spec §6.2 — FE 인터셉터가 코드 문자열에 의존):
- 401 TOKEN_EXPIRED  : access 만료 → FE가 /auth/refresh 후 재시도
- 401 UNAUTHORIZED   : 그 외 전부(헤더 없음·위조·탈퇴 유저) → FE가 로그인으로
"""

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)
from app.db import models
from app.db.session import get_db


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    """Authorization: Bearer <access>를 검증하고 현재 유저를 반환한다."""
    if not authorization:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요해요.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "UNAUTHORIZED", "인증 형식이 올바르지 않아요. (Bearer 토큰)")

    try:
        user_id = decode_access_token(token.strip())
    except TokenExpiredError:
        # 정확히 이 코드여야 FE 인터셉터가 refresh를 시도한다 (api-spec §2·§6.2)
        raise ApiError(401, "TOKEN_EXPIRED", "로그인이 만료됐어요.")
    except TokenInvalidError:
        raise ApiError(401, "UNAUTHORIZED", "유효하지 않은 인증이에요.")

    user = db.get(models.User, user_id)
    if user is None or user.deleted_at is not None:  # 토큰 유효기간 내 탈퇴한 경우 차단
        raise ApiError(401, "UNAUTHORIZED", "유효하지 않은 인증이에요.")
    return user
