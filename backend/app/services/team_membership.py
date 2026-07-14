"""팀 멤버십 이탈 + 팀장 자동 승계 공용 로직 (db-schema §7.2 · D5).

`POST /teams/{id}/leave`(teams.py)와 `DELETE /users/me`(users.py, 탈퇴=익명화)가
같은 규칙을 공유한다. 규칙을 한 곳에 두어 두 경로가 어긋나지 않게 한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def leave_or_succeed(db: Session, team: models.Team, user_id: str) -> None:
    """한 팀에서 user를 이탈시킨다. **커밋은 호출자 몫**(단일 트랜잭션 보장).

    - 비팀장          : 내 멤버십만 삭제
    - 팀장 + 후임 있음 : 최고참(joined_at→user_id) 승계 후 내 멤버십 삭제
    - 팀장 + 마지막 1인 : 팀 삭제 (세션·멤버십·초대 CASCADE)

    같은 팀의 동시 이탈/내보내기를 직렬화하기 위해 팀 행에 FOR UPDATE 잠금을 걸고
    리더를 새로 읽는다 — 없으면 '리더 이탈(승계)'과 '다른 멤버 이탈'이 겹칠 때
    커밋 시점 FK 위반(500)이 난다. (DEFERRABLE FK가 커밋 시 '팀장 ∈ 멤버'를 강제)
    """
    db.refresh(team, with_for_update=True)
    membership = db.get(models.TeamMember, (team.id, user_id))
    if membership is None:  # 멤버 아님 — 방어 (정상 흐름에선 호출 전 멤버 확인됨)
        return

    if team.leader_id != user_id:
        db.delete(membership)
        return

    # 팀장 이탈 → 본인 제외 최고참을 후임으로 (db-schema §7.2 쿼리 그대로)
    successor_id = db.scalar(
        select(models.TeamMember.user_id)
        .where(models.TeamMember.team_id == team.id,
               models.TeamMember.user_id != user_id)
        .order_by(models.TeamMember.joined_at, models.TeamMember.user_id)
        .limit(1)
    )
    if successor_id is None:
        db.delete(team)          # 마지막 1인 → 팀 통째로 CASCADE
    else:
        team.leader_id = successor_id
        db.delete(membership)    # 커밋 시 후임이 멤버로 남아 있어 FK 통과
