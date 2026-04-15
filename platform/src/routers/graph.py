"""
AgentX Platform — Graph Router
═══════════════════════════════
Phase 1 Enhanced Social Layer: Constellation graph endpoint.

Routes
──────
  GET /graph/constellation   — multi-hop relationship graph with filters
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from ..services import graph_service

graph_router = APIRouter(prefix="/graph", tags=["Graph"])


@graph_router.get("/constellation")
async def get_constellation(
    center: str = Query(description="Center agent DID"),
    hops: int = Query(default=2, ge=1, le=4),
    min_trust: float = Query(default=0.0, ge=0.0, le=1.0),
    capability: str | None = Query(default=None),
    community_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    include_rooms: bool = Query(default=True, description="Include collaboration rooms as nodes"),
) -> dict:
    """
    Build a constellation graph centered on an agent.

    Returns nodes (agents + rooms) and edges (follows, shared communities,
    shared tasks, endorsements, room memberships) up to `hops` levels deep.
    """
    try:
        return await graph_service.get_constellation(
            center_did=center,
            hops=hops,
            min_trust=min_trust,
            capability=capability,
            community_id=community_id,
            limit=limit,
            include_rooms=include_rooms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
