"""
AgentX Platform — Work a collective has done (Phase C, Sprint 22, CL-3)
═══════════════════════════════════════════════════════════════════════
``GET /collectives/{id}/work``: the tasks assigned to a collective (title,
status, reward, when assigned), how many there are in each status, and the
tokens they earned.

Tokens earned come from the ledger (``transactions``): what the task escrow
released to the worker on approval (``escrow_release``), never the reward
written on the task row, so the page shows only money that really moved.

Visibility: a public collective's work is public; a private collective's is
404 to anyone who is not an ACTIVE member (its existence is not confirmed),
as the CL-2 membership reads. The answer is cached for ``CACHE_TTL`` seconds
per collective (Redis, or this machine's memory), together with whether the
collective is public, so a private one is still checked against the caller
on every read.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from .. import cache
from ..database import get_db
from ..models.collective import CollectiveWork, CollectiveWorkItem

logger = logging.getLogger(__name__)

CACHE_TTL = 60
TASKS_LIMIT = 50
TITLE_MAX = 200

#: The task payout: escrow released to the executor on approval (as the gate).
TASK_PAYOUT_TYPES = ("escrow_release",)


class CollectiveNotFound(Exception):
    """Missing, or private and the caller is not an ACTIVE member."""


def _cache_key(collective_id: UUID) -> str:
    return f"{cache._KEY_PREFIX}collectives:work:v1:{collective_id}"


async def build_work(conn, collective_id: UUID) -> CollectiveWork:
    """Read the work from the database (no cache, no visibility check)."""
    counts = await conn.fetch(
        """
        SELECT lower(t.status) AS status, count(*) AS n
        FROM collective_tasks ct
        JOIN tasks t ON t.task_id = ct.task_id
        WHERE ct.collective_id = $1
        GROUP BY 1
        """,
        collective_id,
    )
    earned = await conn.fetchval(
        """
        SELECT COALESCE(SUM(tx.amount), 0)
        FROM collective_tasks ct
        JOIN transactions tx ON tx.related_id = ct.task_id
        WHERE ct.collective_id = $1
          AND tx.type = ANY($2::text[])
          AND tx.to_wallet IS NOT NULL
          AND tx.amount > 0
        """,
        collective_id, list(TASK_PAYOUT_TYPES),
    )
    rows = await conn.fetch(
        """
        SELECT ct.task_id,
               left(COALESCE(NULLIF(t.payload->>'title', ''), t.task_type), $3) AS title,
               lower(t.status) AS status, t.reward, ct.assigned_at,
               COALESCE((
                   SELECT SUM(tx.amount) FROM transactions tx
                   WHERE tx.related_id = ct.task_id
                     AND tx.type = ANY($2::text[])
                     AND tx.to_wallet IS NOT NULL
                     AND tx.amount > 0
               ), 0) AS earned
        FROM collective_tasks ct
        JOIN tasks t ON t.task_id = ct.task_id
        WHERE ct.collective_id = $1
        ORDER BY ct.assigned_at DESC, ct.task_id
        LIMIT $4
        """,
        collective_id, list(TASK_PAYOUT_TYPES), TITLE_MAX, TASKS_LIMIT,
    )
    by_status = {r["status"]: int(r["n"]) for r in counts}
    return CollectiveWork(
        collective_id=collective_id,
        total_tasks=sum(by_status.values()),
        counts_by_status=by_status,
        tokens_earned=int(earned or 0),
        tasks=[
            CollectiveWorkItem(
                task_id=r["task_id"],
                title=r["title"],
                status=r["status"],
                reward=int(r["reward"] or 0),
                assigned_at=r["assigned_at"],
                tokens_earned=int(r["earned"] or 0),
            )
            for r in rows
        ],
    )


async def _visibility(conn, collective_id: UUID, caller_did: Optional[str]):
    """(is_public, caller is an ACTIVE member) or None when missing."""
    row = await conn.fetchrow(
        """
        SELECT c.is_public,
               EXISTS (SELECT 1 FROM collective_members cm
                       WHERE cm.collective_id = c.collective_id
                         AND cm.agent_did = $2 AND cm.status = 'ACTIVE') AS active
        FROM collectives c
        WHERE c.collective_id = $1
        """,
        collective_id, caller_did,
    )
    return None if row is None else (bool(row["is_public"]), bool(row["active"]))


async def get_work(collective_id: UUID, caller_did: Optional[str]) -> CollectiveWork:
    """The work, from the cache when fresh. Raises CollectiveNotFound."""
    key = _cache_key(collective_id)
    cached = await cache.cache_get(key)
    work: Optional[CollectiveWork] = None
    if isinstance(cached, dict):
        try:
            work = CollectiveWork.model_validate(cached["work"])
            if cached.get("is_public") is True:
                return work
        except (KeyError, TypeError, ValueError):
            logger.warning("collective work: cached copy unreadable; rebuilding")
            work = None

    async with get_db() as conn:
        seen = await _visibility(conn, collective_id, caller_did)
        if seen is None:
            raise CollectiveNotFound(collective_id)
        is_public, active = seen
        if not is_public and not active:
            raise CollectiveNotFound(collective_id)
        if work is None:
            work = await build_work(conn, collective_id)
            await cache.cache_set(
                key, {"is_public": is_public, "work": work.model_dump(mode="json")}, CACHE_TTL,
            )
    return work
