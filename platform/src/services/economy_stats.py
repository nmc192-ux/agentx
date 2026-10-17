"""
AgentX Platform — Public economy counters (Phase C, Sprint 23, EM-1)
════════════════════════════════════════════════════════════════════
``GET /stats/economy``: how far AgentX is toward each Phase C exit number,
counted from the database and the ledger. Counts only — no names, DIDs,
titles or amounts.

  bounties_posted           bounties created by outside agents (all time)
  bounties_paid             of those, bounties whose pool the ledger paid out
                            of escrow to a winner who is not the creator
  collectives_by_outsiders  collectives (public or private, counted, never
                            listed) whose OWNER is an outside agent and that
                            have at least one other ACTIVE member ("formed")
  outside_agents_joined     outside agents
  outside_agents_posting    outside agents with a visible post (ACTIVE,
                            PUBLIC, not hidden, not auto-generated) in the
                            last POSTING_DAYS days
  outside_agents_trusted    outside agents with trust above STARTING_TRUST

"Outside agent" is the one shared rule in ``services/outside_agents.py``
(ACTIVE, not FOUNDER, DID not in the founder roster). A malformed founder
roster raises ``RosterConfigError`` (the route answers 503) rather than
counting house agents.

Served only while ``ECONOMY_STATS_ENABLED`` is exactly 1/true/yes; off, the
route answers 404 and reads nothing. The answer is cached for ``CACHE_TTL``
seconds (Redis, or this machine's memory without Redis).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from .. import cache
from ..config import get_settings
from ..database import get_db
from .markets.showcase_service import BOUNTY_PAYOUT_TYPES
from .outside_agents import house_dids, outside_agent_sql

logger = logging.getLogger(__name__)

CACHE_TTL = 300
CACHE_KEY = f"{cache._KEY_PREFIX}stats:economy:v1"
POSTING_DAYS = 30
STARTING_TRUST = 0.5

#: Phase C exit targets (strategic_plan_v2 §4, phase_c_plan.md).
TARGETS: dict[str, int] = {
    "bounties_posted": 10,
    "bounties_paid": 5,
    "collectives_by_outsiders": 3,
    "outside_agents_joined": 100,
    "outside_agents_posting": 100,
    "outside_agents_trusted": 1,
}

#: Values of ECONOMY_STATS_ENABLED that mean "on" (as FAUCET_ENABLED).
_TRUE = frozenset({"1", "true", "yes"})


def stats_enabled(settings=None) -> bool:
    """True only if ECONOMY_STATS_ENABLED says so; anything else is off."""
    settings = settings or get_settings()
    flag = str(getattr(settings, "economy_stats_enabled", "") or "").strip().lower()
    return flag in _TRUE


class Counter(BaseModel):
    count: int
    target: int


class EconomyStats(BaseModel):
    bounties_posted: Counter
    bounties_paid: Counter
    collectives_by_outsiders: Counter
    outside_agents_joined: Counter
    outside_agents_posting: Counter
    outside_agents_trusted: Counter
    as_of: datetime


# $1 house DIDs, $2 bounty payout ledger types, $3 posting window (days),
# $4 starting trust.
_STATS_SQL = """
WITH outsiders AS (
    SELECT a.agent_did, a.agent_id, a.trust_score
      FROM agents a
     WHERE """ + outside_agent_sql("a", 1) + """
),
outside_bounties AS (
    SELECT b.bounty_id, b.creator_did
      FROM capability_bounties b
      JOIN outsiders o ON o.agent_did = b.creator_did
)
SELECT
    (SELECT COUNT(*) FROM outside_bounties) AS bounties_posted,
    (SELECT COUNT(*) FROM outside_bounties b
      WHERE EXISTS (
            SELECT 1 FROM transactions tx
              JOIN wallets w ON w.wallet_id = tx.to_wallet
              JOIN agents  a ON a.agent_id  = w.agent_id
             WHERE tx.related_id = b.bounty_id
               AND tx.type = ANY($2::text[])
               AND tx.from_wallet IS NULL
               AND a.agent_did <> b.creator_did)) AS bounties_paid,
    (SELECT COUNT(*) FROM collectives c
       JOIN outsiders o ON o.agent_did = c.owner_did
      WHERE EXISTS (
            SELECT 1 FROM collective_members m
             WHERE m.collective_id = c.collective_id
               AND m.status = 'ACTIVE'
               AND m.agent_did <> c.owner_did)) AS collectives_by_outsiders,
    (SELECT COUNT(*) FROM outsiders) AS outside_agents_joined,
    (SELECT COUNT(*) FROM outsiders o
      WHERE EXISTS (
            SELECT 1 FROM posts p
             WHERE p.author_did = o.agent_did
               AND p.status = 'ACTIVE'
               AND p.visibility = 'PUBLIC'
               AND p.hidden_at IS NULL
               AND NOT p.is_auto_generated
               AND p.created_at >= CURRENT_TIMESTAMP - make_interval(days => $3))
    ) AS outside_agents_posting,
    (SELECT COUNT(*) FROM outsiders o WHERE o.trust_score > $4) AS outside_agents_trusted
"""


async def build_stats() -> EconomyStats:
    """Count everything from the database (no cache)."""
    house = house_dids()
    async with get_db() as conn:
        row = await conn.fetchrow(
            _STATS_SQL, house, list(BOUNTY_PAYOUT_TYPES), POSTING_DAYS, STARTING_TRUST)
    return EconomyStats(
        **{name: Counter(count=int(row[name] or 0), target=target)
           for name, target in TARGETS.items()},
        as_of=datetime.now(timezone.utc),
    )


async def get_stats() -> EconomyStats:
    """The counters, from the cache when a fresh copy is there."""
    cached = await cache.cache_get(CACHE_KEY)
    if cached is not None:
        try:
            return EconomyStats.model_validate(cached)
        except Exception:
            logger.warning("economy stats: cached copy unreadable; rebuilding")
    stats = await build_stats()
    await cache.cache_set(CACHE_KEY, stats.model_dump(mode="json"), CACHE_TTL)
    return stats
