"""
AgentX Platform — Reputation Graph Pydantic Models
════════════════════════════════════════════════════
Phase 20: Agent Reputation Graph.

Models
──────
  GraphEdge               — a single directed trust relationship
  TrustNetworkResponse    — full trust network for an agent
  CollaboratorSummary     — summary of a top collaborator
  RecordInteractionRequest — request body for manual interaction recording
  GraphEnhancedScore      — discovery score with graph weight included
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Graph edge ────────────────────────────────────────────────────────────────

class GraphEdge(BaseModel):
    """A directed trust edge from agent → peer."""
    graph_id:          UUID
    agent_id:          UUID
    peer_agent_id:     UUID
    trust_weight:      float  = Field(ge=0.0, le=1.0)
    interaction_count: int    = Field(ge=0)
    last_interaction:  datetime
    created_at:        datetime

    model_config = {"from_attributes": True}


# ── Trust network ─────────────────────────────────────────────────────────────

class TrustNetworkResponse(BaseModel):
    """Full trust network for a single agent."""
    agent_id:   UUID
    peer_count: int
    peers:      list[GraphEdge]

    model_config = {"from_attributes": True}


# ── Collaborator summary ───────────────────────────────────────────────────────

class CollaboratorSummary(BaseModel):
    """Summary of a top collaborator (for GET /agents/{id}/top-collaborators)."""
    peer_agent_id:     UUID
    trust_weight:      float
    interaction_count: int
    last_interaction:  datetime

    model_config = {"from_attributes": True}


# ── Request body ──────────────────────────────────────────────────────────────

class RecordInteractionRequest(BaseModel):
    """Request body for manually recording an agent-to-agent interaction."""
    peer_agent_id:    UUID
    weight_delta:     float = Field(default=0.1, ge=-1.0, le=1.0)
    interaction_type: str   = Field(default="general", max_length=50)


# ── Graph-enhanced discovery score ────────────────────────────────────────────

class GraphEnhancedScore(BaseModel):
    """Discovery score augmented with reputation graph weight."""
    agent_id:    UUID
    base_score:  float
    graph_weight: float
    enhanced_score: float

    model_config = {"from_attributes": True}
