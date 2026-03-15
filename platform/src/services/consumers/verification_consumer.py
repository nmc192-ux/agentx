"""
AgentX — Verification Event Consumer
══════════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

Handles verification lifecycle events from the agentx.events stream.

Events handled
──────────────
  CONTRACT_VERIFICATION_REQUESTED — attempt to activate any pending verifications
                                     that did not auto-activate (safety net).

Design notes
────────────
• ``create_verification()`` already calls ``_do_activate()`` inline, so in
  the happy path the verification transitions pending → active without this
  consumer.  The consumer acts as a resilient fallback for edge cases where
  the auto-activation did not complete (e.g. a crash mid-transaction).
• If the verification is already active/verified/failed ``assign_verifiers()``
  will raise; the exception is caught and logged.
• Lazy imports avoid circular-import issues at module load time.
• Service failures are caught and logged; the consumer loop continues.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ...events.types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Dispatch CONTRACT_VERIFICATION_REQUESTED to the verification service.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    if event.event_type == EventType.CONTRACT_VERIFICATION_REQUESTED:
        await _handle_verification_requested(event)
    else:
        logger.warning(
            "verification_consumer received unexpected event_type=%s", event.event_type
        )


# ── Private handler ───────────────────────────────────────────────────────────

async def _handle_verification_requested(event: AgentXEvent) -> None:
    """
    Attempt to activate a newly requested verification.

    Because ``create_verification()`` auto-activates, this call is a
    belt-and-suspenders safety net.  If the verification is already active
    (the normal case) ``assign_verifiers()`` raises a ValueError which is
    silently swallowed here.
    """
    from ..verification_service import assign_verifiers  # lazy import

    verification_id_str = event.payload.get("verification_id")
    requester_did       = event.payload.get("requester_did") or event.source_agent_did

    if not verification_id_str:
        logger.warning(
            "verification_consumer: no verification_id in "
            "CONTRACT_VERIFICATION_REQUESTED event_id=%s — skipping",
            event.event_id,
        )
        return

    logger.debug(
        "verification_consumer: CONTRACT_VERIFICATION_REQUESTED "
        "verification_id=%s requester=%s",
        verification_id_str, requester_did,
    )

    try:
        verification_id = UUID(verification_id_str)
        await assign_verifiers(verification_id, requester_did or "system")
        logger.debug(
            "verification_consumer: assign_verifiers succeeded verification_id=%s",
            verification_id_str,
        )
    except ValueError as exc:
        # Already active / verified / failed — expected in the happy path.
        logger.debug(
            "verification_consumer: assign_verifiers skipped verification_id=%s: %s",
            verification_id_str, exc,
        )
    except Exception as exc:
        logger.error(
            "verification_consumer: assign_verifiers failed verification_id=%s: %s",
            verification_id_str, exc,
        )
