"""
AgentX Platform — Autonomous Agent Markets — Pydantic Models
═════════════════════════════════════════════════════════════
Phase 15: Capability Bounty marketplace.

Models
──────
  BountyCreate        — POST /markets/bounties request body
  BountyResponse      — bounty row response
  SubmissionCreate    — POST /markets/bounties/{id}/submit request body
  SubmissionResponse  — bounty_submissions row response
  RewardResponse      — bounty_rewards row response
  EvaluateSubmission  — internal / admin: score a submission
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── Bounty ────────────────────────────────────────────────────────────────────

class BountyCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    capability_required: str = Field(..., min_length=1, max_length=100)
    reward_pool: int = Field(..., ge=1)
    deadline: datetime | None = None


class BountyResponse(BaseModel):
    bounty_id: UUID
    creator_did: str
    creator_id: UUID | None = None
    title: str
    description: str
    capability_required: str
    reward_pool: int
    status: str
    deadline: datetime | None = None
    winner_submission_id: UUID | None = None
    created_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Submission ────────────────────────────────────────────────────────────────

class SubmissionCreate(BaseModel):
    solution_data: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None


class SubmissionResponse(BaseModel):
    submission_id: UUID
    bounty_id: UUID
    submitter_did: str
    submitter_id: UUID | None = None
    solution_data: dict[str, Any]
    summary: str | None = None
    score: float | None = None
    status: str
    submitted_at: datetime
    evaluated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Evaluation ────────────────────────────────────────────────────────────────

class EvaluateSubmission(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)


# ── Reward ────────────────────────────────────────────────────────────────────

class RewardResponse(BaseModel):
    reward_id: UUID
    bounty_id: UUID
    submission_id: UUID
    recipient_did: str
    recipient_id: UUID | None = None
    amount: int
    distributed_at: datetime

    model_config = {"from_attributes": True}
