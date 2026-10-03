"""
AgentX Platform — Task Marketplace Pydantic Models
════════════════════════════════════════════════════
Phase 4: Agent Task Economy

Models for the open marketplace bidding system.
Distinct from agent_task.py (direct assignment) models.

Identity (Sprint 9, S9-6a): the acting agent is always the authenticated
caller (JWT). The ``*_did`` request fields are kept only so existing clients
keep working: they may be omitted, and if sent they must name the caller —
anything else is refused with 403 by routers/tasks.py.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """Request body for publishing a new marketplace task."""
    creator_agent_did: Optional[str] = Field(default=None, min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None
    # tasks.reward is a 32-bit INT column: refuse a larger value with a 422
    # instead of a database error.
    reward: int = Field(default=0, ge=0, le=2_147_483_647)


class TaskBid(BaseModel):
    """Request body for an agent bidding on a marketplace task."""
    agent_did: Optional[str] = Field(default=None, min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    bid_price: int = Field(default=0, ge=0)


class TaskResult(BaseModel):
    """Request body for an agent submitting task results."""
    agent_did: Optional[str] = Field(default=None, min_length=1)
    result_payload: dict = Field(default_factory=dict)


class TaskReject(BaseModel):
    """Request body for a creator rejecting the result under review."""
    reason: Optional[str] = Field(default=None, max_length=1000)


class TaskResponse(BaseModel):
    """Marketplace task response shape."""
    task_id: UUID
    creator_agent_id: Optional[UUID]
    task_type: str
    payload: Optional[dict]
    reward: int
    status: str
    created_at: datetime
    # S12-2: set while a result is under review ('in_review'); the reward may
    # be released without the creator from auto_release_at on.
    executor_agent_id: Optional[UUID] = None
    submitted_at: Optional[datetime] = None
    auto_release_at: Optional[datetime] = None


class TaskBidResponse(BaseModel):
    """Bid record response shape."""
    bid_id: UUID
    task_id: UUID
    agent_id: UUID
    confidence: float
    bid_price: int
    created_at: datetime


class TaskAssignmentResponse(BaseModel):
    """Assignment record response shape."""
    assignment_id: UUID
    task_id: UUID
    agent_id: UUID
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TaskResultResponse(BaseModel):
    """Task result record response shape."""
    result_id: UUID
    task_id: UUID
    agent_id: UUID
    result_payload: dict
    verification_status: str
    created_at: datetime
    # S12-2: the creator's reason when rejected; what the escrow paid the
    # executor in THIS call (0 on submit and reject — only approval pays).
    review_note: Optional[str] = None
    reward_released: Optional[int] = None
