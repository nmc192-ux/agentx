from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    requester_agent_did: str = Field(min_length=1)
    executor_agent_did: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None


class TaskRouteCreate(BaseModel):
    requester_agent_did: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None


class TaskResponse(BaseModel):
    task_id: UUID
    requester_agent_did: str
    executor_agent_did: str
    task_type: str
    payload: Optional[dict] = None
    status: str
    result: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    result: Optional[dict] = None
