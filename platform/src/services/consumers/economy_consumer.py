"""
AgentX — Economy Event Consumer
═════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

Handles economic events from the agentx.events stream and calls the
appropriate service-layer functions.

Events handled
──────────────
  TASK_REWARD_RELEASED   — capture post-release economic metrics snapshot.
  TOKEN_TRANSFER         — audit log for token movement between wallets.
  TREASURY_REWARD        — capture post-revenue economic metrics snapshot.

Design notes
────────────
• Lazy imports avoid circular-import issues at module load time.
• All service failures are caught, logged, and swallowed — this consumer
  must never crash the consumer loop.
• Existing inline calls inside token_service / economy_service are preserved
  (additive-only pattern).
"""
from __future__ import annotations

import logging

from ...events.types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


async def handle(event: AgentXEvent) -> None:
    """
    Dispatch economy events to the service layer.

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    if event.event_type == EventType.TASK_REWARD_RELEASED:
        await _handle_reward_released(event)
    elif event.event_type == EventType.TOKEN_TRANSFER:
        await _handle_token_transfer(event)
    elif event.event_type == EventType.TREASURY_REWARD:
        await _handle_treasury_reward(event)
    else:
        logger.warning(
            "economy_consumer received unexpected event_type=%s", event.event_type
        )


# ── Private handlers ──────────────────────────────────────────────────────────

async def _handle_reward_released(event: AgentXEvent) -> None:
    """Record an economic metrics snapshot after a task reward is paid out."""
    from ..economy_service import record_metrics  # lazy import

    task_id   = event.payload.get("task_id")
    agent_did = event.source_agent_did or event.payload.get("agent_did")

    logger.debug(
        "economy_consumer: TASK_REWARD_RELEASED task_id=%s agent_did=%s "
        "— recording metrics",
        task_id, agent_did,
    )

    try:
        await record_metrics()
        logger.debug(
            "economy_consumer: metrics recorded after TASK_REWARD_RELEASED task_id=%s",
            task_id,
        )
    except Exception as exc:
        logger.error(
            "economy_consumer: record_metrics failed for TASK_REWARD_RELEASED "
            "task_id=%s: %s",
            task_id, exc,
        )


async def _handle_token_transfer(event: AgentXEvent) -> None:
    """
    Audit-log token transfer events.

    Token transfers are already atomic in token_service; this handler
    provides an event-bus audit hook for observability.
    """
    from_did = event.payload.get("from_agent_did") or event.source_agent_did
    to_did   = event.payload.get("to_agent_did")
    amount   = event.payload.get("amount")

    logger.info(
        "economy_consumer: TOKEN_TRANSFER from=%s to=%s amount=%s",
        from_did, to_did, amount,
    )


async def _handle_treasury_reward(event: AgentXEvent) -> None:
    """Record an economic metrics snapshot after a treasury inflow."""
    from ..economy_service import record_metrics  # lazy import

    source  = event.payload.get("source") or event.source_agent_did
    amount  = event.payload.get("amount")

    logger.debug(
        "economy_consumer: TREASURY_REWARD source=%s amount=%s — recording metrics",
        source, amount,
    )

    try:
        await record_metrics()
        logger.debug("economy_consumer: metrics recorded after TREASURY_REWARD")
    except Exception as exc:
        logger.error(
            "economy_consumer: record_metrics failed for TREASURY_REWARD: %s", exc
        )
