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
    """(순수 헬퍼) 팀을 로드하되, 요청자가 그 팀 멤버가 아니면 404 (존재 자체를 숨김).

    비멤버에게 403을 주면 '이 팀이 존재한다'는 정보가 새므로 404로 통일한다.
    Depends가 아니라 일반 함수 — 트랜잭션 본문(4-4 팀 나가기/승계 등)에서 직접
    호출한다. 라우터 진입 가드로는 아래 require_team_member(Depends)를 쓴다."""
    team = db.get(models.Team, team_id)
    if team is None:
        raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없어요.")
    is_member = db.get(models.TeamMember, (team_id, user.id)) is not None
    if not is_member:
        raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없어요.")
    return team


# ── 권한 검사 공통화의 씨앗 (작업 4-2) ────────────────────────────────
# 라우터에 그대로 주입하는 두 가드. Step 2("권한 검사 공통화")가 이 패턴을
# 세션 owner 검사(require_session_owner 등)로 확장한다.
#   - require_team_member : 멤버가 아니면 404 (존재를 숨김)
#   - require_team_leader  : 팀장이 아니면 403 FORBIDDEN_NOT_LEADER (§6.2)
# 팀장 가드는 멤버 가드 위에 합성된다 → 팀장 검사에도 멤버 404 규칙이 먼저 적용됨.


def require_team_member(
    team_id: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.Team:
    """멤버 가드 (Depends). 요청자가 팀 멤버면 Team을 주입하고, 아니면 404.

    사용:  team: models.Team = Depends(require_team_member)
    경로에 {team_id}가 있는 엔드포인트에서 team_id를 자동으로 받아온다."""
    return load_team_as_member(team_id, user, db)


def require_team_leader(
    team: models.Team = Depends(require_team_member),
    user: models.User = Depends(get_current_user),
) -> models.Team:
    """팀장 가드 (Depends). require_team_member 위에 팀장 검사를 얹는다.

    멤버지만 팀장이 아니면 403 FORBIDDEN_NOT_LEADER (팀 존재는 이미 드러난 상태)."""
    if team.leader_id != user.id:
        raise ApiError(403, "FORBIDDEN_NOT_LEADER", "팀장만 할 수 있는 작업이에요.")
    return team


# ── 세션 권한 (작업 1, Step 2) ────────────────────────────────────────
# 세션 = 발표 1회. "멤버"는 세션이 속한 팀의 멤버, "owner"는 발표자(생성자).
#   - require_session_member          : 세션 팀 멤버가 아니면 404 (존재를 숨김)
#   - require_session_owner           : owner가 아니면 403 FORBIDDEN_NOT_OWNER (§6.2)
#   - require_session_owner_or_leader : 삭제용 — owner 또는 팀장 (api-spec §4.1)


def load_session_as_member(session_id: str, user: models.User, db: Session) -> models.RehearsalSession:
    """(순수 헬퍼) 세션을 로드하되, 요청자가 그 세션 팀의 멤버가 아니면 404.

    팀 로더와 같은 규칙 — 비멤버에게 세션 존재를 숨긴다. 트랜잭션 본문에서
    직접 호출하거나, 아래 require_session_member(Depends)가 감싼다."""
    session = db.get(models.RehearsalSession, session_id)
    if session is None:
        raise ApiError(404, "SESSION_NOT_FOUND", "발표 세션을 찾을 수 없어요.")
    is_member = db.get(models.TeamMember, (session.team_id, user.id)) is not None
    if not is_member:
        raise ApiError(404, "SESSION_NOT_FOUND", "발표 세션을 찾을 수 없어요.")
    return session


def require_session_member(
    session_id: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.RehearsalSession:
    """멤버 가드 (Depends). 경로의 {session_id}로 세션을 로드해 주입한다."""
    return load_session_as_member(session_id, user, db)


def require_session_owner(
    session: models.RehearsalSession = Depends(require_session_member),
    user: models.User = Depends(get_current_user),
) -> models.RehearsalSession:
    """owner 가드 (Depends). 멤버 가드 위에 발표자 검사를 얹는다.

    멤버지만 발표자(owner)가 아니면 403 FORBIDDEN_NOT_OWNER (§6.2). 세션 설정
    수정 등 발표자 전용 작업에 사용."""
    if session.owner_id != user.id:
        raise ApiError(403, "FORBIDDEN_NOT_OWNER", "발표자만 할 수 있는 작업이에요.")
    return session


def require_session_owner_or_leader(
    session: models.RehearsalSession = Depends(require_session_member),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> models.RehearsalSession:
    """삭제 가드 (Depends). owner 또는 팀장이면 통과 (api-spec §4.1 세션 삭제 권한).

    둘 다 아니면 403 FORBIDDEN_NOT_OWNER."""
    if session.owner_id == user.id:
        return session
    team = db.get(models.Team, session.team_id)
    if team is not None and team.leader_id == user.id:
        return session
    raise ApiError(403, "FORBIDDEN_NOT_OWNER", "발표자 또는 팀장만 삭제할 수 있어요.")
