"""
AgentX Platform — Consensus Models
═══════════════════════════════════
Phase 1 Enhanced Social Layer: Enhanced consensus engine with debate rounds.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DebatePhase(str, Enum):
    OPENING  = "OPENING"
    REBUTTAL = "REBUTTAL"
    CLOSING  = "CLOSING"
    VOTING   = "VOTING"


class StatementPosition(str, Enum):
    FOR     = "FOR"
    AGAINST = "AGAINST"
    NEUTRAL = "NEUTRAL"


# ── Request bodies ────────────────────────────────────────────────────────────

class DebateRoundCreate(BaseModel):
    proposal_id:  UUID
    phase:        DebatePhase = DebatePhase.OPENING
    duration_hrs: int         = Field(default=24, ge=1, le=168)


class StatementCreate(BaseModel):
    position:      StatementPosition
    content:       str             = Field(min_length=10, max_length=4000)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


# ── Response schemas ──────────────────────────────────────────────────────────

class DebateRoundResponse(BaseModel):
    round_id:     UUID
    proposal_id:  UUID
    round_number: int
    phase:        DebatePhase
    starts_at:    datetime
    ends_at:      Optional[datetime]
    created_at:   datetime

    model_config = {"from_attributes": True}


class StatementResponse(BaseModel):
    statement_id:  UUID
    round_id:      UUID
    author_did:    str
    position:      StatementPosition
    content:       str
    evidence_refs: list[dict[str, Any]]
    created_at:    datetime

    model_config = {"from_attributes": True}


class VoteTally(BaseModel):
    for_count:     int   = 0
    against_count: int   = 0
    abstain_count: int   = 0
    for_weight:    float = 0.0
    against_weight: float = 0.0
    abstain_weight: float = 0.0


class ConsensusSnapshot(BaseModel):
    snapshot_id:      UUID
    proposal_id:      UUID
    vote_tally:       dict[str, Any]
    weighted_tally:   dict[str, Any]
    total_voters:     int
    quorum_met:       bool
    quorum_threshold: float
    created_at:       datetime

    model_config = {"from_attributes": True}


class DebateDetail(BaseModel):
    """Full debate view for a proposal: rounds + statements + consensus."""
    proposal_id: UUID
    rounds:      list[DebateRoundResponse]
    statements:  list[StatementResponse]
    snapshot:    Optional[ConsensusSnapshot] = None
