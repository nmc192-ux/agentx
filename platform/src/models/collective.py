"""
AgentX Platform — Collective Pydantic Schemas
═════════════════════════════════════════════
Collectives are groups of agents that share visibility scope,
governance, and collective trust scores.

SOURCE: agentx_db_schema.sql — ATLAS Phase 1
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class MemberRole(str, Enum):
    OWNER  = "OWNER"
    ADMIN  = "ADMIN"
    MEMBER = "MEMBER"


class MemberStatus(str, Enum):
    PENDING  = "PENDING"
    ACTIVE   = "ACTIVE"
    BANNED   = "BANNED"


# ── Schema models ─────────────────────────────────────────────────────────────

class CollectiveCreate(BaseModel):
    """POST /collectives — create a new collective."""
    name:        str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    charter:     Optional[str] = Field(default=None, max_length=5000)
    is_public:   bool = True


class CollectiveMemberResponse(BaseModel):
    """Single member entry in a collective."""
    agent_did:   str
    display_name: str
    role:         MemberRole
    status:       MemberStatus
    trust_score:  float
    joined_at:    datetime

    model_config = {"from_attributes": True}


class CollectiveResponse(BaseModel):
    """Collective profile returned by GET /collectives/{id}."""
    collective_id:   UUID
    name:            str
    description:     str
    charter:         Optional[str]
    is_public:       bool
    owner_did:       str
    member_count:    int
    trust_score_avg: float
    created_at:      datetime

    model_config = {"from_attributes": True}


class CollectiveWithMembers(CollectiveResponse):
    """Extended collective profile including member list."""
    members: list[CollectiveMemberResponse] = []


class CollectiveListResponse(BaseModel):
    """Paginated collective list."""
    collectives: list[CollectiveResponse]
    total:       int
    page:        int
    limit:       int
    has_more:    bool


class JoinRequest(BaseModel):
    """POST /collectives/{id}/join — request membership."""
    message: Optional[str] = Field(default=None, max_length=500)
