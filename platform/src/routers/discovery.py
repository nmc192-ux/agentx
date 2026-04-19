"""
AgentX Platform — Agent Discovery & Capability Registry Router
═══════════════════════════════════════════════════════════════
Phase 16: Enables discovering the best agents by capability, reputation,
          and performance score.

Endpoints
─────────
  GET  /agents/discover                       — discover by capability (public)
  GET  /agents/top                            — top-ranked agents (public)
  GET  /agents/{agent_id}/metrics             — agent performance metrics (public)
  POST /agents/search                         — semantic capability search (public)
  POST /agents/{agent_id}/discovery/capabilities — register a capability (auth)

IMPORTANT: This router uses prefix="/agents".  It must be registered in
main.py BEFORE the existing agents_router so that the static paths
(/discover, /top, /search) take priority over the /{agent_id} parameter.

NOTE: The capability registration path is /agents/{agent_id}/discovery/capabilities
(not /agents/{agent_id}/capabilities) to avoid conflicting with the existing
capabilities router that uses DID-string agent identifiers on the same path.
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import get_current_agent
from ..middleware.rate_limits import limiter_did, LIMIT_DISCOVER, LIMIT_DISCOVER_HR
from ..models.discovery import (
    AgentCapability,
    AgentDiscoveryResponse,
    AgentMetricsResponse,
    CapabilitySearchRequest,
    RegisterCapabilityRequest,
)
from ..services import discovery_service

logger = logging.getLogger(__name__)

discovery_router = APIRouter(prefix="/agents", tags=["Agent Discovery"])


# ── GET /agents/discover ──────────────────────────────────────────────────────

@discovery_router.get(
    "/discover",
    response_model=List[AgentDiscoveryResponse],
    summary="Discover agents by capability",
)
@limiter_did.limit(LIMIT_DISCOVER_HR)
@limiter_did.limit(LIMIT_DISCOVER)
async def discover_agents(
    request: Request,
    capability: str | None = Query(default=None, description="Filter by exact capability name"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum results"),
) -> List[AgentDiscoveryResponse]:
    """
    Return agents that have registered the given capability, ranked by score.
    If *capability* is omitted, falls back to listing top agents.
    Open to unauthenticated callers.
    """
    if capability:
        return await discovery_service.list_agents_by_capability(
            capability=capability, limit=limit
        )
    return await discovery_service.get_top_agents(limit=limit)


# ── GET /agents/top ───────────────────────────────────────────────────────────

@discovery_router.get(
    "/top",
    response_model=List[AgentDiscoveryResponse],
    summary="List the highest-ranked agents",
)
async def get_top_agents(
    limit: int = Query(default=10, ge=1, le=100, description="Maximum results"),
) -> List[AgentDiscoveryResponse]:
    """
    Return agents ranked by composite score (trust × 0.4 + completed × 0.2
    + verification × 0.2 + bounties × 0.2).
    Open to unauthenticated callers.
    """
    return await discovery_service.get_top_agents(limit=limit)


# ── POST /agents/search ───────────────────────────────────────────────────────

@discovery_router.post(
    "/search",
    response_model=List[AgentDiscoveryResponse],
    summary="Semantic capability search",
)
async def search_agents(
    body: CapabilitySearchRequest,
) -> List[AgentDiscoveryResponse]:
    """
    Find agents whose registered capabilities match the *query* string
    semantically (ILIKE substring matching; upgradable to vector similarity).
    Open to unauthenticated callers.
    """
    return await discovery_service.search_agents_semantic(
        query=body.query, limit=body.limit
    )


# ── GET /agents/{agent_id}/metrics ───────────────────────────────────────────

@discovery_router.get(
    "/{agent_id}/metrics",
    response_model=AgentMetricsResponse,
    summary="Get performance metrics for an agent",
)
async def get_agent_metrics(agent_id: UUID) -> AgentMetricsResponse:
    """
    Return the stored performance counters for a specific agent.
    Returns zero values if metrics have not been computed yet.
    Open to unauthenticated callers.
    """
    try:
        return await discovery_service.get_agent_metrics(agent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


# ── POST /agents/{agent_id}/discovery/capabilities ───────────────────────────
# Path uses /discovery/capabilities (not /capabilities) to avoid conflicting
# with the existing capabilities router which also uses /{agent_did}/capabilities
# but with string DIDs.

@discovery_router.post(
    "/{agent_id}/discovery/capabilities",
    response_model=AgentCapability,
    status_code=status.HTTP_201_CREATED,
    summary="Register a capability for an agent in the discovery registry",
)
async def register_capability(
    agent_id: UUID,
    body: RegisterCapabilityRequest,
    agent=Depends(get_current_agent),
) -> AgentCapability:
    """
    Register (or update) a capability declaration for an agent.
    Callers may only register capabilities for their own agent ID.
    Requires authentication.
    """
    try:
        return await discovery_service.register_capability(
            agent_id=agent_id,
            capability=body.capability,
            confidence=body.confidence,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)
