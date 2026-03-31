"""
AgentX Platform — Developer Ecosystem Models
═════════════════════════════════════════════
Phase 5: API keys, webhooks, SDK registration
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── API Key Models ────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", max_length=100)
    scopes: list[str] = Field(default=["read", "write"])
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        valid = {"read", "write", "admin", "webhooks", "swarms", "tasks", "wallet"}
        for scope in v:
            if scope not in valid:
                raise ValueError(f"Invalid scope: {scope}. Valid: {', '.join(sorted(valid))}")
        return v


class ApiKeyResponse(BaseModel):
    key_id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the full key (shown once)."""
    api_key: str = Field(description="Full API key — store securely, shown only once")


# ── Webhook Models ────────────────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    name: str = Field(default="default", max_length=100)
    callback_url: str = Field(min_length=1)
    event_types: list[str] = Field(default=["*"])

    @field_validator("callback_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Webhook callback_url must use HTTPS")
        return v


class WebhookUpdate(BaseModel):
    callback_url: Optional[str] = None
    event_types: Optional[list[str]] = None
    is_active: Optional[bool] = None

    @field_validator("callback_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v.startswith("https://"):
                raise ValueError("Webhook callback_url must use HTTPS")
        return v


class WebhookResponse(BaseModel):
    webhook_id: UUID
    name: str
    callback_url: str
    event_types: list[str]
    is_active: bool
    failure_count: int
    last_triggered_at: Optional[datetime] = None
    created_at: datetime


class WebhookDeliveryResponse(BaseModel):
    delivery_id: UUID
    webhook_id: UUID
    event_id: UUID
    event_type: str
    status: str
    response_code: Optional[int] = None
    attempt_count: int
    last_attempt: Optional[datetime] = None
    created_at: datetime
