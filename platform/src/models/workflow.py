from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowStepCreate(BaseModel):
    task_type: str = Field(min_length=1)
    payload: Optional[dict] = None


class WorkflowCreate(BaseModel):
    initiator_agent_did: str = Field(min_length=1)
    workflow_type: str = Field(min_length=1)
    steps: list[WorkflowStepCreate] = Field(min_length=1)


class WorkflowStepResponse(BaseModel):
    step_id: UUID
    step_order: int
    task_type: str
    payload: Optional[dict] = None
    status: str
    task_id: Optional[UUID] = None
    created_at: datetime


class WorkflowResponse(BaseModel):
    workflow_id: UUID
    workflow_type: str
    initiator_agent_did: str
    status: str
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepResponse]
