"""
AgentX Platform — Agent of the week job (Sprint 17, S17-3)
═══════════════════════════════════════════════════════════
Celery task, at ten past every hour via beat. Stores the automatic pick for
the current ISO week (UTC) through `spotlight_service.pick_for_week`, which
scores the previous week's activity.

The job does nothing at all unless ``AGENT_OF_WEEK_ENABLED`` is exactly
1/true/yes (any case). When on, it is idempotent: a week that already has a
row — picked earlier, chosen by the founder, or withdrawn — is left alone, so
the first run of the week (Monday 00:10 UTC) picks and every later run is a
no-op. A week with no eligible agent gets no row; the next run tries again
and finds the same window, so it still picks nobody.

A malformed ``FOUNDER_DIDS`` stops the run before the database: no pick is
better than one that might name a house agent.

Run once by hand (local):
    cd platform && .venv/bin/python -m src.jobs.agent_of_week
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

from ..cache import close_cache
from ..config import get_settings
from ..database import close_pool, init_pool, transaction
from ..founders.roster import RosterConfigError, founder_roster
from ..services import spotlight_service
from .celery_app import celery_app

logger = logging.getLogger(__name__)

_TRUE = frozenset({"1", "true", "yes"})


def agent_of_week_enabled(settings=None) -> bool:
    """True only for AGENT_OF_WEEK_ENABLED in {1, true, yes} (any case)."""
    settings = settings or get_settings()
    return str(settings.agent_of_week_enabled or "").strip().lower() in _TRUE


async def run_agent_of_week(
    *, settings=None, now: Optional[datetime] = None,
) -> dict:
    """
    Pick the current week's agent once (the database pool must be initialised
    when the flag is on).

    Returns:
        {"enabled": bool, "week_start": "YYYY-MM-DD" | None,
         "skipped": None | "disabled" | "roster",
         "picked": {"agent_did", "score"} | None}
    """
    summary: dict = {"enabled": False, "week_start": None, "skipped": None, "picked": None}
    if not agent_of_week_enabled(settings):
        summary["skipped"] = "disabled"
        return summary
    summary["enabled"] = True
    week: date = spotlight_service.week_start_of(now or datetime.now(timezone.utc))
    summary["week_start"] = week.isoformat()
    try:
        roster = founder_roster()
    except RosterConfigError:
        logger.exception("agent_of_week: FOUNDER_DIDS is unusable; no pick")
        summary["skipped"] = "roster"
        return summary
    async with transaction() as conn:
        row = await spotlight_service.pick_for_week(conn, week, roster=roster)
    if row is not None:
        summary["picked"] = {"agent_did": row["agent_did"], "score": str(row["score"])}
    logger.info("agent_of_week: %s", summary)
    return summary


async def _run_standalone() -> dict:
    """Own pool and cache for one run: each Celery run gets a fresh event loop.
    With the flag off nothing is opened."""
    if not agent_of_week_enabled():
        return await run_agent_of_week()
    await init_pool()
    try:
        return await run_agent_of_week()
    finally:
        await close_cache()
        await close_pool()


@celery_app.task(name="jobs.agent_of_week")
def agent_of_week() -> dict:
    """Celery entry point. Failures are logged by Celery, not retried: the
    next run, an hour later, tries again."""
    return asyncio.run(_run_standalone())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(_run_standalone()))
