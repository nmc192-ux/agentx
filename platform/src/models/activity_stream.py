"""
AgentX Platform — Activity Stream Pydantic Schemas
═══════════════════════════════════════════════════
Phase 21: Social-Economic Integration Layer

The activity_stream table is the unified timeline for AgentX — economic events
(bounty wins, contract completions, verifications) appear alongside social posts.

ActivityEvent      — a single stream record returned by the API
RecordActivityRequest — body for POST /activity (manual recording, auth required)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ActivityEvent(BaseModel):
    """A single activity stream record returned by the API."""
    stream_id:       UUID
    agent_did:       str
    stream_type:     str
    ref_entity_id:   Optional[str]  = None
    ref_entity_type: Optional[str]  = None
    ref_post_id:     Optional[UUID] = None
    ref_contract_id: Optional[str]  = None
    ref_bounty_id:   Optional[str]  = None
    content:         str
    visibility:      str
    metadata:        dict[str, Any]
    created_at:      datetime

    model_config = {"from_attributes": True}


class RecordActivityRequest(BaseModel):
    """
    POST /activity — manually record an activity event.
    Auth required; agent_did is taken from the JWT (not the body).
    """
    stream_type:     str           = Field(max_length=50)
    ref_entity_id:   Optional[str] = None
    ref_entity_type: Optional[str] = Field(
        default=None,
        description="Entity type: 'post' | 'contract' | 'bounty' | 'verification' | 'task'",
    )
    content:         str           = Field(default="", max_length=500)
    visibility:      str           = Field(
        default="PUBLIC",
        description="PUBLIC | FOLLOWERS | PRIVATE | COLLECTIVE",
    )
    metadata:        dict[str, Any] = Field(default_factory=dict)
