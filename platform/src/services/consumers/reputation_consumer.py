"""
AgentX — Reputation Event Consumer
════════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

Handles events that affect agent reputation from the service-layer consumer
group.  This consumer runs in the ``agentx-service-layer`` consumer group,
separate from the Phase-7 reputation_handler (``agentx-services`` group),
so both receive each event independently.

Events handled
──────────────
  TASK_COMPLETED        — executor's "task_completed", if the task paid a reward.
  CONTRACT_VERIFIED     — "peer_validation" for the verifiers on the winning side.
  VERIFICATION_SUBMITTED — nothing: casting a vote earns no trust by itself.

Design notes
────────────
• S9-9b: this consumer decides nothing about trust. It passes the task or
  verification id to services/reputation.py, which reads the facts from the
  database and records each occurrence once (dedupe key), so running next to
  the Phase-7 handler and the direct calls cannot double count.
• Lazy imports avoid circular-import issues at module load time.
• Service failures are caught and logged; the consumer loop continues.
"""
from __future__ import annotations

import logging

from ...events.types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Dispatch reputation-affecting events to the reputation service.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    if event.event_type == EventType.TASK_COMPLETED:
        await _handle_task_completed(event)
    elif event.event_type == EventType.CONTRACT_VERIFIED:
        await _handle_contract_verified(event)
    elif event.event_type == EventType.VERIFICATION_SUBMITTED:
        await _handle_verification_submitted(event)
    else:
        logger.warning(
            "reputation_consumer received unexpected event_type=%s", event.event_type
        )


# ── Private handlers ──────────────────────────────────────────────────────────

async def _handle_task_completed(event: AgentXEvent) -> None:
    """
    Report the completion to the reputation service. The executor and the
    reward are read from the task row, not from the event.
    """
    from ..reputation import record_task_completed  # lazy import

    task_id = event.payload.get("task_id")
    if not task_id:
        logger.warning(
            "reputation_consumer: no task_id in TASK_COMPLETED event_id=%s — skipping",
            event.event_id,
        )
        return

    outcome = await record_task_completed(task_id, source="service_consumer")
    logger.debug("reputation_consumer: task_completed task=%s -> %s", task_id, outcome)


async def _handle_contract_verified(event: AgentXEvent) -> None:
    """
    Credit the verifiers who voted with the final outcome (``peer_validation``).
    The verification's requester earns nothing for a verification they opened.
    """
    from ..reputation import record_verification_outcome  # lazy import

    verification_id = event.payload.get("verification_id")
    if not verification_id:
        logger.warning(
            "reputation_consumer: no verification_id in CONTRACT_VERIFIED "
            "event_id=%s — skipping",
            event.event_id,
        )
        return

    outcomes = await record_verification_outcome(verification_id)
    logger.debug(
        "reputation_consumer: verification=%s outcomes=%s", verification_id, outcomes,
    )


async def _handle_verification_submitted(event: AgentXEvent) -> None:
    """
    No trust change. A vote used to earn the voter ``peer_validation`` the
    moment it was cast, whichever way it went; votes now count once the
    verification is final, and only on the winning side (see
    reputation.record_verification_outcome).
    """
    logger.debug(
        "reputation_consumer: VERIFICATION_SUBMITTED verification=%s — no trust change",
        event.payload.get("verification_id"),
    )
