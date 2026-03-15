"""
AgentX — Contract Event Consumer
══════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

Handles contract lifecycle events from the agentx.events stream and calls
the appropriate service-layer functions.

Events handled
──────────────
  CONTRACT_COMPLETED          — record economic metrics after contract closes.
  CONTRACT_RESULT_SUBMITTED   — log audit trail entry for the submitted result.

Design notes
────────────
• Lazy imports avoid circular-import issues at module load time.
• All service failures are caught, logged, and swallowed — this consumer
  must never crash the consumer loop.
• Direct service calls are NOT removed from contract_service; this consumer
  is purely additive (Phase 12.5 requirement).
"""
from __future__ import annotations

import logging

from ...events.types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Dispatch CONTRACT_COMPLETED / CONTRACT_RESULT_SUBMITTED to service layer.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    if event.event_type == EventType.CONTRACT_COMPLETED:
        await _handle_contract_completed(event)
    elif event.event_type == EventType.CONTRACT_RESULT_SUBMITTED:
        await _handle_result_submitted(event)
    else:
        logger.warning(
            "contract_consumer received unexpected event_type=%s", event.event_type
        )


# ── Private handlers ──────────────────────────────────────────────────────────

async def _handle_contract_completed(event: AgentXEvent) -> None:
    """
    Record economic metrics snapshot when a contract completes.

    Metrics capture treasury balance, total staked, fees collected etc.
    Failure is soft: the consumer loop continues unaffected.
    """
    from ..economy_service import record_metrics  # lazy import

    contract_id = event.payload.get("contract_id")
    logger.debug(
        "contract_consumer: CONTRACT_COMPLETED contract_id=%s — recording metrics",
        contract_id,
    )

    try:
        await record_metrics()
        logger.debug(
            "contract_consumer: metrics recorded after CONTRACT_COMPLETED contract_id=%s",
            contract_id,
        )
    except Exception as exc:
        logger.error(
            "contract_consumer: record_metrics failed for CONTRACT_COMPLETED "
            "contract_id=%s: %s",
            contract_id, exc,
        )


async def _handle_result_submitted(event: AgentXEvent) -> None:
    """
    Log an audit entry when a contractor submits a result.

    No heavy service call is needed here today; this handler exists as the
    correct extension point for future verification-trigger logic.
    """
    contract_id = event.payload.get("contract_id")
    result_id   = event.payload.get("result_id")
    agent_did   = event.source_agent_did or event.payload.get("agent_did")

    logger.info(
        "contract_consumer: CONTRACT_RESULT_SUBMITTED contract_id=%s "
        "result_id=%s agent_did=%s",
        contract_id, result_id, agent_did,
    )
