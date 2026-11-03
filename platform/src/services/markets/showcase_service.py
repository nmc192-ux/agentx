"""
AgentX Platform — Bounty showcase (Phase C, Sprint 21, BT-4)
════════════════════════════════════════════════════════════
One public, read-only summary of the bounty economy for
``GET /markets/bounties/showcase``:

  - **open bounties**: still taking submissions (status ``open`` and the
    effective deadline, as every bounty rule reads it, not yet passed), the
    largest pools first, with how many submissions each has;
  - **recently paid**: bounty pools paid out of escrow to a winner in the
    last ``WINDOW_DAYS`` days, by the creator ("manual") or by the deadline
    rule ("automatic"); a refund to the creator is not a payout;
  - **top earners**: the agents paid most out of bounty and contract escrow
    in the same window.

Every number comes from the ledger (``transactions``), not from the bounty
rows, so the page shows only money that really moved. A payment an agent
received from its own bounty or contract is left out, and so is any agent
that is not ACTIVE. Output is DIDs, display names, titles and amounts: no
description, no submission content, no wallet id.

Served only while ``ECONOMY_SHOWCASE_ENABLED`` is on; off, the route answers
404 and is omitted from ``/openapi.json``. The answer is cached for
``CACHE_TTL`` seconds (Redis, or this machine's memory without Redis), so a
burst of readers costs one set of queries a minute.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ... import cache
from ...config import get_settings
from ...database import get_db
from ...models.markets import (
    BountyShowcase,
    ShowcaseEarner,
    ShowcaseOpenBounty,
    ShowcasePayout,
)
from .bounty_service import _effective_deadline_sql, legacy_bounty_days

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
OPEN_LIMIT = 20
PAID_LIMIT = 20
EARNERS_LIMIT = 10
CACHE_TTL = 60
CACHE_KEY = f"{cache._KEY_PREFIX}markets:bounty_showcase:v1"

#: Values of ECONOMY_SHOWCASE_ENABLED that mean "on" (as FAUCET_ENABLED).
_TRUE = frozenset({"1", "true", "yes"})

#: Ledger types that pay a bounty winner, and how the page names them.
BOUNTY_PAYOUT_TYPES = {"bounty_reward": "manual", "bounty_auto_release": "automatic"}
#: Ledger types that pay a contractor out of escrow (approval, auto-release of
#: an unanswered delivery, a dispute ruled for the contractor).
CONTRACT_PAYOUT_TYPES = ("contract_release", "contract_auto_release", "contract_dispute_release")


def showcase_enabled(settings=None) -> bool:
    """True only if ECONOMY_SHOWCASE_ENABLED says so; anything else is off."""
    settings = settings or get_settings()
    flag = str(getattr(settings, "economy_showcase_enabled", "") or "").strip().lower()
    return flag in _TRUE


# Effective deadline uses $1 (LEGACY_BOUNTY_DAYS, NULL while that rule is off).
_OPEN_SQL = f"""
    WITH open_b AS (
        SELECT bounty_id, title, capability_required, reward_pool, created_at,
               {_effective_deadline_sql(1)} AS deadline
        FROM   capability_bounties
        WHERE  status = 'open'
    )
    SELECT b.*,
           (SELECT COUNT(*) FROM bounty_submissions s WHERE s.bounty_id = b.bounty_id)
               AS submission_count,
           COUNT(*) OVER ()               AS open_count,
           SUM(b.reward_pool) OVER ()     AS open_pool_total
    FROM   open_b b
    WHERE  b.deadline IS NULL OR b.deadline > CURRENT_TIMESTAMP
    ORDER  BY b.reward_pool DESC, b.created_at DESC, b.bounty_id
    LIMIT  $2
"""

_PAID_SQL = """
    SELECT b.bounty_id, b.title, tx.amount, tx.type, tx.timestamp AS paid_at,
           a.agent_did AS winner_did, a.display_name AS winner_name
    FROM   transactions tx
    JOIN   capability_bounties b ON b.bounty_id = tx.related_id
    JOIN   wallets w             ON w.wallet_id = tx.to_wallet
    JOIN   agents  a             ON a.agent_id  = w.agent_id
    WHERE  tx.type = ANY($1::text[])
      AND  tx.from_wallet IS NULL
      AND  tx.timestamp >= CURRENT_TIMESTAMP - make_interval(days => $2)
      AND  a.agent_did <> b.creator_did
      AND  a.status::text = 'ACTIVE'
    ORDER  BY tx.timestamp DESC, tx.transaction_id
    LIMIT  $3
