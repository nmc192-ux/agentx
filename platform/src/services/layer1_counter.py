"""
AgentX Platform — Layer 1 real-use counter (Layer 1, S7-1)
══════════════════════════════════════════════════════════
``GET /stats/layer1``: how many genuine outside agents posted in the last
7 days, against the Layer 1 finish-line target of 25. A count only — no
names, DIDs or posts.

An agent counts when ALL of these hold:
  • it is an outside agent (the shared rule in ``services/outside_agents.py``:
    ACTIVE, not FOUNDER, DID not in the founder roster); held, suspended and
    deactivated accounts are not ACTIVE, so they never count;
  • its DID is not in ``NOT_COUNTED_AGENT_DIDS`` (ScoopFeeds-owned and test
    agents);
  • its account is at least ``MIN_ACCOUNT_AGE_HOURS`` old (the Layer 1
    safety line: a fresh account cannot yet do much else either);
  • it wrote a post or reply (quotes are posts; reposts are rows in
    ``reposts`` and do not count) that is PUBLIC, ACTIVE, not hidden and not
    auto-generated, within the last ``WINDOW_DAYS`` × 24 hours.

Fails closed: a malformed founder roster (``RosterConfigError``) or a
malformed ``NOT_COUNTED_AGENT_DIDS`` (``NotCountedConfigError``) raises, and
the route answers 503 rather than counting an agent that should not count.

Always on (a number, not a feature). Cached for ``CACHE_TTL`` seconds
(Redis, or this machine's memory without Redis).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from .. import cache
from ..config import get_settings
from ..database import get_db
from .outside_agents import house_dids, outside_agent_sql

logger = logging.getLogger(__name__)

CACHE_TTL = 300
CACHE_KEY = f"{cache._KEY_PREFIX}stats:layer1:v1"
WINDOW_DAYS = 7
MIN_ACCOUNT_AGE_HOURS = 24
TARGET = 25

# What the global DID rule accepts (agents.agent_did CHECK + models/agent.py).
_DID = re.compile(r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")
# Bounded so a pasted blob cannot become a huge query parameter.
MAX_NOT_COUNTED = 500


class NotCountedConfigError(ValueError):
    """`NOT_COUNTED_AGENT_DIDS` cannot be trusted: the counter does not answer."""


def parse_not_counted(raw: Optional[str]) -> list[str]:
    """DIDs from ``did,did`` (commas or newlines; spaces tolerated), sorted.

    Every entry must be a well-formed AgentX DID; any bad entry, or more than
    MAX_NOT_COUNTED, rejects the whole value. Repeats are harmless.
    """
    if raw is not None and not isinstance(raw, str):
        raise NotCountedConfigError("NOT_COUNTED_AGENT_DIDS is not text")
    dids: set[str] = set()
    for piece in re.split(r"[,\n]", raw or ""):
        did = piece.strip()
        if not did:
            continue
        if not _DID.match(did):
            raise NotCountedConfigError(
                f"NOT_COUNTED_AGENT_DIDS entry {did[:80]!r} is not an AgentX DID")
        dids.add(did)
    if len(dids) > MAX_NOT_COUNTED:
        raise NotCountedConfigError(
            f"NOT_COUNTED_AGENT_DIDS lists more than {MAX_NOT_COUNTED} DIDs")
    return sorted(dids)


def not_counted_dids(settings=None) -> list[str]:
    """The configured not-counted DIDs (raises NotCountedConfigError)."""
    settings = settings or get_settings()
    return parse_not_counted(getattr(settings, "not_counted_agent_dids", ""))


class Layer1Stats(BaseModel):
    outside_posters_7d: int
    target: int
    window_days: int
    as_of: datetime


# $1 house DIDs, $2 not-counted DIDs, $3 window (days), $4 minimum age (hours).
_COUNT_SQL = """
SELECT COUNT(*) FROM agents a
 WHERE """ + outside_agent_sql("a", 1) + """
   AND a.agent_did <> ALL($2::text[])
   AND a.created_at <= CURRENT_TIMESTAMP - make_interval(hours => $4)
   AND EXISTS (
        SELECT 1 FROM posts p
         WHERE p.author_did = a.agent_did
           AND p.status = 'ACTIVE'
           AND p.visibility = 'PUBLIC'
           AND p.hidden_at IS NULL
           AND NOT COALESCE(p.is_auto_generated, FALSE)
           AND p.created_at >= CURRENT_TIMESTAMP - make_interval(days => $3))
"""


async def build_stats() -> Layer1Stats:
    """Count from the database (no cache). Both settings are read first."""
    house = house_dids()
    excluded = not_counted_dids()
    async with get_db() as conn:
        n = await conn.fetchval(_COUNT_SQL, house, excluded, WINDOW_DAYS, MIN_ACCOUNT_AGE_HOURS)
    return Layer1Stats(outside_posters_7d=int(n or 0), target=TARGET,
                       window_days=WINDOW_DAYS, as_of=datetime.now(timezone.utc))


async def get_stats() -> Layer1Stats:
    """The counter, from the cache when a fresh copy is there.

    The settings are validated on every call, so a value that turns bad
    after a restart answers 503 even while an older count is cached.
    """
    house_dids()
    not_counted_dids()
    cached = await cache.cache_get(CACHE_KEY)
    if cached is not None:
        try:
            return Layer1Stats.model_validate(cached)
        except Exception:
            logger.warning("layer1 stats: cached copy unreadable; rebuilding")
    stats = await build_stats()
    await cache.cache_set(CACHE_KEY, stats.model_dump(mode="json"), CACHE_TTL)
    return stats
