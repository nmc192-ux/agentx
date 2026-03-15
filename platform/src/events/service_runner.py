"""
AgentX Event Bus — Service-Layer Consumer Runner
═════════════════════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

``run_service_consumers()`` is the long-running entry-point for the
Phase 12.5 service consumer tier.  It operates on a *separate* Redis Stream
consumer group (``agentx-service-layer``) so that every event on
``agentx.events`` is delivered independently to BOTH:

  • The Phase-7 handler group  (``agentx-services``)
  • The Phase-12.5 service group (``agentx-service-layer``)

Dispatch table
──────────────
  CONTRACT_COMPLETED            → contract_consumer.handle
  CONTRACT_RESULT_SUBMITTED     → contract_consumer.handle
  TASK_REWARD_RELEASED          → economy_consumer.handle
  TOKEN_TRANSFER                → economy_consumer.handle
  TREASURY_REWARD               → economy_consumer.handle
  TASK_COMPLETED                → reputation_consumer.handle
  CONTRACT_VERIFIED             → reputation_consumer.handle
  VERIFICATION_SUBMITTED        → reputation_consumer.handle
  CONTRACT_VERIFICATION_REQUESTED → verification_consumer.handle

Usage
─────
    import asyncio
    from src.events.service_runner import run_service_consumers
    asyncio.run(run_service_consumers())

Or as a FastAPI background task / asyncio.create_task() in the lifespan.

Design notes
────────────
• Uses its own consumer group so it does not interfere with Phase-7 handlers.
• Handler failures are caught and logged; the loop continues.
• ACK is sent after every event regardless of handler success to prevent
  stuck pending-delivery queues.
• consume_events() hard-codes the Phase-7 group, so this runner implements
  its own XREADGROUP loop using the same Redis client.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from .bus import STREAM_NAME, get_bus_client
from .types import AgentXEvent

logger = logging.getLogger(__name__)

# ── Service consumer group constants ─────────────────────────────────────────

SERVICE_CONSUMER_GROUP = "agentx-service-layer"
SERVICE_CONSUMER_NAME  = f"agentx-svc-consumer-{socket.gethostname()}"

# ── Dispatch table ────────────────────────────────────────────────────────────

def _build_handlers() -> dict[str, Any]:
    """
    Build the service-layer event dispatch table.

    Imports are deferred here (not at module top) to avoid pulling in heavy
    service dependencies during testing unless the runner is actually called.
    """
    from ..services.consumers import (
        contract_consumer,
        discovery_consumer,
        economy_consumer,
        reputation_consumer,
        verification_consumer,
    )

    def _chain(*handlers):
        """Return a single async handler that calls all supplied handlers in order."""
        async def _multi(event):
            for h in handlers:
                try:
                    await h(event)
                except Exception as exc:  # pragma: no cover
                    logger.warning("_chain: handler %s raised: %s", h, exc)
        return _multi

    return {
        # Contract lifecycle
        "CONTRACT_COMPLETED":              _chain(contract_consumer.handle,
                                                  discovery_consumer.handle),
        "CONTRACT_RESULT_SUBMITTED":       contract_consumer.handle,
        # Economy
        "TASK_REWARD_RELEASED":            economy_consumer.handle,
        "TOKEN_TRANSFER":                  economy_consumer.handle,
        "TREASURY_REWARD":                 economy_consumer.handle,
        # Reputation + Discovery
        "TASK_COMPLETED":                  _chain(reputation_consumer.handle,
                                                  discovery_consumer.handle),
        "CONTRACT_VERIFIED":               _chain(reputation_consumer.handle,
                                                  discovery_consumer.handle),
        "VERIFICATION_SUBMITTED":          reputation_consumer.handle,
        # Verification
        "CONTRACT_VERIFICATION_REQUESTED": verification_consumer.handle,
        # Discovery (Phase 16) — bounty rewards
        "BOUNTY_REWARD_DISTRIBUTED":       discovery_consumer.handle,
    }


# ── Consumer group bootstrap ──────────────────────────────────────────────────

async def _ensure_service_consumer_group() -> bool:
    """
    Create the ``agentx-service-layer`` consumer group if it does not exist.

    Returns True on success (including BUSYGROUP), False if Redis unavailable
    or an unexpected error occurred.
    """
    redis = get_bus_client()
    if redis is None:
        logger.warning(
            "service_runner: Redis unavailable; service consumer group not initialised"
        )
        return False

    try:
        await redis.xgroup_create(
            name=STREAM_NAME,
            groupname=SERVICE_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
        logger.info(
            "Service consumer group '%s' created on stream '%s'",
            SERVICE_CONSUMER_GROUP, STREAM_NAME,
        )
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            logger.debug(
                "Service consumer group '%s' already exists (BUSYGROUP)",
                SERVICE_CONSUMER_GROUP,
            )
        else:
            logger.warning("_ensure_service_consumer_group error: %s", exc)
            return False

    return True


# ── ACK helper ────────────────────────────────────────────────────────────────

async def _ack(redis: Any, stream_id: str) -> None:
    """Acknowledge a processed event so it leaves the pending-delivery list."""
    try:
        await redis.xack(STREAM_NAME, SERVICE_CONSUMER_GROUP, stream_id)
    except Exception as exc:
        logger.warning("service_runner: XACK failed stream_id=%s: %s", stream_id, exc)


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_service_consumers(
    consumer_name: str = SERVICE_CONSUMER_NAME,
    batch_size: int = 10,
    block_ms: int = 5_000,
) -> None:
    """
    Start the service-layer event consumer loop.

    Reads events from ``agentx.events`` using the ``agentx-service-layer``
    consumer group and dispatches each event to the registered handler.

    This function runs indefinitely (designed for asyncio.create_task or a
    dedicated worker process).  It exits gracefully on CancelledError.

    Args:
        consumer_name: Unique consumer identifier within the consumer group.
        batch_size:    Maximum events read per XREADGROUP call.
        block_ms:      Milliseconds to block waiting for new events.
    """
    await _ensure_service_consumer_group()
    handlers = _build_handlers()

    redis = get_bus_client()
    if redis is None:
        logger.warning("service_runner: Redis unavailable; service consumer not starting")
        return

    logger.info(
        "Service consumer started: group=%s consumer=%s",
        SERVICE_CONSUMER_GROUP, consumer_name,
    )

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=SERVICE_CONSUMER_GROUP,
                consumername=consumer_name,
                streams={STREAM_NAME: ">"},
                count=batch_size,
                block=block_ms,
            )
            if not results:
                continue

            for _stream, entries in results:
                for stream_id, fields in entries:
                    # Parse event — ACK malformed messages to unblock the queue
                    try:
                        event = AgentXEvent.from_stream_fields(fields)
                    except Exception as parse_exc:
                        logger.warning(
                            "service_runner: failed to parse event stream_id=%s: %s",
                            stream_id, parse_exc,
                        )
                        await _ack(redis, stream_id)
                        continue

                    # Dispatch to handler
                    handler = handlers.get(event.event_type.value)
                    if handler is not None:
                        try:
                            await handler(event)
                        except Exception as handler_exc:
                            logger.error(
                                "service_runner: handler error event_type=%s "
                                "stream_id=%s: %s",
                                event.event_type, stream_id, handler_exc,
                            )
                    else:
                        logger.debug(
                            "service_runner: no handler for event_type=%s — skipping",
                            event.event_type,
                        )

                    await _ack(redis, stream_id)

        except asyncio.CancelledError:
            logger.info("service_runner: consumer loop cancelled — shutting down")
            raise
        except Exception as loop_exc:
            logger.error("service_runner: consumer loop error: %s", loop_exc)
            await asyncio.sleep(1)
