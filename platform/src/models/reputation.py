from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentTrustScoreResponse(BaseModel):
    agent_id: UUID
    current_score: float = Field(ge=0.0, le=1.0)
    last_updated: datetime | None = None


class ReputationHistoryEntry(BaseModel):
    history_id: UUID
    agent_id: UUID
    event_id: UUID
    event_type: str
    event_weight: float
    score_before: float = Field(ge=0.0, le=1.0)
    score_after: float = Field(ge=0.0, le=1.0)
    metadata: dict
    created_at: datetime
