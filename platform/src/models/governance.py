"""Pydantic models for the Governance layer (Phase 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────


class ProposalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    proposal_type: str = Field(default="general")
    payload: Optional[dict] = None
    voting_days: int = Field(default=7, gt=0, le=30)


class VoteRequest(BaseModel):
    proposal_id: UUID
    vote: str = Field(..., pattern=r"^(yes|no|abstain)$")


# ──────────────────────────────────────────────────────────────────────────────
# Response models
# ──────────────────────────────────────────────────────────────────────────────


class ProposalResponse(BaseModel):
    proposal_id: UUID
    proposer_did: str
    proposer_id: Optional[UUID] = None
    title: str
    description: str
    proposal_type: str
    status: str
    payload: Optional[dict] = None
    yes_power: float
    no_power: float
    voting_ends_at: datetime
    created_at: datetime


class VoteResponse(BaseModel):
    vote_id: UUID
    proposal_id: UUID
    voter_did: str
    vote: str
    vote_power: float
    created_at: datetime


class GovernanceParameterResponse(BaseModel):
    param_id: UUID
    name: str
    value: str
    description: Optional[str] = None
    updated_at: datetime
