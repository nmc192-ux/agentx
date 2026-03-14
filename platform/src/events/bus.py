"""
AgentX Event Bus — Stream & Consumer Group Infrastructure
══════════════════════════════════════════════════════════
Phase 7: Event-Driven Architecture

Redis Stream configuration (single source of truth):
  Stream:         agentx.events
  Consumer Group: agentx-services

Reuses the shared async Redis client from cache.py to avoid spawning
extra connections. Both publisher and consumer import from here.
"""
from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import Redis

from ..cache import get_cache

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

STREAM_NAME    = "agentx.events"
CONSUMER_GROUP = "agentx-services"


# ── Client access ─────────────────────────────────────────────────────────────

def get_bus_client() -> Optional[Redis]:
    """
    Return the shared async Redis client, or None if unavailable.

    Delegates to cache.get_cache() so that both the cache layer and the
    event bus share a single connection pool.
    """
    return get_cache()


# ── Consumer group bootstrap ──────────────────────────────────────────────────

async def ensure_consumer_group() -> bool:
    """
    Create the consumer group on agentx.events if it does not already exist.

    Uses MKSTREAM so the stream itself is created on first call even if no
    events have been published yet.

    Returns:
        True  — group exists (newly created or pre-existing).
        False — Redis is unavailable or an unexpected error occurred.
    """
    redis = get_bus_client()
    if redis is None:
        logger.warning("Event bus: Redis unavailable; consumer group not initialised")
        return False

    try:
        await redis.xgroup_create(
            name=STREAM_NAME,
            groupname=CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
        logger.info(
            "Consumer group '%s' created on stream '%s'",
            CONSUMER_GROUP, STREAM_NAME,
        )
    except Exception as exc:
        # BUSYGROUP is returned when the group already exists — that is success.
        if "BUSYGROUP" in str(exc):
            logger.debug("Consumer group '%s' already exists (BUSYGROUP)", CONSUMER_GROUP)
        else:
            logger.warning("ensure_consumer_group error: %s", exc)
            return False

    return True
