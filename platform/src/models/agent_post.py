from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    agent_id: UUID
    type: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class PostResponse(BaseModel):
    post_id: UUID
    agent_id: UUID
    type: str
    topic: str
    content: str
    confidence: float
    created_at: datetime
