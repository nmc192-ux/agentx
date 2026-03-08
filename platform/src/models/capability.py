"""
AgentX Platform — Capability Pydantic Schemas
═════════════════════════════════════════════
SOURCE: capability_registry_spec.json — ATLAS Phase 1
"""
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Pattern ───────────────────────────────────────────────────────────────────
_CAP_PATTERN = re.compile(
    r"^[a-z]+\.[a-z0-9_]+\.(basic|intermediate|advanced|expert)$"
)


# ── Enumerations ──────────────────────────────────────────────────────────────

class CapabilityDomain(str, Enum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    FRONTEND       = "FRONTEND"
    SECURITY       = "SECURITY"
    DATA           = "DATA"
    ML             = "ML"
    GOVERNANCE     = "GOVERNANCE"
    CREATIVE       = "CREATIVE"
    QA             = "QA"
    PROTOCOL       = "PROTOCOL"
    ANALYTICS      = "ANALYTICS"


class CapabilityLevel(str, Enum):
    BASIC        = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED     = "ADVANCED"
    EXPERT       = "EXPERT"


# ── Schema models ─────────────────────────────────────────────────────────────

class CapabilityResponse(BaseModel):
    """Capability record returned by GET /capabilities."""
    capability_id:        str
    name:                 str
    description:          str
    domain:               CapabilityDomain
    level:                CapabilityLevel
    requires_verification: bool
    rep_reward:           int
    prerequisites:        list[str]
    verified_by:          list[str]
    created_at:           datetime

    model_config = {"from_attributes": True}


class AgentCapabilityCreate(BaseModel):
    """POST /agents/{did}/capabilities — add capability to agent."""
    capability_id: str = Field(description="e.g. infrastructure.kubernetes.advanced")

    @field_validator("capability_id")
    @classmethod
    def valid_capability_id(cls, v: str) -> str:
        if not _CAP_PATTERN.match(v):
            raise ValueError(
                f"Invalid capability_id {v!r}. "
                "Expected: domain.skill.(basic|intermediate|advanced|expert)"
            )
        return v


class AgentCapabilityResponse(BaseModel):
    """Agent's capability entry — returned by GET /agents/{did}/capabilities."""
    capability_id:    str
    name:             str
    domain:           CapabilityDomain
    level:            CapabilityLevel
    verified:         bool
    verified_by_count: int
    acquired_at:      datetime

    model_config = {"from_attributes": True}


class CapabilityVerifyRequest(BaseModel):
    """POST /agents/{did}/capabilities/{cap_id}/verify — peer endorsement."""
    endorser_did: str = Field(description="DID of agent providing the endorsement")
    notes:        Optional[str] = Field(default=None, max_length=500)


class CapabilityListResponse(BaseModel):
    """Paginated capability list."""
    capabilities: list[CapabilityResponse]
    total:        int
    page:         int
    limit:        int
