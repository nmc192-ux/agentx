"""
AgentX Platform — Task Marketplace Pydantic Models
════════════════════════════════════════════════════
Phase 4: Agent Task Economy

Models for the open marketplace bidding system.
Distinct from agent_task.py (direct assignment) models.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """Request body for publishing a new marketplace task."""
    creator_agent_did: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None
    reward: int = Field(default=0, ge=0)


class TaskBid(BaseModel):
    """Request body for an agent bidding on a marketplace task."""
    agent_did: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    bid_price: int = Field(default=0, ge=0)


class TaskResult(BaseModel):
    """Request body for an agent submitting task results."""
    agent_did: str = Field(min_length=1)
    result_payload: dict = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """Marketplace task response shape."""
    task_id: UUID
    creator_agent_id: Optional[UUID]
    task_type: str
    payload: Optional[dict]
    reward: int
    status: str
    created_at: datetime


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


class TaskVerdict(BaseModel):
    """Request body for verifying a task result."""
    verdict: str = Field(..., pattern="^(approved|rejected)$")
    feedback: Optional[str] = None


class TaskResultResponse(BaseModel):
    """Task result record response shape."""
    result_id: UUID
    task_id: UUID
    agent_id: UUID
    result_payload: dict
    verification_status: str
    feedback: Optional[str] = None
    verified_by_did: Optional[str] = None
    verified_at: Optional[datetime] = None
    created_at: datetime
