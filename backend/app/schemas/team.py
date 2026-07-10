from pydantic import BaseModel, Field

from .common import PresentationType


class TeamCreate(BaseModel):
    name: str = Field(..., max_length=20)  # 팀 이름 20자 이내
    type: PresentationType
    member_names: list[str] = Field(default_factory=list)


class Team(BaseModel):
    id: str
    name: str
    type: PresentationType
    member_names: list[str]
