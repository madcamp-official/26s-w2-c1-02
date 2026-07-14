"""마이페이지 계정 관리 (`/users/me`) — api-spec §2.1.

Step 4 작업 2: 라우터 골격 + 인증 배선만. 각 핸들러의 실제 로직은 후속 작업에서 채운다.
  - GET    /users/me           → 작업 3 (계정 조회)
  - PATCH  /users/me           → 작업 4 (닉네임 수정)
  - PATCH  /users/me/password  → 작업 5 (비밀번호 변경)
  - DELETE /users/me           → 작업 6 (회원 탈퇴 = 익명화, §7.1)

모든 엔드포인트는 본인 스코프다 — 경로에 userId가 없고, 대상은 항상 토큰의 유저
(`get_current_user`). 탈퇴(`deleted_at`) 유저 차단은 Depends가 이미 처리한다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import ApiError
from app.db import models
from app.db.session import get_db
from app.schemas.user import ProfileUpdateRequest, UserOut

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
def change_password(current_user: models.User = Depends(get_current_user)) -> None:
    """비밀번호 변경 (api-spec §2.1). 구현: 작업 5."""
    raise ApiError(501, "NOT_IMPLEMENTED", _NOT_IMPL_MSG)


@router.delete("/me", status_code=204)
def delete_me(current_user: models.User = Depends(get_current_user)) -> None:
    """회원 탈퇴 = 익명화 (db-schema §7.1, D4). 구현: 작업 6."""
    raise ApiError(501, "NOT_IMPLEMENTED", _NOT_IMPL_MSG)
