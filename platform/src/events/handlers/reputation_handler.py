"""
AgentX Event Bus — Reputation Handler
═══════════════════════════════════════
Phase 7: Event-Driven Architecture

Handles TASK_COMPLETED and TASK_FAILED events from the agentx.events stream.

This is the event-driven path for reputation updates.  The existing direct-call
path (task_service → reputation.record_task_completed) is preserved for
backward compatibility (Phase 7 requirement: do NOT remove existing service
calls).

The handler is idempotent since S9-9b: the reputation service keys the trust
event on the task id (``trust_events.dedupe_key``, UNIQUE), so the direct call
and this handler together record one event, not two. It also takes nothing
from the bus message on trust: who the executor is, and whether a funded
reward was paid, are read from the task row.
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
    from ...services.reputation import record_task_completed

    task_id = event.payload.get("task_id")

    if event.event_type == EventType.TASK_COMPLETED:
        if not task_id:
            logger.warning(
                "reputation_handler: no task_id in event %s (type=%s) — skipping",
                event.event_id, event.event_type,
            )
            return
        outcome = await record_task_completed(task_id, source="event_bus")
        logger.debug(
            "reputation_handler: task_completed task=%s -> %s", task_id, outcome,
        )

    elif event.event_type == EventType.TASK_FAILED:
        # No trust change from the bus: a failure costs trust only when the
        # executor reports it themselves, and only the route that took the
        # report knows who made it (routers/tasks.update_task records it).
        logger.debug("reputation_handler: task_failed task=%s — no trust change", task_id)

    else:
        logger.warning(
            "reputation_handler received unexpected event_type=%s", event.event_type
        )
