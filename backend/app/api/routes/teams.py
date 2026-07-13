"""팀 CRUD (작업 4-1, api-spec §3 · db-schema §3.2·§8.3).

권한:
- GET /teams          : 내가 속한 팀만
- POST /teams         : 로그인한 누구나 (생성자 = 팀장 + 첫 멤버)
- GET /teams/{id}     : 멤버
- PATCH /teams/{id}   : 팀장
- DELETE /teams/{id}  : 팀장 (세션·멤버십·초대 전부 CASCADE — db-schema §7.3)
- GET /teams/{id}/members            : 멤버 (팀원 목록)
- DELETE /teams/{id}/members/{userId}: 팀장 (팀원 내보내기, 팀장 자신 제외)
- POST /teams/{id}/leave             : 멤버 (팀 나가기 + 팀장 자동 승계, §7.2)
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_team_leader, require_team_member
from app.core.errors import ApiError
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


# ── 팀 나가기 + 팀장 자동 승계 (작업 4-4, db-schema §7.2 · D5) ──────────

@router.post("/{team_id}/leave", status_code=204)
def leave_team(
    team: models.Team = Depends(require_team_member),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """팀 나가기(멤버 누구나). 단일 트랜잭션 — DEFERRABLE FK가 커밋 시점에
    '팀장 ∈ 멤버'를 강제하므로 UPDATE/DELETE 순서는 자유롭다 (db-schema §7.2).

    - 비팀장         : 내 멤버십만 삭제
    - 팀장 + 후임 있음: 최고참(joined_at→user_id) 승계 후 내 멤버십 삭제
    - 팀장 + 마지막 1인: 팀 삭제 (세션·멤버십·초대 CASCADE)
    """
    # 같은 팀의 나가기/내보내기를 직렬화 — 팀 행에 잠금(FOR UPDATE)을 걸고 리더를 새로 읽는다.
    # 없으면 '리더 나가기(승계)'와 '다른 멤버 나가기'가 겹칠 때 커밋 시점 FK 위반(500)이 난다.
    db.refresh(team, with_for_update=True)
    membership = db.get(models.TeamMember, (team.id, user.id))  # 멤버임은 가드가 보장

    if team.leader_id != user.id:
        db.delete(membership)
        db.commit()
        return

    # 팀장 이탈 → 본인 제외 최고참을 후임으로 (db-schema §7.2 쿼리 그대로)
    successor_id = db.scalar(
        select(models.TeamMember.user_id)
        .where(models.TeamMember.team_id == team.id,
               models.TeamMember.user_id != user.id)
        .order_by(models.TeamMember.joined_at, models.TeamMember.user_id)
        .limit(1)
    )
    if successor_id is None:
        db.delete(team)          # 마지막 1인 → 팀 통째로 CASCADE
    else:
        team.leader_id = successor_id
        db.delete(membership)    # 커밋 시 후임이 멤버로 남아 있어 FK 통과
    db.commit()


# ── 멤버 (작업 4-3, api-spec §3) ──────────────────────────────────────

@router.get("/{team_id}/members", response_model=list[TeamMemberInfo])
def list_members(
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> list[TeamMemberInfo]:
    """팀원 목록(멤버 누구나). 상세(GET /teams/{id})의 members와 동일 형태·정렬."""
    return _list_members(team, db)


@router.delete("/{team_id}/members/{user_id}", status_code=204)
def remove_member(
    user_id: str,
    team: models.Team = Depends(require_team_leader),
    db: Session = Depends(get_db),
) -> None:
    """팀원 내보내기(팀장 전용). 팀장 자신은 내보낼 수 없다 —
    '팀장 ∈ 멤버' DEFERRABLE FK를 깨므로. 팀을 뜨려면 /leave(위임 후)로."""
    db.refresh(team, with_for_update=True)  # leave와 동일 잠금 — 승계 레이스 직렬화
    if user_id == team.leader_id:
        raise ApiError(400, "CANNOT_REMOVE_LEADER",
                       "팀장은 내보낼 수 없어요. 팀을 나가려면 팀 나가기로 위임하세요.")
    membership = db.get(models.TeamMember, (team.id, user_id))
    if membership is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "해당 팀원을 찾을 수 없어요.")
    db.delete(membership)
    db.commit()


def _list_members(team: models.Team, db: Session) -> list[TeamMemberInfo]:
    """팀원 목록(가입순 → user_id) + is_leader 플래그. 상세·멤버목록이 공유."""
    rows = db.execute(
        select(models.User.id, models.User.name, models.User.username)
        .join(models.TeamMember, models.TeamMember.user_id == models.User.id)
        .where(models.TeamMember.team_id == team.id)
        .order_by(models.TeamMember.joined_at, models.User.id)
    ).all()
    return [
        TeamMemberInfo(id=r.id, name=r.name, username=r.username,
                       is_leader=(r.id == team.leader_id))
        for r in rows
    ]


def _to_detail(team: models.Team, db: Session) -> TeamDetail:
    """팀 상세 응답 구성 — 멤버 목록(가입순) + 발표 수."""
    session_count = db.scalar(
        select(func.count()).select_from(models.RehearsalSession)
        .where(models.RehearsalSession.team_id == team.id)
    )
    return TeamDetail(
        id=team.id, name=team.name, leader_id=team.leader_id,
        session_count=session_count, members=_list_members(team, db),
        created_at=team.created_at,
    )
