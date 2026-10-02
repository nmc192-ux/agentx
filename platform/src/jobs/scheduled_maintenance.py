"""
AgentX Platform — Scheduled Maintenance Job
════════════════════════════════════════════
Celery task, every 15 minutes via beat (Sprint 9, S9-9):

  1. Trust Score: apply every trust event not yet applied
     (services/reputation.recalculate_agent_trust). This is the score stored
     in agents.trust_score — the one leaderboards, search and governance vote
     weight read.
  2. Governance: close every proposal whose voting period is over, so a
     result does not wait for somebody to open the proposal list.

Each part runs on its own: one failing does not stop the other. Both are
safe to run from several processes at once (the trust replay takes a
transaction-level advisory lock; finalize skips proposals another
transaction holds).

Run once by hand (local):
    cd platform && .venv/bin/python -m src.jobs.scheduled_maintenance
"""
from __future__ import annotations

import asyncio
import logging

from ..cache import close_cache
from ..database import close_pool, init_pool
from ..services.governance_service import finalize_due_proposals
from ..services.reputation import recalculate_agent_trust
from .celery_app import celery_app

logger = logging.getLogger(__name__)


async def run_maintenance() -> dict:
    """
    Run every maintenance part once (the database pool must be initialised).

    Returns:
        {"trust": {"processed_events", "updated_agents"} | None,
         "proposals_closed": int | None,
         "errors": [part names that failed]}
    """
    summary: dict = {"trust": None, "proposals_closed": None, "errors": []}

    try:
        summary["trust"] = await recalculate_agent_trust()
    except Exception:
        logger.exception("scheduled_maintenance: trust recalculation failed")
        summary["errors"].append("trust")

    try:
        summary["proposals_closed"] = await finalize_due_proposals()
    except Exception:
        logger.exception("scheduled_maintenance: closing due proposals failed")
        summary["errors"].append("governance")

    logger.info("scheduled_maintenance: %s", summary)
    return summary


async def _run_standalone() -> dict:
    """Own pool and cache for one run: each Celery run gets a fresh event loop."""
    await init_pool()
    try:
        return await run_maintenance()
    finally:
        await close_cache()
        await close_pool()


@celery_app.task(name="jobs.scheduled_maintenance")
def scheduled_maintenance() -> dict:
    """Celery entry point. A failed part is logged and reported, not retried:
    the next run, 15 minutes later, picks up whatever is left."""
    return asyncio.run(_run_standalone())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(_run_standalone()))
