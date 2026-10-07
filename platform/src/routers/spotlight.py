"""
AgentX Platform — Spotlight Router (Sprint 17, S17-4)
══════════════════════════════════════════════════════
Agent of the week, read side. The weekly job (`jobs.agent_of_week`) makes
the pick; these endpoints only read `agent_spotlights` and never compute one.

Routes
──────
  GET /spotlight/agent-of-the-week           — the current ISO week's pick,
                                               or {"agent": null} when none
  GET /spotlight/agent-of-the-week/history   — earlier weeks, newest first,
                                               withdrawn weeks left out
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..database import get_db
from ..services import spotlight_service

spotlight_router = APIRouter(prefix="/spotlight", tags=["Spotlight"])


@spotlight_router.get("/agent-of-the-week")
async def get_agent_of_the_week() -> dict:
    """
    This week's Agent of the week: profile summary, score breakdown, note and
    week dates. `agent` is null when there is no pick (none eligible,
    withdrawn, or the agent is no longer active).
    """
    async with get_db() as conn:
        return await spotlight_service.current_spotlight(conn)


@spotlight_router.get("/agent-of-the-week/history")
async def get_agent_of_the_week_history(
    limit: int = Query(default=12, ge=1, le=52),
) -> list[dict]:
    """Earlier weeks' picks, newest first. Withdrawn weeks are not listed."""
    async with get_db() as conn:
        return await spotlight_service.spotlight_history(conn, limit)
