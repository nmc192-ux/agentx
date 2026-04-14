"""
AgentX Platform — Room Models
═════════════════════════════
Phase 1 Enhanced Social Layer: Collaboration rooms.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoomType(str, Enum):
    WORKSHOP   = "WORKSHOP"
    WAR_ROOM   = "WAR_ROOM"
    REVIEW     = "REVIEW"
    BRAINSTORM = "BRAINSTORM"


class RoomStatus(str, Enum):
    OPEN        = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED      = "CLOSED"
    ARCHIVED    = "ARCHIVED"


class ParticipantRole(str, Enum):
    HOST        = "HOST"
    PARTICIPANT = "PARTICIPANT"
    OBSERVER    = "OBSERVER"


class ArtifactType(str, Enum):
    NOTE        = "NOTE"
    CODE        = "CODE"
    DIAGRAM     = "DIAGRAM"
    LOG         = "LOG"
    WORKFLOW    = "WORKFLOW"
    RAG_SNIPPET = "RAG_SNIPPET"


# ── Request bodies ────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    name:             str            = Field(min_length=2, max_length=128)
    description:      str            = Field(default="", max_length=1000)
    community_id:     Optional[UUID] = None
    room_type:        RoomType       = RoomType.WORKSHOP
    max_participants: int            = Field(default=12, ge=2, le=50)


class ArtifactCreate(BaseModel):
    artifact_type: ArtifactType = ArtifactType.NOTE
    title:         str          = Field(default="", max_length=200)
    content:       dict[str, Any] = Field(default_factory=dict)


# ── Response schemas ──────────────────────────────────────────────────────────

class RoomResponse(BaseModel):
    room_id:          UUID
    name:             str
    description:      str
    community_id:     Optional[UUID]
    room_type:        RoomType
    status:           RoomStatus
    max_participants: int
    creator_did:      str
    participant_count: int = 0
    created_at:       datetime
    closed_at:        Optional[datetime] = None

    model_config = {"from_attributes": True}


class RoomParticipant(BaseModel):
    room_id:   UUID
    agent_did: str
    role:      ParticipantRole
    joined_at: datetime

    model_config = {"from_attributes": True}


class ArtifactResponse(BaseModel):
    artifact_id:   UUID
    room_id:       UUID
    author_did:    str
    artifact_type: ArtifactType
    title:         str
    content:       dict[str, Any]
    created_at:    datetime

    model_config = {"from_attributes": True}
