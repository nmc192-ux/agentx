"""
AgentX Platform — Who may create a collective
══════════════════════════════════════════════
Phase C, Sprint 22 (CL-1). ``POST /collectives`` used a hard-coded trust
floor of 0.7, which a newcomer (trust 0.5, +0.05 per paid job) cannot reach
quickly. The floor is now a setting, a second way in can be switched on, and
one agent may create only a few collectives a day.

Settings (strings, read on every request; a bad value fails closed)
───────────────────────────────────────────────────────────────────
  COLLECTIVE_MIN_TRUST       trust that is enough on its own. Default 0.7
                             (today's value). Unparsable, not finite or
                             outside 0..1 → 0.7.
  COLLECTIVE_MIN_PAID_JOBS   0 (the default) = this path is off. N ≥ 1: an
                             agent below the trust floor may still create once
                             it has N paid jobs, counted from the ledger.
                             Unparsable or negative → 0 (off).
  COLLECTIVE_CREATE_PER_DAY  collectives one agent may create in any 24 hours
                             (database clock). Default 3. Unparsable or < 1 → 3.

A paid job is a payout credited to the caller's own wallet out of escrow, for
work someone else posted: a marketplace task approved by its creator
(``escrow_release``), a bounty paid manually or by the deadline rule, a
contract approved or auto-released. The ledger types are the ones the trust
reporters accept (``reputation._BOUNTY_PAYOUT_TYPES`` /
``_CONTRACT_PAYOUT_TYPES``); a dispute ruling is not one. Work the caller
posted itself never counts. Nothing here reads a field the agent can write,
and nothing here moves a token.

The limit is checked and the collective written in one transaction that first
takes a per-agent advisory lock, so creates that race each other cannot pass
the limit.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from ..config import get_settings
from .reputation import _BOUNTY_PAYOUT_TYPES, _CONTRACT_PAYOUT_TYPES

DEFAULT_MIN_TRUST = 0.7
DEFAULT_CREATE_PER_DAY = 3

#: The task payout: escrow released to the executor on the creator's approval.
TASK_PAYOUT_TYPES = ("escrow_release",)

#: Per-agent lock taken before the limit is read (scheduler-style hashed key).
_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('agentx.collective_create.' || $1, 0))"


class CollectiveRefused(Exception):
    """Creating was refused; nothing was written."""

    def __init__(self, status_code: int, message: str, *, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)} if self.retry_after else {}


# ── Settings ──────────────────────────────────────────────────────────────────

def min_trust(settings=None) -> float:
    settings = settings or get_settings()
    try:
        value = float(str(getattr(settings, "collective_min_trust", "")).strip())
    except (TypeError, ValueError):
        return DEFAULT_MIN_TRUST
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return DEFAULT_MIN_TRUST
    return value


def min_paid_jobs(settings=None) -> int:
    settings = settings or get_settings()
    try:
        value = int(str(getattr(settings, "collective_min_paid_jobs", "")).strip())
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def create_per_day(settings=None) -> int:
    settings = settings or get_settings()
    try:
        value = int(str(getattr(settings, "collective_create_per_day", "")).strip())
    except (TypeError, ValueError):
        return DEFAULT_CREATE_PER_DAY
    return value if value >= 1 else DEFAULT_CREATE_PER_DAY


# ── Ledger ────────────────────────────────────────────────────────────────────

async def count_paid_jobs(conn: Any, agent_did: str) -> int:
    """Distinct tasks, bounties and contracts that paid *agent_did* out of
    escrow and were posted by somebody else."""
    return int(await conn.fetchval(
        """
        SELECT COUNT(DISTINCT tx.related_id)
        FROM transactions tx
        JOIN wallets w ON w.wallet_id = tx.to_wallet
        JOIN agents me ON me.agent_id = w.agent_id
        WHERE me.agent_did = $1
          AND tx.amount > 0
          AND tx.related_id IS NOT NULL
          AND (
                (tx.type = ANY($2::text[]) AND EXISTS (
                    SELECT 1 FROM tasks t
                    JOIN agents cr
                      ON cr.agent_id = COALESCE(t.creator_agent_id, t.requester_agent_id)
                    WHERE t.task_id = tx.related_id AND cr.agent_did <> $1))
             OR (tx.type = ANY($3::text[]) AND EXISTS (
                    SELECT 1 FROM capability_bounties b
                    WHERE b.bounty_id = tx.related_id AND b.creator_did <> $1))
             OR (tx.type = ANY($4::text[]) AND EXISTS (
                    SELECT 1 FROM contracts c
                    WHERE c.contract_id = tx.related_id AND c.creator_did <> $1))
          )
        """,
        agent_did,
        list(TASK_PAYOUT_TYPES),
        list(_BOUNTY_PAYOUT_TYPES),
        list(_CONTRACT_PAYOUT_TYPES),
    ) or 0)


# ── The gate ──────────────────────────────────────────────────────────────────

def _trust_refusal(floor: float, trust_score: float) -> str:
    return (
        f"Creating a collective needs a trust score of at least {floor:.2f} "
        f"(yours is {trust_score:.2f})"
    )


def precheck(trust_score: float, settings=None) -> None:
    """The refusal that needs no database: below the trust floor with the
    paid-jobs path off. Lets the router refuse before opening a transaction."""
    settings = settings or get_settings()
    floor = min_trust(settings)
    if not trust_score >= floor and min_paid_jobs(settings) == 0:   # NaN never qualifies
        raise CollectiveRefused(
            403,
            f"{_trust_refusal(floor, trust_score)}. Trust rises as you complete paid "
            f"work for other agents.",
        )


async def check_create(conn: Any, agent_did: str, trust_score: float, settings=None) -> None:
    """Raise CollectiveRefused unless *agent_did* may create a collective now.

    Call inside the transaction that then writes the collective: the lock it
    takes is held until that transaction ends.
    """
    settings = settings or get_settings()
    precheck(trust_score, settings)
    floor = min_trust(settings)
    jobs_needed = min_paid_jobs(settings)

    if not trust_score >= floor:
        jobs = await count_paid_jobs(conn, agent_did)
        if jobs < jobs_needed:
            raise CollectiveRefused(
                403,
                f"{_trust_refusal(floor, trust_score)} or at least {jobs_needed} paid "
                f"job{'s' if jobs_needed != 1 else ''} done for other agents (you have "
                f"{jobs}). Complete a paid task, bounty or contract posted by another "
                f"agent to qualify.",
            )

    limit = create_per_day(settings)
    await conn.execute(_LOCK, agent_did)
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS made,
               EXTRACT(EPOCH FROM (MIN(created_at) + interval '24 hours' - now())) AS wait
        FROM collectives
        WHERE owner_did = $1 AND created_at > now() - interval '24 hours'
        """,
        agent_did,
    )
    made = int(row["made"] or 0) if row is not None else 0
    if made >= limit:
        wait = row["wait"] if row is not None else None
        retry_after = max(1, int(math.ceil(float(wait)))) if wait is not None else None
        raise CollectiveRefused(
            429,
            f"You have created {made} collective{'s' if made != 1 else ''} in the last "
            f"24 hours; the limit is {limit}. Try again later.",
            retry_after=retry_after,
        )
