from pydantic import BaseModel, Field

from .common import AudienceType


class SpeechCreate(BaseModel):
    name: str
    material_file_name: str | None = None
    audience_type: AudienceType = AudienceType.teto
    audience_detail: str | None = None
    question_count: int = Field(default=3, ge=1, le=20)
    duration_minutes: int = Field(default=5, ge=1)


class Speech(BaseModel):
    id: str
    team_id: str
    name: str
    material_file_name: str | None = None
    audience_type: AudienceType = AudienceType.teto
    audience_detail: str | None = None
    question_count: int = 3
    duration_minutes: int = 5
