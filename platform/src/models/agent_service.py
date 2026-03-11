from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ServiceCreate(BaseModel):
    agent_did: str = Field(min_length=1)
    service_name: str = Field(min_length=1)
    service_type: str = Field(min_length=1)
    description: Optional[str] = None
    pricing_model: Optional[str] = None
    price: Optional[float] = None
    capabilities: Optional[dict] = None


class ServiceResponse(BaseModel):
    service_id: UUID
    agent_did: str
    service_name: str
    service_type: str
    description: Optional[str] = None
    pricing_model: Optional[str] = None
    price: Optional[float] = None
    capabilities: Optional[dict] = None
    is_active: bool
    created_at: datetime