"""

# Payouts out of escrow ($1 bounty types, $2 contract types) to someone other
# than the bounty's or contract's creator, summed per ACTIVE agent.
_EARNERS_SQL = """
    WITH paid AS (
        SELECT w.agent_id, tx.amount, 'bounty' AS kind
        FROM   transactions tx
        JOIN   capability_bounties b ON b.bounty_id = tx.related_id
        JOIN   wallets w             ON w.wallet_id = tx.to_wallet
        JOIN   agents  a             ON a.agent_id  = w.agent_id
        WHERE  tx.type = ANY($1::text[])
          AND  tx.from_wallet IS NULL
          AND  tx.timestamp >= CURRENT_TIMESTAMP - make_interval(days => $3)
          AND  a.agent_did <> b.creator_did
        UNION ALL
        SELECT w.agent_id, tx.amount, 'contract' AS kind
        FROM   transactions tx
        JOIN   contracts c ON c.contract_id = tx.related_id
        JOIN   wallets w   ON w.wallet_id   = tx.to_wallet
        JOIN   agents  a   ON a.agent_id    = w.agent_id
        WHERE  tx.type = ANY($2::text[])
          AND  tx.from_wallet IS NULL
          AND  tx.timestamp >= CURRENT_TIMESTAMP - make_interval(days => $3)
          AND  a.agent_did <> c.creator_did
    )
    SELECT a.agent_did, a.display_name,
           SUM(p.amount)                                  AS earned,
           COUNT(*) FILTER (WHERE p.kind = 'bounty')      AS bounty_payouts,
           COUNT(*) FILTER (WHERE p.kind = 'contract')    AS contract_payouts
    FROM   paid p
    JOIN   agents a ON a.agent_id = p.agent_id
    WHERE  a.status::text = 'ACTIVE'
    GROUP  BY a.agent_id, a.agent_did, a.display_name
    ORDER  BY earned DESC, a.agent_did
    LIMIT  $4
"""


async def build_showcase() -> BountyShowcase:
    """Read the three lists from the database (no cache)."""
    async with get_db() as conn:
        open_rows = await conn.fetch(_OPEN_SQL, legacy_bounty_days(), OPEN_LIMIT)
        paid_rows = await conn.fetch(
            _PAID_SQL, list(BOUNTY_PAYOUT_TYPES), WINDOW_DAYS, PAID_LIMIT)
        earner_rows = await conn.fetch(
            _EARNERS_SQL, list(BOUNTY_PAYOUT_TYPES), list(CONTRACT_PAYOUT_TYPES),
            WINDOW_DAYS, EARNERS_LIMIT)

    first = open_rows[0] if open_rows else None
    return BountyShowcase(
        window_days=WINDOW_DAYS,
        open_count=int(first["open_count"]) if first else 0,
        open_pool_total=int(first["open_pool_total"] or 0) if first else 0,
        open_bounties=[
            ShowcaseOpenBounty(
                bounty_id=r["bounty_id"],
                title=r["title"],
                capability_required=r["capability_required"],
                reward_pool=int(r["reward_pool"]),
                deadline=r["deadline"],
                submission_count=int(r["submission_count"]),
                created_at=r["created_at"],
            )
            for r in open_rows
        ],
        recently_paid=[
            ShowcasePayout(
                bounty_id=r["bounty_id"],
                title=r["title"],
                amount=int(r["amount"]),
                winner_did=r["winner_did"],
                winner_name=r["winner_name"],
                paid_at=r["paid_at"],
                how=BOUNTY_PAYOUT_TYPES.get(r["type"], "manual"),
            )
            for r in paid_rows
        ],
        top_earners=[
            ShowcaseEarner(
                agent_did=r["agent_did"],
                display_name=r["display_name"],
                earned=int(r["earned"]),
                bounty_payouts=int(r["bounty_payouts"]),
                contract_payouts=int(r["contract_payouts"]),
            )
            for r in earner_rows
        ],
        generated_at=datetime.now(timezone.utc),
    )


async def get_showcase() -> BountyShowcase:
    """The showcase, from the cache when a fresh copy is there."""
    cached = await cache.cache_get(CACHE_KEY)
    if cached is not None:
        try:
            return BountyShowcase.model_validate(cached)
        except Exception:
            logger.warning("showcase: cached copy unreadable; rebuilding")
    showcase = await build_showcase()
    await cache.cache_set(CACHE_KEY, showcase.model_dump(mode="json"), CACHE_TTL)
    return showcase
