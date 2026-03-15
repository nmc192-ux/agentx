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
  TASK_COMPLETED        — reward executor with "task_success" reputation delta.
  CONTRACT_VERIFIED     — reward verifiers / requester with "peer_validation".
  VERIFICATION_SUBMITTED — reward verifier with "peer_validation" delta.

Design notes
────────────
• event_type strings fed to reputation.record_event() must exist in
  EVENT_WEIGHTS (see services/reputation.py).
• "task_success" (weight +0.05) and "peer_validation" (weight +0.03) are
  the canonical keys used here.
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
    Credit the executing agent with a ``task_success`` reputation boost.

    The agent DID is sourced first from ``source_agent_did``, then from the
    payload ``agent_did`` field (defensive fallback).
    """
    from ..reputation import record_event  # lazy import

    agent_did = event.source_agent_did or event.payload.get("agent_did")
    task_id   = event.payload.get("task_id")

    if not agent_did:
        logger.warning(
            "reputation_consumer: no agent_did in TASK_COMPLETED event_id=%s — skipping",
            event.event_id,
        )
        return

    try:
        await record_event(
            agent_did,
            "task_success",
            {"task_id": task_id, "source": "service_consumer"},
        )
        logger.debug(
            "reputation_consumer: task_success recorded agent=%s task=%s",
            agent_did, task_id,
        )
    except Exception as exc:
        logger.error(
            "reputation_consumer: record_event(task_success) failed agent=%s: %s",
            agent_did, exc,
        )


async def _handle_contract_verified(event: AgentXEvent) -> None:
    """
    Credit the requesting agent with a ``peer_validation`` boost when
    their submitted contract result passes verification.
    """
    from ..reputation import record_event  # lazy import

    requester_did     = event.payload.get("requester_did") or event.source_agent_did
    verification_id   = event.payload.get("verification_id")

    if not requester_did:
        logger.warning(
            "reputation_consumer: no requester_did in CONTRACT_VERIFIED "
            "event_id=%s — skipping",
            event.event_id,
        )
        return

    try:
        await record_event(
            requester_did,
            "peer_validation",
            {"verification_id": verification_id, "outcome": "verified", "source": "service_consumer"},
        )
        logger.debug(
            "reputation_consumer: peer_validation recorded requester=%s verification=%s",
            requester_did, verification_id,
        )
    except Exception as exc:
        logger.error(
            "reputation_consumer: record_event(peer_validation) failed "
            "requester=%s: %s",
            requester_did, exc,
        )


async def _handle_verification_submitted(event: AgentXEvent) -> None:
    """
    Credit the voting verifier with a ``peer_validation`` boost for
    participating in the verification process.
    """
    from ..reputation import record_event  # lazy import

    verifier_did    = event.payload.get("verifier_did") or event.source_agent_did
    verification_id = event.payload.get("verification_id")

    if not verifier_did:
        logger.warning(
            "reputation_consumer: no verifier_did in VERIFICATION_SUBMITTED "
            "event_id=%s — skipping",
            event.event_id,
        )
        return

    try:
        await record_event(
            verifier_did,
            "peer_validation",
            {"verification_id": verification_id, "source": "service_consumer"},
        )
        logger.debug(
            "reputation_consumer: peer_validation recorded verifier=%s verification=%s",
            verifier_did, verification_id,
        )
    except Exception as exc:
        logger.error(
            "reputation_consumer: record_event(peer_validation) failed "
            "verifier=%s: %s",
            verifier_did, exc,
        )
