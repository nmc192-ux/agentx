"""
AgentX Platform — Swarm Pydantic Models
════════════════════════════════════════
Phase 4: Multi-agent coordination

Swarm strategies:
  parallel    — all subtasks run concurrently, results aggregated
  pipeline    — subtasks execute in sequence, each feeding the next
  consensus   — all members work the same task, majority result wins
  competitive — all members race, first acceptable result wins
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SwarmStrategy(str, Enum):
    PARALLEL = "parallel"
    PIPELINE = "pipeline"
    CONSENSUS = "consensus"
    COMPETITIVE = "competitive"


class SwarmStatus(str, Enum):
    FORMING = "forming"
    ACTIVE = "active"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemberRole(str, Enum):
    COORDINATOR = "coordinator"
    WORKER = "worker"
    VERIFIER = "verifier"


# ── Request Models ────────────────────────────────────────────────────────────

class SwarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    strategy: SwarmStrategy = SwarmStrategy.PARALLEL
    max_members: int = Field(default=10, ge=2, le=50)
    reward_pool: int = Field(default=0, ge=0)
    required_capabilities: list[str] = Field(default_factory=list)
    subtasks: list["SubtaskCreate"] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class SubtaskCreate(BaseModel):
    task_type: str = Field(min_length=1)
    description: str = Field(default="")
    payload: dict = Field(default_factory=dict)
    sequence: int = Field(default=0, ge=0)


class SubtaskResultSubmit(BaseModel):
    result: dict = Field(default_factory=dict)


# ── Response Models ───────────────────────────────────────────────────────────

class SwarmMemberResponse(BaseModel):
    agent_did: str
    role: str
    status: str
    subtask_id: Optional[UUID] = None
    joined_at: datetime


class SubtaskResponse(BaseModel):
    subtask_id: UUID
    swarm_id: UUID
    task_type: str
    description: Optional[str] = None
    payload: dict
    sequence: int
    assigned_did: Optional[str] = None
    status: str
    result: Optional[dict] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class SwarmResponse(BaseModel):
    swarm_id: UUID
    name: str
    coordinator_did: str
    objective: str
    strategy: str
    max_members: int
    reward_pool: int
    status: str
    required_capabilities: list[str]
    member_count: int = 0
    subtask_count: int = 0
    completed_subtasks: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SwarmDetailResponse(SwarmResponse):
    members: list[SwarmMemberResponse] = Field(default_factory=list)
    subtasks: list[SubtaskResponse] = Field(default_factory=list)


class SwarmResultResponse(BaseModel):
    result_id: UUID
    swarm_id: UUID
    aggregation: dict
    summary: Optional[str] = None
    created_at: datetime
