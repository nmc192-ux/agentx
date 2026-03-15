"""
AgentX Platform — Node Consumer
════════════════════════════════
Phase 17: Broadcasts qualifying events to all active peer nodes.

Handled events
──────────────
  CONTRACT_COMPLETED          → broadcast to all active peer nodes
  TASK_COMPLETED              → broadcast to all active peer nodes
  BOUNTY_REWARD_DISTRIBUTED   → broadcast to all active peer nodes

Design
──────
• handle() swallows ALL exceptions — the consumer loop must never crash.
• list_nodes(active_only=True) is called once per event; if no nodes are
  registered the function returns immediately without any HTTP calls.
• For each peer node, post_event() from node_peer_client is called.
  Successful deliveries are logged to node_messages with direction='outbound'.
• node_peer_client is imported at module level for easy test patching.
• node_service is imported at module level (no circular dependency risk).
"""
from __future__ import annotations

import logging

from ...events.types import AgentXEvent, EventType
from ...services import node_service
from ...services.node_peer_client import post_event

logger = logging.getLogger(__name__)

# Event types that should be broadcast to peer nodes
BROADCAST_EVENTS: frozenset[EventType] = frozenset({
    EventType.CONTRACT_COMPLETED,
    EventType.TASK_COMPLETED,
    EventType.BOUNTY_REWARD_DISTRIBUTED,
})


async def handle(event: AgentXEvent) -> None:
    """Broadcast qualifying events to all active peer nodes."""
    try:
        await _dispatch(event)
    except Exception:
        logger.warning(
            "node_consumer: unhandled exception for event %s",
            event.event_type,
            exc_info=True,
        )


async def _dispatch(event: AgentXEvent) -> None:
    """Route the event to peer nodes if applicable."""
    if event.event_type not in BROADCAST_EVENTS:
        return

    event_type_str: str = (
        event.event_type.value
        if hasattr(event.event_type, "value")
        else str(event.event_type)
    )

    nodes = await node_service.list_nodes(active_only=True)
    if not nodes:
        logger.debug("node_consumer: no active peer nodes; skipping broadcast")
        return

    for node in nodes:
        ok = await post_event(
            node_url=node.node_url,
            event_type=event_type_str,
            payload=event.payload,
        )
        if ok:
            try:
                await node_service.send_node_message(
                    node_id=node.node_id,
                    event_type=event_type_str,
                    payload=event.payload,
                    direction="outbound",
                )
            except Exception as exc:
                logger.warning(
                    "node_consumer: failed to log outbound message to %s: %s",
                    node.node_url,
                    exc,
                )
