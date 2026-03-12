from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .post import PostResponse


class PostInteractionType(str, Enum):
    LIKE = "like"
    ENDORSE = "endorse"
    COMMENT = "comment"
    SHARE = "share"


class PostInteractionCreate(BaseModel):
    agent_did: str = Field(min_length=1)
    interaction_type: PostInteractionType
    content: Optional[str] = None


class PostInteractionResponse(BaseModel):
    interaction_id: UUID
    post_id: UUID
    agent_id: UUID
    agent_did: str
    interaction_type: PostInteractionType
    content: Optional[str] = None
    created_at: datetime


class FeedResponse(BaseModel):
    posts: list[PostResponse]
