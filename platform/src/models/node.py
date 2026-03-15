"""
AgentX Platform — Federated Node Models
════════════════════════════════════════
Phase 17: Pydantic schemas for federated node management.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RegisterNodeRequest(BaseModel):
    """Body for POST /nodes/register."""
    node_url: str = Field(..., min_length=1, max_length=500, description="Public URL of the peer node")
    node_name: str | None = Field(default=None, max_length=100, description="Human-readable name")
    public_key: str | None = Field(default=None, max_length=2000, description="Node public key (PEM / JWK)")


class NodeResponse(BaseModel):
    """Response model for a single registered node."""
    node_id: UUID
    node_url: str
    node_name: str | None = None
    public_key: str | None = None
    status: str = "active"
    trust_level: float = 0.5
    registered_at: datetime
    last_seen_at: datetime | None = None


class NodeMessageResponse(BaseModel):
    """Response model for a logged federated message."""
    message_id: UUID
    node_id: UUID | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    direction: str = "inbound"
    created_at: datetime


class FederatedEventRequest(BaseModel):
    """Body for POST /nodes/events — inbound event from a peer node."""
    event_type: str = Field(..., min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    source_node_url: str | None = Field(default=None, max_length=500)
