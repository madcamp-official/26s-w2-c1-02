from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .common import PresentationType


# ── 구버전(mock speeches 플로우 호환용) — 삭제하지 않음 ──
class TeamCreate(BaseModel):
    name: str = Field(..., max_length=20)  # 팀 이름 20자 이내
    type: PresentationType
    member_names: list[str] = Field(default_factory=list)


class Team(BaseModel):
    id: str
    name: str
    type: PresentationType
    member_names: list[str]


# ── v0.3 실 API (api-spec §3, db-schema §3.2·§8.3) ──

def _strip_name(v: object) -> object:
    return v.strip() if isinstance(v, str) else v


class TeamCreateRequest(BaseModel):
    """POST /teams (api-spec §3)."""

    name: str = Field(min_length=1, max_length=20)
    _strip = field_validator("name", mode="before")(_strip_name)


class TeamUpdateRequest(BaseModel):
    """PATCH /teams/{id} — 팀 이름 변경."""

    name: str = Field(min_length=1, max_length=20)
    _strip = field_validator("name", mode="before")(_strip_name)


class TeamCard(BaseModel):
    """GET /teams 목록 항목 (db-schema §8.3 쿼리 결과)."""

    id: str
    name: str
    session_count: int
    members_preview: str  # "박준서, 이서진" — 탈퇴자는 '탈퇴한 사용자'


class TeamListOut(BaseModel):
    """GET /teams 응답 봉투 (api-spec §1.2: 목록은 { items } 형태 — FE 계약)."""

    items: list[TeamCard]


class TeamMemberInfo(BaseModel):
    id: str
    name: str | None       # 탈퇴(익명화) 유저는 None
    username: str | None
    is_leader: bool


class TeamDetail(BaseModel):
    """GET /teams/{id} 상세 (팀원 목록 포함)."""

    id: str
    name: str
    leader_id: str
    session_count: int
    members: list[TeamMemberInfo]
    created_at: datetime
