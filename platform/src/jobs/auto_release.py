"""
AgentX Platform — Automatic Release Job
════════════════════════════════════════
Celery task, every 15 minutes via beat (Sprint 12, S12-7 / E6):

When the other side stays silent for AUTO_RELEASE_DAYS, held tokens are
released by the three reviewed release functions — and by nothing else:

  1. tasks:     a result left unanswered        → task_service.release_overdue_result
  2. contracts: a delivery left unanswered      → contract_service.release_overdue_contract
  3. bounties:  a pool left unpaid past deadline → bounty_service.release_overdue_bounty

This job only finds candidates and calls those functions, one item at a time.
The candidate query is a cheap pre-filter; each release function re-checks
every rule (status, the database clock, payee) with the row locked, so an item
that is not due, or that somebody else settled first, is refused there and
nothing moves. That also makes the job idempotent and safe to run from several
processes at once: an item is paid at most once however often it runs.

One item failing is logged and skipped; the rest still run, and the next run
tries it again.

Run once by hand (local):
    cd platform && .venv/bin/python -m src.jobs.auto_release
"""
from __future__ import annotations

import asyncio
import logging
from types import ModuleType
from uuid import UUID

from ..cache import close_cache
from ..database import close_pool, get_db, init_pool
from ..services import contract_service, task_service
from ..services.auto_release import AUTO_RELEASE_DAYS
from ..services.markets import bounty_service
from .celery_app import celery_app

logger = logging.getLogger(__name__)

# At most this many items of each kind per run; the rest wait 15 minutes.
BATCH_LIMIT = 200

_DUE_TASKS = """
    SELECT task_id FROM tasks
     WHERE status = 'in_review'
       AND submitted_at <= CURRENT_TIMESTAMP - make_interval(days => $1)
     ORDER BY submitted_at, task_id
     LIMIT $2
"""

_DUE_CONTRACTS = """
    SELECT c.contract_id FROM contracts c
      JOIN contract_results r ON r.contract_id = c.contract_id
     WHERE c.status = 'submitted'
     GROUP BY c.contract_id
    HAVING MAX(r.submitted_at) <= CURRENT_TIMESTAMP - make_interval(days => $1)
     ORDER BY MAX(r.submitted_at), c.contract_id
     LIMIT $2
"""

_DUE_BOUNTIES = """
    SELECT bounty_id FROM capability_bounties
     WHERE status IN ('open', 'evaluating')
       AND deadline <= CURRENT_TIMESTAMP - make_interval(days => $1)
     ORDER BY deadline, bounty_id
     LIMIT $2
"""

# kind → (candidate query, service module, its release function)
_KINDS: dict[str, tuple[str, ModuleType, str]] = {
    "tasks":     (_DUE_TASKS,     task_service,     "release_overdue_result"),
    "contracts": (_DUE_CONTRACTS, contract_service, "release_overdue_contract"),
    "bounties":  (_DUE_BOUNTIES,  bounty_service,   "release_overdue_bounty"),
}


async def _due_ids(query: str) -> list[UUID]:
    async with get_db() as conn:
        rows = await conn.fetch(query, AUTO_RELEASE_DAYS, BATCH_LIMIT)
    return [row[0] for row in rows]


async def _release_kind(kind: str) -> dict:
    query, service, function_name = _KINDS[kind]
    release = getattr(service, function_name)
    counts = {"released": 0, "skipped": 0, "failed": 0}
    for item_id in await _due_ids(query):
        try:
            await release(item_id)
        except ValueError as exc:
            # The service's refusal (its *ConflictError is a ValueError) or
            # "not found": settled by somebody else since the query, or no
            # longer due. The release function moved nothing.
            logger.info("auto_release: %s %s skipped: %s", kind, item_id, exc)
            counts["skipped"] += 1
        except Exception:
            logger.exception("auto_release: %s %s failed; next run retries", kind, item_id)
            counts["failed"] += 1
        else:
            counts["released"] += 1
    return counts


async def run_auto_release() -> dict:
    """
    Release every due item once (the database pool must be initialised).

    Returns:
        {"tasks" | "contracts" | "bounties": {"released", "skipped", "failed"} | None,
         "errors": [kinds whose candidate query failed]}
    """
    summary: dict = {kind: None for kind in _KINDS}
    summary["errors"] = []
    for kind in _KINDS:
        try:
            summary[kind] = await _release_kind(kind)
        except Exception:
            logger.exception("auto_release: finding due %s failed", kind)
            summary["errors"].append(kind)
    logger.info("auto_release: %s", summary)
    return summary


async def _run_standalone() -> dict:
    """Own pool and cache for one run: each Celery run gets a fresh event loop."""
    await init_pool()
    try:
        return await run_auto_release()
    finally:
        await close_cache()
        await close_pool()


@celery_app.task(name="jobs.auto_release")
def auto_release() -> dict:
    """Celery entry point. Failures are logged and reported, not retried:
    the next run, 15 minutes later, picks up whatever is left."""
    return asyncio.run(_run_standalone())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(_run_standalone()))
