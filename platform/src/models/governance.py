"""Pydantic models for the Governance layer (Phase 9)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Sprint 9 (S9-8): a proposal is public text anyone logged in can post, so
# every free-form part of it is bounded.
MAX_DESCRIPTION_CHARS = 10_000
MAX_PAYLOAD_BYTES = 16 * 1024


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────


class ProposalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    proposal_type: str = Field(default="general", pattern=r"^[A-Za-z0-9_]{1,40}$")
    payload: Optional[dict] = None
    voting_days: int = Field(default=7, gt=0, le=30)

    @field_validator("payload")
    @classmethod
    def _payload_is_small(cls, value: Optional[dict]) -> Optional[dict]:
        if value is None:
            return value
        try:
            size = len(json.dumps(value).encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be plain JSON") from exc
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")
        return value


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
    # Sprint 9 (S9-8): the tally in full. Abstentions carry weight towards the
    # quorum; the *_votes fields are head counts (what the UI shows).
    abstain_power: float = 0.0
    yes_votes: int = 0
    no_votes: int = 0
    abstain_votes: int = 0
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
