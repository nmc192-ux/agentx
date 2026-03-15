"""Pydantic models for the Result Verification Engine (Phase 12)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────


class VerificationCreate(BaseModel):
    contract_id: UUID = Field(..., description="UUID of the contract whose result is being verified")
    result_id: UUID = Field(..., description="UUID of the contract result to verify")


class VerificationVoteCreate(BaseModel):
    vote: str = Field(..., pattern=r"^(approve|reject)$", description="'approve' or 'reject'")
    comment: Optional[str] = Field(default=None, description="Optional justification for the vote")


# ──────────────────────────────────────────────────────────────────────────────
# Response models
# ──────────────────────────────────────────────────────────────────────────────


class VerificationResponse(BaseModel):
    verification_id: UUID
    contract_id: UUID
    result_id: UUID
    requester_did: str
    requester_id: Optional[UUID] = None
    status: str                          # pending | active | verified | failed
    required_votes: int
    consensus_threshold: float
    yes_power: float
    no_power: float
    vote_count: int
    reward_pool: int
    created_at: datetime
    finalized_at: Optional[datetime] = None


class VerificationVoteResponse(BaseModel):
    vote_id: UUID
    verification_id: UUID
    verifier_did: str
    vote: str                            # approve | reject
    vote_power: float
    comment: Optional[str] = None
    created_at: datetime


class VerificationConsensusResponse(BaseModel):
    verification_id: UUID
    yes_power: float
    no_power: float
    vote_count: int
    required_votes: int
    consensus_threshold: float
    yes_ratio: float
    outcome: Optional[str] = None        # 'verified' | 'failed' | None (insufficient votes)
