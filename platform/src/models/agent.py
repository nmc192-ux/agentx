"""
AgentX Platform — Agent Pydantic Schemas
═════════════════════════════════════════
Request and response models for the /agents API.
Uses Pydantic v2 — validates against agent_identity_schema_v3.json constraints.

SOURCE: agent_identity_schema_v3.json — ATLAS Phase 1
"""
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enumerations (mirror database ENUM types) ─────────────────────────────────

class AgentType(str, Enum):
    AUTONOMOUS  = "AUTONOMOUS"
    SUPERVISED  = "SUPERVISED"
    HYBRID      = "HYBRID"


class GovernanceRole(str, Enum):
    FOUNDER   = "FOUNDER"
    OPERATOR  = "OPERATOR"
    DELEGATE  = "DELEGATE"
    MEMBER    = "MEMBER"
    OBSERVER  = "OBSERVER"


class AgentTier(str, Enum):
    BOOTSTRAP    = "BOOTSTRAP"
    BASIC        = "BASIC"
    PROFESSIONAL = "PROFESSIONAL"
    ELITE        = "ELITE"


class AgentStatus(str, Enum):
    ACTIVE         = "ACTIVE"
    SUSPENDED      = "SUSPENDED"
    DEACTIVATED    = "DEACTIVATED"
    PENDING_REVIEW = "PENDING_REVIEW"


# ── DID pattern ───────────────────────────────────────────────────────────────
_DID_PATTERN = re.compile(r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")


# ── Trust score breakdown ─────────────────────────────────────────────────────

class TrustScoreBreakdown(BaseModel):
    """
    5-factor trust score breakdown.
    Weights: execution_success(35%) + sla_compliance(25%) +
             peer_endorsements(20%) + audit_transparency(12%) + security_record(8%)
    """
    execution_success:  float = Field(ge=0.0, le=1.0)
    sla_compliance:     float = Field(ge=0.0, le=1.0)
    peer_endorsements:  float = Field(ge=0.0, le=1.0)
    audit_transparency: float = Field(ge=0.0, le=1.0)
    security_record:    float = Field(ge=0.0, le=1.0)
    composite:          float = Field(ge=0.0, le=1.0)


# ── API Schemas ───────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    """POST /agents request body."""
    agent_did:    str = Field(description="W3C DID in did:agentx:<name>-<seq> format")
    display_name: str = Field(min_length=1, max_length=64)
    agent_type:   AgentType   = AgentType.AUTONOMOUS
    governance_role: GovernanceRole = GovernanceRole.MEMBER
    bio:          Optional[str] = Field(default=None, max_length=512)
    specialization: Optional[str] = Field(default=None, max_length=128)

    @field_validator("agent_did")
    @classmethod
    def validate_did(cls, v: str) -> str:
        if not _DID_PATTERN.match(v):
            raise ValueError(
                f"Invalid DID format '{v}'. "
                "Expected: did:agentx:<name>-<NNN> (e.g. did:agentx:atlas-001)"
            )
        return v


class AgentUpdate(BaseModel):
    """PATCH /agents/{did} request body — all fields optional."""
    display_name:   Optional[str] = Field(default=None, min_length=1, max_length=64)
    bio:            Optional[str] = Field(default=None, max_length=512)
    specialization: Optional[str] = Field(default=None, max_length=128)
    status:         Optional[AgentStatus] = None


class AgentResponse(BaseModel):
    """Public agent profile returned by GET /agents and GET /agents/{did}."""
    agent_did:      str
    display_name:   str
    agent_type:     AgentType
    governance_role: GovernanceRole
    tier:           AgentTier
    status:         AgentStatus
    trust_score:    float
    bio:            Optional[str]
    specialization: Optional[str]
    created_at:     datetime
    last_seen_at:   Optional[datetime]
    # Phase 21: Economic profile metrics
    posts_count:          int   = 0
    bounties_won:         int   = 0
    contracts_completed:  int   = 0
    verifications_passed: int   = 0
    eco_influence_score:  float = 0.0

    model_config = {"from_attributes": True}


class AgentWithTrust(AgentResponse):
    """Extended profile that includes trust score breakdown."""
    trust_breakdown: Optional[TrustScoreBreakdown] = None


class AgentListResponse(BaseModel):
    """Paginated agent list."""
    agents:  list[AgentResponse]
    total:   int
    page:    int
    limit:   int
    has_more: bool


class TokenResponse(BaseModel):
    """JWT token pair returned after creating an agent or logging in."""
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int           # seconds until access token expiry
    agent_did:     str
