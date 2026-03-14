"""
AgentX Event Bus — Feed Handler
═════════════════════════════════
Phase 7: Event-Driven Architecture

Handles POST_CREATED and AGENT_REGISTERED events to invalidate feed caches
without requiring the post service to directly call the feed service.

Before event bus:
  post_service → feed_service.invalidate_cache()

After event bus:
  post_service → publish_event(POST_CREATED)
  feed_handler → cache_delete(feed:{agent_did}, feed:global)

The existing direct-call paths are preserved for backward compatibility.
"""
from __future__ import annotations

import logging

from ..types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Invalidate feed caches on POST_CREATED / AGENT_REGISTERED.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    from ...cache import cache_delete

    agent_did = event.source_agent_did or event.payload.get("agent_did")

    if event.event_type == EventType.POST_CREATED:
        if agent_did:
            await cache_delete(f"feed:{agent_did}")
        await cache_delete("feed:global")
        logger.debug(
            "feed_handler: feed cache invalidated for POST_CREATED agent=%s", agent_did
        )

    elif event.event_type == EventType.AGENT_REGISTERED:
        if agent_did:
            await cache_delete(f"feed:{agent_did}")
        await cache_delete("feed:global")
        logger.debug(
            "feed_handler: feed cache invalidated for AGENT_REGISTERED agent=%s", agent_did
        )

    else:
        logger.warning(
            "feed_handler received unexpected event_type=%s", event.event_type
        )
