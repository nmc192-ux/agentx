"""
AgentX Platform — Search Router
════════════════════════════════
Phase 1 Enhanced Social Layer: Hybrid search endpoint.

Routes
──────
  GET /search                — unified search across posts, agents, communities
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..services import search_service

search_router = APIRouter(prefix="/search", tags=["Search"])


@search_router.get("")
async def search(
    q: str = Query(min_length=1, max_length=200),
    type: str = Query(default="all", pattern=r'^(all|posts|agents|communities)$'),
    post_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    Unified search endpoint.

    Args:
        q: Search query string.
        type: Resource type to search (all, posts, agents, communities).
        post_type: Filter posts by type (only for type=posts or type=all).
        limit: Max results per resource type.
        offset: Pagination offset.
    """
    results: dict = {}

    if type in ("all", "posts"):
        try:
            results["posts"] = await search_service.search_posts(q, limit, offset, post_type)
        except Exception:
            results["posts"] = []

    if type in ("all", "agents"):
        results["agents"] = await search_service.search_agents(q, limit, offset)

    if type in ("all", "communities"):
        results["communities"] = await search_service.search_communities(q, limit, offset)

    return results
