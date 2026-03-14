"""
AgentX Event Bus — Reputation Handler
═══════════════════════════════════════
Phase 7: Event-Driven Architecture

Handles TASK_COMPLETED and TASK_FAILED events from the agentx.events stream
and updates agent trust scores via the reputation service.

This is the event-driven path for reputation updates.  The existing direct-call
path (task_service → reputation.record_event) is preserved for backward
compatibility (Phase 7 requirement: do NOT remove existing service calls).

The handler is intentionally idempotent — reputation.record_event is
guarded by unique event keys in the trust_events table.
"""
from __future__ import annotations

import logging

from ..types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Dispatch TASK_COMPLETED / TASK_FAILED to the reputation service.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    # Lazy import to avoid circular imports at module load time
    from ...services.reputation import record_event

    agent_did = event.source_agent_did or event.payload.get("agent_did")
    task_id   = event.payload.get("task_id")

    if not agent_did:
        logger.warning(
            "reputation_handler: no agent_did in event %s (type=%s) — skipping",
            event.event_id, event.event_type,
        )
        return

    if event.event_type == EventType.TASK_COMPLETED:
        await record_event(
            agent_did,
            "task_completed",
            {"task_id": task_id, "source": "event_bus"},
        )
        logger.debug(
            "reputation_handler: task_completed recorded for agent=%s task=%s",
            agent_did, task_id,
        )

    elif event.event_type == EventType.TASK_FAILED:
        await record_event(
            agent_did,
            "task_failed",
            {"task_id": task_id, "source": "event_bus"},
        )
        logger.debug(
            "reputation_handler: task_failed recorded for agent=%s task=%s",
            agent_did, task_id,
        )

    else:
        logger.warning(
            "reputation_handler received unexpected event_type=%s", event.event_type
        )
