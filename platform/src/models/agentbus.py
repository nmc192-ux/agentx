"""Pydantic models for the Agent Bus (Phase 11)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────


class AgentMessageCreate(BaseModel):
    receiver_did: str = Field(..., min_length=1, description="DID of the message recipient")
    content: str = Field(..., min_length=1, description="Message body")
    channel: str = Field(default="default", description="Channel name (default: 'default')")
    metadata: Optional[dict] = Field(default=None, description="Arbitrary metadata payload")


class AgentChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Response models
# ──────────────────────────────────────────────────────────────────────────────


class AgentMessageResponse(BaseModel):
    message_id: UUID
    sender_did: str
    receiver_did: str
    content: str
    channel: str
    status: str
    metadata: Optional[dict] = None
    created_at: datetime


class AgentChannelResponse(BaseModel):
    channel_id: UUID
    name: str
    description: Optional[str] = None
    created_by: str
    created_at: datetime


class AgentSessionResponse(BaseModel):
    session_id: UUID
    agent_did: str
    session_token: str
    connected_at: datetime
    last_seen: datetime
    expires_at: Optional[datetime] = None
    is_active: bool
