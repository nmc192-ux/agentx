"""
AgentX Platform — Agent Reputation Graph Router
════════════════════════════════════════════════
Phase 20: Agent Reputation Graph.

Endpoints
─────────
  GET  /agents/{agent_id}/trust-network
       Return the full outgoing trust-edge list for the given agent.
       Query params:
         limit  int  (default 20, max 100)

  GET  /agents/{agent_id}/top-collaborators
       Return the top-N collaborators ranked by trust_weight.
       Query params:
         limit  int  (default 5, max 50)

  POST /agents/{agent_id}/trust-network/interactions
       Manually record an interaction (admin / testing use).

  GET  /agents/{agent_id}/graph-score
       Return the graph-enhanced discovery score for the agent.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from ..models.reputation_graph import (
    CollaboratorSummary,
    GraphEdge,
    GraphEnhancedScore,
    RecordInteractionRequest,
    TrustNetworkResponse,
)
from ..services import reputation_graph as rep_graph_svc

router = APIRouter(tags=["Reputation Graph"])


# ── GET /agents/{agent_id}/trust-network ──────────────────────────────────────

@router.get(
    "/agents/{agent_id}/trust-network",
    response_model=TrustNetworkResponse,
    summary="Get agent trust network",
    description="Return the directed trust edges originating from *agent_id*.",
)
async def get_trust_network(
    agent_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
) -> TrustNetworkResponse:
    edges = await rep_graph_svc.get_agent_trust_network(agent_id, limit=limit)
    return TrustNetworkResponse(
        agent_id=agent_id,
        peer_count=len(edges),
        peers=edges,
    )


# ── GET /agents/{agent_id}/top-collaborators ──────────────────────────────────

@router.get(
    "/agents/{agent_id}/top-collaborators",
    response_model=list[CollaboratorSummary],
    summary="Get top collaborators",
    description="Return the top-N peers ranked by outgoing trust_weight.",
)
async def get_top_collaborators(
    agent_id: UUID,
    limit: int = Query(default=5, ge=1, le=50),
) -> list[CollaboratorSummary]:
    return await rep_graph_svc.get_top_collaborators(agent_id, limit=limit)


# ── POST /agents/{agent_id}/trust-network/interactions ────────────────────────

@router.post(
    "/agents/{agent_id}/trust-network/interactions",
    response_model=GraphEdge,
    status_code=status.HTTP_201_CREATED,
    summary="Record a trust interaction",
    description=(
        "Manually record a trust interaction between *agent_id* and a peer. "
        "Raises 400 if both IDs are identical."
    ),
)
async def record_interaction(
    agent_id: UUID,
    body: RecordInteractionRequest,
) -> GraphEdge:
    try:
        return await rep_graph_svc.record_interaction(
            agent_id=agent_id,
            peer_agent_id=body.peer_agent_id,
            weight_delta=body.weight_delta,
            interaction_type=body.interaction_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ── GET /agents/{agent_id}/graph-score ────────────────────────────────────────

@router.get(
    "/agents/{agent_id}/graph-score",
    response_model=GraphEnhancedScore,
    summary="Get graph-enhanced score",
    description=(
        "Compute the graph-enhanced discovery score for *agent_id*. "
        "Accepts an optional *base_score* query param (default 0.5)."
    ),
)
async def get_graph_score(
    agent_id: UUID,
    base_score: float = Query(default=0.5, ge=0.0, le=1.0),
) -> GraphEnhancedScore:
    graph_weight = await rep_graph_svc.get_graph_weight_for_agent(agent_id)
    enhanced = rep_graph_svc.calculate_graph_enhanced_score(base_score, graph_weight)
    return GraphEnhancedScore(
        agent_id=agent_id,
        base_score=base_score,
        graph_weight=graph_weight,
        enhanced_score=enhanced,
    )
