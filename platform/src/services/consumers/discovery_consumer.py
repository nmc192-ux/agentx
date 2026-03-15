"""
AgentX Platform — Discovery Consumer
══════════════════════════════════════
Phase 16: Updates agent_metrics automatically when key events occur.

Handled events
──────────────
  TASK_COMPLETED              → update_agent_metrics for the executor
  CONTRACT_COMPLETED          → update_agent_metrics for assigned_agent_id
  CONTRACT_VERIFIED           → update_agent_metrics for requester_id
  BOUNTY_REWARD_DISTRIBUTED   → update_agent_metrics for recipient

Design
──────
• handler() swallows ALL exceptions — the consumer loop must never crash.
• DID→UUID resolution is attempted inside the handler; if the agent
  cannot be found the event is silently skipped.
• update_agent_metrics() is itself soft-fail (see discovery_service).
"""
from __future__ import annotations

import logging
from uuid import UUID

from ...events.types import AgentXEvent, EventType
from ...services import discovery_service

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """Dispatch discovery metric updates for relevant event types."""
    try:
        await _dispatch(event)
    except Exception:
        logger.warning(
            "discovery_consumer: unhandled exception for event %s",
            event.event_type, exc_info=True,
        )


async def _dispatch(event: AgentXEvent) -> None:
    """Route event to the correct handler."""
    payload = event.payload

    if event.event_type == EventType.TASK_COMPLETED:
        agent_id_str = payload.get("agent_id") or payload.get("executor_agent_id")
        if agent_id_str:
            await discovery_service.update_agent_metrics(_to_uuid(agent_id_str))

    elif event.event_type == EventType.CONTRACT_COMPLETED:
        agent_id_str = payload.get("assigned_agent_id") or payload.get("agent_id")
        if agent_id_str:
            await discovery_service.update_agent_metrics(_to_uuid(agent_id_str))

    elif event.event_type == EventType.CONTRACT_VERIFIED:
        # The requester (contract creator) may benefit, but the real actors
        # are the verifiers.  We refresh the agent identified by agent_id.
        agent_id_str = payload.get("agent_id") or payload.get("requester_id")
        if agent_id_str:
            await discovery_service.update_agent_metrics(_to_uuid(agent_id_str))

    elif event.event_type == EventType.BOUNTY_REWARD_DISTRIBUTED:
        agent_id_str = payload.get("recipient_id") or payload.get("agent_id")
        if agent_id_str:
            await discovery_service.update_agent_metrics(_to_uuid(agent_id_str))


def _to_uuid(value: str) -> UUID:
    return UUID(str(value))
