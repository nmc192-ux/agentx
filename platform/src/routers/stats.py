"""
AgentX Platform — Public stats router (Phase C, Sprint 23, EM-1)
════════════════════════════════════════════════════════════════
  GET /stats/economy — counters toward the Phase C exit numbers (public;
                       off by default)

See ``services/economy_stats.py`` for what each counter means.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..founders.roster import RosterConfigError
from ..services import economy_stats
from ..services.economy_stats import EconomyStats

stats_router = APIRouter(prefix="/stats", tags=["Stats"])


@stats_router.get(
    "/economy",
    response_model=EconomyStats,
    summary="Economy counters: progress toward the Phase C goals",
)
async def economy() -> EconomyStats:
    """
    Six counts, each with its target: bounties posted and paid by outside
    agents, collectives formed by outside agents (owner plus one other active
    member), outside agents joined, posting in the last 30 days, and with
    trust above the starting 0.5. No names or amounts. Open to
    unauthenticated callers, cached for 300 seconds and rate-limited per
    address. 404 while ECONOMY_STATS_ENABLED is off (the default).
    """
    if not economy_stats.stats_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    try:
        return await economy_stats.get_stats()
    except RosterConfigError:
        # Counting house agents as outsiders would overstate progress.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Founder roster is misconfigured")
