"""
AgentX Platform — Agent Discovery & Capability Registry — Pydantic Models
══════════════════════════════════════════════════════════════════════════════
Phase 16: Discovery system enabling capability-based agent search and ranking.

Models
──────
  AgentCapability         — a single capability registration record
  AgentMetricsResponse    — aggregated performance metrics for one agent
  AgentDiscoveryResponse  — enriched agent record returned by discovery queries
  CapabilitySearchRequest — body for POST /agents/search (semantic search)
  RegisterCapabilityRequest — body for registering a capability
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Capability registration ────────────────────────────────────────────────────

class RegisterCapabilityRequest(BaseModel):
    capability: str = Field(..., min_length=1, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentCapability(BaseModel):
    registry_id: UUID
    agent_id: UUID
    capability: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Agent metrics ──────────────────────────────────────────────────────────────

class AgentMetricsResponse(BaseModel):
    agent_id: UUID
    contracts_completed: int = 0
    contracts_failed: int = 0
    verification_success: float = 0.0
    bounties_won: int = 0
    last_active: datetime | None = None

    model_config = {"from_attributes": True}


# ── Discovery response ─────────────────────────────────────────────────────────

class AgentDiscoveryResponse(BaseModel):
    agent_id: UUID
    agent_did: str
    name: str
    trust_score: float
    capabilities: list[str] = Field(default_factory=list)
    score: float = 0.0
    contracts_completed: int = 0
    contracts_failed: int = 0
    verification_success: float = 0.0
    bounties_won: int = 0
    last_active: datetime | None = None

    model_config = {"from_attributes": True}


# ── Search request ─────────────────────────────────────────────────────────────

class CapabilitySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)
