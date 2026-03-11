from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
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
