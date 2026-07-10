from fastapi import APIRouter, HTTPException

from app.db.store import store
from app.schemas.speech import Speech, SpeechCreate
from app.schemas.team import Team, TeamCreate

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[Team])
async def list_teams() -> list[Team]:
    return store.list_teams()


@router.post("", response_model=Team, status_code=201)
async def create_team(payload: TeamCreate) -> Team:
    # 생성자 본인(user)은 항상 포함. 팀 이름 중복은 허용.
    members = ["user", *[m for m in payload.member_names if m != "user"]]
    team = Team(
        id=store.next_team_id(),
        name=payload.name,
        type=payload.type,
        member_names=members,
    )
    return store.add_team(team)


@router.get("/{team_id}", response_model=Team)
async def get_team(team_id: str) -> Team:
    team = store.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="team not found")
    return team


@router.delete("/{team_id}", status_code=204)
async def leave_team(team_id: str) -> None:
    if store.get_team(team_id) is None:
        raise HTTPException(status_code=404, detail="team not found")
    store.remove_team(team_id)


@router.get("/{team_id}/speeches", response_model=list[Speech])
async def list_speeches(team_id: str) -> list[Speech]:
    if store.get_team(team_id) is None:
        raise HTTPException(status_code=404, detail="team not found")
    return store.list_speeches(team_id)


@router.post("/{team_id}/speeches", response_model=Speech, status_code=201)
async def create_speech(team_id: str, payload: SpeechCreate) -> Speech:
    if store.get_team(team_id) is None:
        raise HTTPException(status_code=404, detail="team not found")
    speech = Speech(
        id=store.next_speech_id(),
        team_id=team_id,
        **payload.model_dump(),
    )
    return store.add_speech(speech)
