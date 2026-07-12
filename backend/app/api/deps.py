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


def load_team_as_member(team_id: str, user: models.User, db: Session) -> models.Team:
    """팀을 로드하되, 요청자가 그 팀 멤버가 아니면 404 (존재 자체를 숨김).

    비멤버에게 403을 주면 '이 팀이 존재한다'는 정보가 새므로 404로 통일한다.
    라우터에서 재사용하는 공통 권한 부품 (세션 라우터도 사용 예정)."""
    team = db.get(models.Team, team_id)
    if team is None:
        raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없어요.")
    is_member = db.get(models.TeamMember, (team_id, user.id)) is not None
    if not is_member:
        raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없어요.")
    return team


def require_team_leader(team: models.Team, user: models.User) -> None:
    """팀장 전용 작업 가드. 멤버지만 팀장이 아니면 403 (존재는 이미 드러난 상태)."""
    if team.leader_id != user.id:
        raise ApiError(403, "FORBIDDEN_NOT_LEADER", "팀장만 할 수 있는 작업이에요.")
