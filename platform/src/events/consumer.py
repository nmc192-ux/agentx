"""
AgentX Event Bus — Consumer
════════════════════════════
Phase 7: Event-Driven Architecture

EventConsumer wraps Redis XREADGROUP-based consumption with automatic ACK
and safe handler dispatch. Designed to run as a long-lived asyncio task.

Usage:
    from src.events.consumer import run_consumer
    from src.events.handlers import HANDLERS

    await run_consumer(HANDLERS)
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import AsyncGenerator
from typing import Any

from .bus import CONSUMER_GROUP, STREAM_NAME, get_bus_client
from .types import AgentXEvent

logger = logging.getLogger(__name__)

# Unique consumer name per process/host (prevents message duplication)
DEFAULT_CONSUMER = f"agentx-consumer-{socket.gethostname()}"


# ── Low-level generator ───────────────────────────────────────────────────────

async def consume_events(
    consumer_name: str = DEFAULT_CONSUMER,
    batch_size: int = 10,
    block_ms: int = 5_000,
) -> AsyncGenerator[tuple[str, AgentXEvent], None]:
    """
    Async generator that yields (stream_id, AgentXEvent) tuples.

    Reads pending messages from the agentx.events consumer group using
    XREADGROUP with ">" (deliver only new, undelivered messages).
    The caller is responsible for acknowledging each event via ack_event().

    Args:
        consumer_name: Unique identifier for this consumer within the group.
        batch_size:    Maximum events delivered per XREADGROUP call.
        block_ms:      How long to block waiting for new events (milliseconds).

    Yields:
        (stream_id, AgentXEvent) — stream_id is needed for ACK.
    """
    redis = get_bus_client()
    if redis is None:
        logger.warning("Event consumer: Redis unavailable; not starting")
        return

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=consumer_name,
                streams={STREAM_NAME: ">"},
                count=batch_size,
                block=block_ms,
            )
            if not results:
                continue

            for _stream, entries in results:
                for stream_id, fields in entries:
                    try:
                        event = AgentXEvent.from_stream_fields(fields)
                        yield stream_id, event
                    except Exception as exc:
                        logger.warning(
                            "Failed to parse event stream_id=%s: %s", stream_id, exc
                        )
                        # ACK malformed events so they don't block the queue
                        await ack_event(stream_id)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Event consumer loop error: %s", exc)
            await asyncio.sleep(1)


# ── ACK helper ────────────────────────────────────────────────────────────────

async def ack_event(stream_id: str) -> bool:
    """
    Acknowledge a processed event in the consumer group (XACK).

    Must be called after a handler completes successfully to prevent the
    event from being re-delivered.

    Args:
        stream_id: The Redis stream ID returned from consume_events().

    Returns:
        True if acknowledged, False on failure.
    """
    redis = get_bus_client()
    if redis is None:
        return False
    try:
        await redis.xack(STREAM_NAME, CONSUMER_GROUP, stream_id)
        return True
    except Exception as exc:
        logger.warning("Event ACK failed for stream_id=%s: %s", stream_id, exc)
        return False


# ── High-level consumer loop ──────────────────────────────────────────────────

async def run_consumer(
    handlers: dict[str, Any],
    consumer_name: str = DEFAULT_CONSUMER,
    batch_size: int = 10,
) -> None:
    """
    Run the event consumer loop with automatic handler dispatch.

    Bootstraps the consumer group, then continuously reads events and
    dispatches them to the registered handler for each event_type.
    Unhandled event types are ACK'd and skipped with a debug log.

    Args:
        handlers:      Mapping of event_type string → async callable(AgentXEvent).
        consumer_name: Unique consumer name within the consumer group.
        batch_size:    Events consumed per XREADGROUP call.
    """
    from .bus import ensure_consumer_group

    await ensure_consumer_group()
    logger.info("Event consumer started: consumer_name=%s", consumer_name)

    async for stream_id, event in consume_events(consumer_name, batch_size):
        handler = handlers.get(event.event_type.value)
        if handler is not None:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    "Handler error for %s (stream_id=%s): %s",
                    event.event_type, stream_id, exc,
                )
        else:
            logger.debug("No handler for event_type=%s — skipping", event.event_type)

        await ack_event(stream_id)
