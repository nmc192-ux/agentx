"""
AgentX Event Bus — Publisher
═════════════════════════════
Phase 7: Event-Driven Architecture

publish_event()      — async XADD for FastAPI services.
publish_event_sync() — synchronous XADD for the worker process which runs
                       in a blocking loop with its own sync Redis connection.

Both variants are fire-and-forget: exceptions are caught, logged as warnings,
and never re-raised. Callers should never fail because the event bus is down.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

# Sync Redis client imported at module level so tests can patch src.events.publisher.Redis
from redis import Redis

logger = logging.getLogger(__name__)


# ── Async publisher (FastAPI / asyncpg services) ──────────────────────────────

async def publish_event(
    event_type: "EventType | str",
    payload: dict[str, Any],
    source_agent_did: str | None = None,
) -> str | None:
    """
    Publish an event to the agentx.events Redis Stream via XADD.

    Fire-and-forget: any Redis failure is logged but never propagated to
    the caller, so existing service flows are never disrupted.

    Args:
        event_type:       EventType enum value or plain string.
        payload:          Arbitrary JSON-serialisable dict.
        source_agent_did: DID of the agent that triggered the event (optional).

    Returns:
        The Redis stream ID (e.g. "1714059123456-0") on success, None on failure.
    """
    from .bus import STREAM_NAME, get_bus_client
    from .types import AgentXEvent, EventType as ET

    # Accept both enum and plain string
    if isinstance(event_type, str):
        try:
            event_type = ET(event_type)
        except ValueError:
            logger.warning("publish_event: unknown event_type %r — skipping", event_type)
            return None

    redis = get_bus_client()
    if redis is None:
        logger.debug("Event bus disabled; skipping publish of %s", event_type)
        return None

    event = AgentXEvent(
        event_type=event_type,
        payload=payload,
        source_agent_did=source_agent_did,
    )

    try:
        stream_id = await redis.xadd(STREAM_NAME, event.to_stream_fields())
        logger.debug(
            "Event published: %s → %s (stream_id=%s)", event_type, STREAM_NAME, stream_id
        )
        return stream_id
    except Exception as exc:
        logger.warning("Event bus XADD failed for %s: %s", event_type, exc)
        return None


# ── Sync publisher (worker process) ──────────────────────────────────────────

def publish_event_sync(
    event_type: str,
    payload: dict[str, Any],
    source_agent_did: str | None = None,
    redis_url: str | None = None,
) -> str | None:
    """
    Synchronous event publisher for the worker process.

    The worker uses blocking redis.Redis (not redis.asyncio) because it runs
    inside a synchronous loop with BRPOP. This variant creates a short-lived
    sync connection, publishes the event, and returns.

    Args:
        event_type:       Plain string event type (e.g. "TASK_COMPLETED").
        payload:          Arbitrary JSON-serialisable dict.
        source_agent_did: DID of the agent that triggered the event (optional).
        redis_url:        Override Redis URL (defaults to REDIS_URL env var).

    Returns:
        The Redis stream ID on success, None on any failure.
    """
    try:
        url = redis_url or os.getenv("REDIS_URL", "redis://:devredis@redis:6379/0")
        r = Redis.from_url(url, decode_responses=True)

        fields = {
            "event_id":         str(uuid.uuid4()),
            "event_type":       event_type,
            "source_agent_did": source_agent_did or "",
            "payload":          json.dumps(payload),
            "timestamp":        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

        stream_id = r.xadd("agentx.events", fields)
        logger.debug("Event published (sync): %s (stream_id=%s)", event_type, stream_id)
        return stream_id

    except Exception as exc:
        logger.warning("Event bus XADD (sync) failed for %s: %s", event_type, exc)
        return None
