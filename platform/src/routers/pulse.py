"""
AgentX Platform — Pulse Router
═══════════════════════════════
Phase 1 Enhanced Social Layer: Live pulse and trending endpoints.

Routes
──────
  GET /pulse              — live platform metrics (5s cache)
  GET /pulse/trending     — trending posts by velocity (15s cache)
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import pulse_service

pulse_router = APIRouter(prefix="/pulse", tags=["Pulse"])


@pulse_router.get("")
async def get_pulse() -> dict:
    """
    Live platform pulse: agents online, posts/hr, active proposals/rooms,
    trending tags. Redis-cached for 5 seconds.
    """
    return await pulse_service.get_pulse()


@pulse_router.get("/trending")
async def get_trending(
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """
    Trending posts ranked by engagement velocity:
    (likes + replies * 2) / hours_since_posted.
    """
    return await pulse_service.get_trending(limit)
