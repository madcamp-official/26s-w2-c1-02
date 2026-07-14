"""마이페이지 계정 관리 (`/users/me`) — api-spec §2.1.

Step 4 작업 2: 라우터 골격 + 인증 배선만. 각 핸들러의 실제 로직은 후속 작업에서 채운다.
  - GET    /users/me           → 작업 3 (계정 조회)
  - PATCH  /users/me           → 작업 4 (닉네임 수정)
  - PATCH  /users/me/password  → 작업 5 (비밀번호 변경)
  - DELETE /users/me           → 작업 6 (회원 탈퇴 = 익명화, §7.1)

모든 엔드포인트는 본인 스코프다 — 경로에 userId가 없고, 대상은 항상 토큰의 유저
(`get_current_user`). 탈퇴(`deleted_at`) 유저 차단은 Depends가 이미 처리한다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import ApiError
from app.core.security import PasswordTooLongError, hash_password, verify_password
from app.db import models
from app.db.session import get_db
from app.schemas.user import PasswordChangeRequest, ProfileUpdateRequest, UserOut
from app.services.team_membership import leave_or_succeed

router = APIRouter(prefix="/users", tags=["users"])

# 골격 단계 플레이스홀더 — 후속 작업에서 각 핸들러 본문으로 교체된다.
_NOT_IMPL_MSG = "이 기능은 아직 준비 중이에요."


def _to_user_out(user: models.User) -> UserOut:
    """User 모델 → UserOut. email_verified는 email_verified_at에서 파생
    (signup 응답과 동일 규약). GET·PATCH가 공유한다."""
    return UserOut(
        id=user.id, name=user.name, username=user.username,
        email=user.email, email_verified=user.email_verified_at is not None,
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: models.User = Depends(get_current_user)) -> UserOut:
    """계정 정보 조회 (api-spec §2.1).

    get_current_user가 이미 토큰 검증 + 탈퇴 유저 차단을 마쳤으므로 직렬화만 한다."""
    return _to_user_out(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """프로필(닉네임) 수정 (api-spec §2.1). name만 변경 (username·email은 범위 밖).

    current_user는 get_current_user가 이 요청의 db 세션으로 로드한 것이므로
    (Depends(get_db) 캐싱), 필드 수정 후 같은 세션에서 commit하면 반영된다."""
    current_user.name = body.name
    db.commit()
    db.refresh(current_user)
    return _to_user_out(current_user)


@router.patch("/me/password", status_code=204)
def change_password(
    body: PasswordChangeRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """비밀번호 변경 (api-spec §2.1).

    현재 비밀번호 확인 → 새 해시로 교체 → 이 유저의 모든 refresh 토큰 폐기.
    폐기 이유: 비밀번호가 바뀌면 기존에 유출됐을 수 있는 refresh 토큰도 무력화해야
    한다(전 기기 재로그인). 현재 기기의 access 토큰은 만료 전까진 유효."""
    # 소셜 전용(로컬 비번 없음)은 변경 대상이 아니다
    if current_user.password_hash is None:
        raise ApiError(400, "NO_PASSWORD_SET", "소셜 로그인 계정은 비밀번호가 없어요.")
    # 현재 비밀번호 확인
    if not verify_password(body.current_password, current_user.password_hash):
        raise ApiError(400, "INVALID_CREDENTIALS", "현재 비밀번호가 일치하지 않아요.")
    # 새 비밀번호 해시 (bcrypt 72바이트 상한 초과 → 400, signup과 동일 매핑)
    try:
        new_hash = hash_password(body.new_password)
    except PasswordTooLongError as e:
        raise ApiError(400, "PASSWORD_TOO_LONG", str(e))

    current_user.password_hash = new_hash
    db.execute(
        update(models.RefreshToken)
        .where(models.RefreshToken.user_id == current_user.id,
               models.RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


@router.delete("/me", status_code=204)
def delete_me(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """회원 탈퇴 = 익명화 (db-schema §7.1, D4). **하드삭제가 아니다.**

    단일 트랜잭션 (db-schema §7.1):
      1. 소속 각 팀: 팀장이면 승계, 아니면 멤버십만 삭제 (leave_or_succeed 공유)
      2. 소셜 계정 삭제 + refresh 토큰 전부 폐기
      3. PII(username·password_hash·name·email) NULL화 + deleted_at 기록
    본인이 owner인 세션·녹음·Q&A·리포트는 **보존**된다(팀 자산, owner는 "탈퇴한 사용자").
    유니크 인덱스가 부분(WHERE ... IS NOT NULL)이라 NULL화로 재가입도 허용된다.
    """
    # 1. 소속 팀 처리 (팀장 승계 포함) — 내가 가진 모든 멤버십을 팀별로 정리
    team_ids = db.scalars(
        select(models.TeamMember.team_id)
        .where(models.TeamMember.user_id == current_user.id)
    ).all()
    for team_id in team_ids:
        team = db.get(models.Team, team_id)
        if team is not None:
            leave_or_succeed(db, team, current_user.id)

    # 2. 소셜 계정 삭제 + 이 유저의 모든 refresh 토큰 폐기
    db.execute(delete(models.SocialAccount)
               .where(models.SocialAccount.user_id == current_user.id))
    db.execute(update(models.RefreshToken)
               .where(models.RefreshToken.user_id == current_user.id,
                      models.RefreshToken.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))

    # 3. PII 익명화 (row 보존 — owner 세션 유지, 재가입 허용)
    current_user.username = None
    current_user.password_hash = None
    current_user.name = None
    current_user.email = None
    current_user.deleted_at = datetime.now(timezone.utc)

    db.commit()
