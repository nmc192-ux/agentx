"""
AgentX Event Bus — Notification Handler
═════════════════════════════════════════
Phase 7: Event-Driven Architecture

Handles COLLECTIVE_CREATED, COLLECTIVE_JOINED, and TRUST_UPDATED events to
broadcast real-time WebSocket notifications without direct coupling between
the collective/reputation services and the WebSocket events layer.

Before event bus:
  collective_service → services.events.emit_event()

After event bus:
  collective_service → publish_event(COLLECTIVE_CREATED)
  notification_handler → services.events.emit_event()

The existing direct-call paths are preserved for backward compatibility.
"""
from __future__ import annotations

import logging

from ..types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Broadcast COLLECTIVE_CREATED / COLLECTIVE_JOINED / TRUST_UPDATED
    to connected WebSocket clients via the existing events service.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    # Lazy import: avoids circular imports and only pulls in WebSocket layer on demand
    from ...services.events import emit_event

    agent_did = event.source_agent_did or event.payload.get("agent_did") or event.payload.get("owner_did")

    if event.event_type == EventType.COLLECTIVE_CREATED:
        await emit_event(
            "COLLECTIVE_CREATED",
            agent_did,
            event.payload,
        )
        logger.debug(
            "notification_handler: COLLECTIVE_CREATED broadcast collective_id=%s",
            event.payload.get("collective_id"),
        )

    elif event.event_type == EventType.COLLECTIVE_JOINED:
        await emit_event(
            "COLLECTIVE_JOINED",
            agent_did,
            event.payload,
        )
        logger.debug(
            "notification_handler: COLLECTIVE_JOINED broadcast agent=%s collective=%s",
            agent_did, event.payload.get("collective_id"),
        )

    elif event.event_type == EventType.TRUST_UPDATED:
        await emit_event(
            "TRUST_UPDATED",
            agent_did,
            event.payload,
        )
        logger.debug(
            "notification_handler: TRUST_UPDATED broadcast for agent=%s", agent_did
        )

    else:
        logger.warning(
            "notification_handler received unexpected event_type=%s", event.event_type
        )
