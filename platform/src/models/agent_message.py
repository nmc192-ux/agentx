from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    sender_agent_did: str = Field(min_length=1)
    receiver_agent_did: str = Field(min_length=1)
    message: str = Field(min_length=1)
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    message_id: UUID
    sender_agent_did: str
    receiver_agent_did: str
    message: str
    metadata: Optional[dict] = None
    created_at: datetime
