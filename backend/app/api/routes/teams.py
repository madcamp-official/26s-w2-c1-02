"""팀 CRUD (작업 4-1, api-spec §3 · db-schema §3.2·§8.3).

권한:
- GET /teams          : 내가 속한 팀만
- POST /teams         : 로그인한 누구나 (생성자 = 팀장 + 첫 멤버)
- GET /teams/{id}     : 멤버
- PATCH /teams/{id}   : 팀장
- DELETE /teams/{id}  : 팀장 (세션·멤버십·초대 전부 CASCADE — db-schema §7.3)
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_team_leader, require_team_member
from app.db import models
from app.db.session import get_db
from app.schemas.team import (
    TeamCard,
    TeamCreateRequest,
    TeamDetail,
    TeamMemberInfo,
    TeamUpdateRequest,
)

router = APIRouter(prefix="/teams", tags=["teams"])


# db-schema §8.3 쿼리 그대로 — 내 팀 목록(발표 수 + 멤버 미리보기)
_LIST_TEAMS_SQL = text("""
    SELECT t.id, t.name,
           (SELECT count(*) FROM sessions s WHERE s.team_id = t.id) AS session_count,
           (SELECT string_agg(coalesce(u.name, '탈퇴한 사용자'), ', ' ORDER BY m2.joined_at)
            FROM team_members m2 JOIN users u ON u.id = m2.user_id
            WHERE m2.team_id = t.id) AS members_preview
    FROM teams t
    JOIN team_members m ON m.team_id = t.id AND m.user_id = :uid
    ORDER BY t.created_at DESC
""")


@router.get("", response_model=list[TeamCard])
def list_teams(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamCard]:
    rows = db.execute(_LIST_TEAMS_SQL, {"uid": user.id}).mappings().all()
    return [
        TeamCard(
            id=r["id"], name=r["name"],
            session_count=r["session_count"],
            members_preview=r["members_preview"] or "",
        )
        for r in rows
    ]


@router.post("", response_model=TeamDetail, status_code=201)
def create_team(
    body: TeamCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamDetail:
    """생성자를 팀장 + 첫 멤버로. teams_leader_is_member_fk가 DEFERRABLE이라
    팀 insert와 멤버 insert 순서는 자유 — 커밋 시점에 '팀장 ∈ 멤버'를 검사한다."""
    team = models.Team(name=body.name, leader_id=user.id)
    db.add(team)
    db.flush()  # team.id 확보 (아직 커밋 아님)
    db.add(models.TeamMember(team_id=team.id, user_id=user.id))
    db.commit()
    db.refresh(team)
    return _to_detail(team, db)


@router.get("/{team_id}", response_model=TeamDetail)
def get_team(
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> TeamDetail:
    return _to_detail(team, db)


@router.patch("/{team_id}", response_model=TeamDetail)
def update_team(
    body: TeamUpdateRequest,
    team: models.Team = Depends(require_team_leader),
    db: Session = Depends(get_db),
) -> TeamDetail:
    team.name = body.name
    db.commit()
    db.refresh(team)
    return _to_detail(team, db)


@router.delete("/{team_id}", status_code=204)
def delete_team(
    team: models.Team = Depends(require_team_leader),
    db: Session = Depends(get_db),
) -> None:
    # 세션·자료·녹음·전사·Q&A·리포트·멤버십·초대까지 DB CASCADE (db-schema §7.3)
    # 오브젝트 스토리지 파일 삭제는 작업 5에서 추가 예정
    db.delete(team)
    db.commit()


def _to_detail(team: models.Team, db: Session) -> TeamDetail:
    """팀 상세 응답 구성 — 멤버 목록(가입순) + 발표 수."""
    member_rows = db.execute(
        select(models.User.id, models.User.name, models.User.username)
        .join(models.TeamMember, models.TeamMember.user_id == models.User.id)
        .where(models.TeamMember.team_id == team.id)
        .order_by(models.TeamMember.joined_at, models.User.id)
    ).all()
    members = [
        TeamMemberInfo(id=r.id, name=r.name, username=r.username,
                       is_leader=(r.id == team.leader_id))
        for r in member_rows
    ]
    session_count = db.scalar(
        select(func.count()).select_from(models.RehearsalSession)
        .where(models.RehearsalSession.team_id == team.id)
    )
    return TeamDetail(
        id=team.id, name=team.name, leader_id=team.leader_id,
        session_count=session_count, members=members, created_at=team.created_at,
    )
