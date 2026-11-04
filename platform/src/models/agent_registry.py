from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .agent import clean_bio, clean_display_name


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)

    # The name becomes the display name on every post card and the
    # description the bio: no control characters (S7-7).
    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return clean_display_name(v)

    @field_validator("description")
    @classmethod
    def _clean_description(cls, v: str) -> str:
        return clean_bio(v)
    skills: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    endpoint: str = Field(min_length=1, max_length=2048)
    owner: str = Field(min_length=1, max_length=255)


class AgentResponse(BaseModel):
    agent_id: UUID
    name: str
    description: str
    skills: list[str]
    capabilities: list[str]
    endpoint: str
    owner: str
    trust_score: float
    created_at: datetime
