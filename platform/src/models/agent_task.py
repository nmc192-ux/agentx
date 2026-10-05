from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# The requester is always the authenticated caller (Sprint 9, S9-6a).
# ``requester_agent_did`` is optional and, if sent, must name the caller.

class TaskCreate(BaseModel):
    requester_agent_did: Optional[str] = Field(default=None, min_length=1)
    executor_agent_did: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None


class TaskRouteCreate(BaseModel):
    requester_agent_did: Optional[str] = Field(default=None, min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None


class TaskResponse(BaseModel):
    task_id: UUID
    requester_agent_did: str
    # None while a marketplace task is still open (no bid accepted yet).
    executor_agent_did: Optional[str] = None
    task_type: str
    payload: Optional[dict] = None
    status: str
    result: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    result: Optional[dict] = None
