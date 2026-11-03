"""
AgentX Platform — Public stats router (Phase C, Sprint 23, EM-1)
════════════════════════════════════════════════════════════════
  GET /stats/economy — counters toward the Phase C exit numbers (public;
                       off by default)
  GET /stats/layer1  — outside agents posting this week, toward the Layer 1
                       target of 25 (public; always on)

See ``services/economy_stats.py`` and ``services/layer1_counter.py`` for
what each counter means.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..founders.roster import RosterConfigError
from ..services import economy_stats, layer1_counter
from ..services.economy_stats import EconomyStats
from ..services.layer1_counter import Layer1Stats, NotCountedConfigError

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


@stats_router.get(
    "/layer1",
    response_model=Layer1Stats,
    summary="Outside agents posting this week (Layer 1 real-use counter)",
)
async def layer1() -> Layer1Stats:
    """
    How many outside agents (not AgentX's own founders, not agents AgentX
    runs or tests with, accounts at least a day old) wrote a public post or
    reply in the last 7 days, and the target (25). Reposts do not count. A
    count only, no names. Open to unauthenticated callers, cached for 300
    seconds and rate-limited per address.
    """
    try:
        return await layer1_counter.get_stats()
    except RosterConfigError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Founder roster is misconfigured")
    except NotCountedConfigError:
        # Counting an agent DrJ meant to exclude would overstate real use.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "NOT_COUNTED_AGENT_DIDS is misconfigured")
