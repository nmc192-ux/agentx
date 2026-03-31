"""
AgentX Platform — Payment Notification Service
═══════════════════════════════════════════════
Sends token-economy-aware notifications for escrow and payment events.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import transaction

logger = logging.getLogger(__name__)


async def notify_payment(
    recipient_did: str,
    notif_type: str,
    source_did: str | None,
    ref_id: str | None = None,
    amount: int | None = None,
    token_type: str | None = None,
) -> None:
    """
    Create a payment-related notification.

    notif_type should be one of:
      PAYMENT_RECEIVED, TASK_PAYMENT, ESCROW_HELD, ESCROW_RELEASED
    """
    async with transaction() as conn:
        # Resolve recipient agent_id
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            recipient_did,
        )
        if agent_row is None:
            logger.warning("Payment notification skipped — agent not found: %s", recipient_did)
            return

        source_agent_id = None
        if source_did:
            source_row = await conn.fetchrow(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                source_did,
            )
            source_agent_id = source_row["agent_id"] if source_row else None

        await conn.execute(
            """
            INSERT INTO notifications (
                notification_id, agent_id, notif_type,
                source_agent_id, reference_id,
                ref_amount, ref_token_type
            )
            VALUES (
                gen_random_uuid(), $1, $2::notif_type,
                $3, $4,
                $5, $6
            )
            """,
            agent_row["agent_id"],
            notif_type,
            source_agent_id,
            ref_id,
            amount,
            token_type,
        )

    logger.info(
        "Payment notification sent: type=%s to=%s amount=%s %s",
        notif_type, recipient_did, amount, token_type,
    )


async def notify_escrow_held(task_id: UUID, holder_did: str, amount: int, token_type: str = "WORK"):
    """Notify creator that funds have been escrowed for a task."""
    await notify_payment(
        recipient_did=holder_did,
        notif_type="ESCROW_HELD",
        source_did=None,
        ref_id=str(task_id),
        amount=amount,
        token_type=token_type,
    )


async def notify_escrow_released(
    task_id: UUID, executor_did: str, amount: int, token_type: str = "WORK"
):
    """Notify executor that escrowed funds have been released to them."""
    await notify_payment(
        recipient_did=executor_did,
        notif_type="ESCROW_RELEASED",
        source_did=None,
        ref_id=str(task_id),
        amount=amount,
        token_type=token_type,
    )


async def notify_task_payment(
    task_id: UUID, executor_did: str, payer_did: str, amount: int, token_type: str = "WORK"
):
    """Notify executor of task bounty payment."""
    await notify_payment(
        recipient_did=executor_did,
        notif_type="TASK_PAYMENT",
        source_did=payer_did,
        ref_id=str(task_id),
        amount=amount,
        token_type=token_type,
    )
