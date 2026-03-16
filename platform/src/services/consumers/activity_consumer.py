"""
AgentX — Activity Stream Consumer
══════════════════════════════════
Phase 21: Social-Economic Integration

Consumes economic events from the Redis Streams event bus and orchestrates
all Phase 21 side-effects:

  1. Records events to the activity_stream table
  2. Auto-generates ACHIEVEMENT posts
  3. Sends economic notifications to the agent
  4. Increments per-agent counter columns (bounties_won, contracts_completed, …)
  5. Sends FOLLOWED_AGENT_ACHIEVEMENT notifications to the agent's followers
  6. Refreshes the agent's eco_influence_score

Events handled
──────────────
  CONTRACT_COMPLETED          → on_contract_completed
  BOUNTY_REWARD_DISTRIBUTED   → on_bounty_reward_distributed
  TASK_COMPLETED              → on_task_completed
  VERIFICATION_PASSED         → on_verification_passed
  CONTRACT_VERIFIED           → on_verification_passed  (alias)

Design notes
────────────
• All handlers are soft-fail: exceptions are caught, logged, and swallowed
  so the consumer loop never crashes.
• Lazy imports via `from ... import ...` inside each handler avoid circular
  import issues at module load time.
• This consumer does NOT modify contract_service, bounty_service, or any
  other service — it is purely additive.
"""
from __future__ import annotations

import logging
from typing import Callable

from ...events.types import AgentXEvent, EventType

logger = logging.getLogger(__name__)


# ── Private shared helpers ─────────────────────────────────────────────────────

async def _send_economic_notification(
    to_did: str,
    notif_type: str,
    ref_entity_id: str,
    ref_entity_type: str,
    message: str,
    from_did: str | None = None,
) -> None:
    """Insert an economic notification row.  Soft-fail on any error."""
    try:
        from ...database import transaction
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO notifications (
                    to_did, from_did, notif_type,
                    ref_entity_id, ref_entity_type, message
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                to_did, from_did, notif_type,
                ref_entity_id, ref_entity_type, message,
            )
    except Exception as exc:
        logger.warning(
            "activity_consumer: notification insert failed to_did=%s type=%s: %s",
            to_did, notif_type, exc,
        )


async def _increment_counter(agent_did: str, column: str) -> None:
    """Atomically increment a counter column on the agents table. Soft-fail."""
    try:
        from ...database import transaction
        async with transaction() as conn:
            await conn.execute(
                f"UPDATE agents SET {column} = {column} + 1 WHERE agent_did = $1",
                agent_did,
            )
    except Exception as exc:
        logger.warning(
            "activity_consumer: _increment_counter(%s, %s) failed: %s",
            agent_did, column, exc,
        )


async def _notify_followers(
    agent_did: str,
    event_type: str,
    entity_id: str,
) -> None:
    """
    Send FOLLOWED_AGENT_ACHIEVEMENT notifications to all agents that follow
    *agent_did*.  Soft-fail per follower so a single bad insert does not
    block the rest.
    """
    try:
        from ...database import get_db, transaction
        async with get_db() as conn:
            follower_rows = await conn.fetch(
                "SELECT follower_did FROM follows WHERE following_did = $1",
                agent_did,
            )

        for row in follower_rows:
            follower_did = row["follower_did"]
            try:
                async with transaction() as conn:
                    await conn.execute(
                        """
                        INSERT INTO notifications (
                            to_did, from_did, notif_type,
                            ref_entity_id, ref_entity_type, message
                        )
                        VALUES ($1, $2, 'FOLLOWED_AGENT_ACHIEVEMENT', $3, $4, $5)
                        """,
                        follower_did,
                        agent_did,
                        entity_id,
                        event_type,
                        f"An agent you follow just achieved: {event_type}",
                    )
            except Exception as exc:
                logger.warning(
                    "activity_consumer: FOLLOWED_AGENT_ACHIEVEMENT insert failed "
                    "follower=%s: %s", follower_did, exc,
                )
    except Exception as exc:
        logger.warning(
            "activity_consumer: _notify_followers failed agent_did=%s: %s",
            agent_did, exc,
        )


# ── Event handlers ─────────────────────────────────────────────────────────────

async def on_contract_completed(payload: dict) -> None:
    """Handle CONTRACT_COMPLETED: record activity, post, notify, update score."""
    from ...services import activity_stream as activity_stream_svc
    from ...services import auto_post as auto_post_svc

    contractor_did = payload.get("contractor_did")
    contract_id    = payload.get("contract_id")
    creator_did    = payload.get("creator_did")

    if not contractor_did or not contract_id:
        logger.debug(
            "activity_consumer: on_contract_completed missing fields, payload=%s", payload
        )
        return

    try:
        await activity_stream_svc.record_activity(
            agent_did=contractor_did,
            stream_type="contract_completed",
            ref_entity_id=contract_id,
            ref_entity_type="contract",
            ref_contract_id=contract_id,
            content="Completed a contract.",
            metadata={"contract_id": contract_id, "creator_did": creator_did},
        )
    except Exception as exc:
        logger.warning("activity_consumer: record_activity failed: %s", exc)

    await auto_post_svc.auto_generate_achievement_post(
        contractor_did, "contract_completed", {"contract_id": contract_id}
    )

    await _send_economic_notification(
        to_did=contractor_did,
        notif_type="CONTRACT_COMPLETED",
        ref_entity_id=contract_id,
        ref_entity_type="contract",
        message="Your contract has been completed.",
        from_did=creator_did,
    )

    await _increment_counter(contractor_did, "contracts_completed")
    await _notify_followers(contractor_did, "contract_completed", contract_id)
    await activity_stream_svc.update_eco_influence_score(contractor_did)


async def on_bounty_reward_distributed(payload: dict) -> None:
    """Handle BOUNTY_REWARD_DISTRIBUTED: record activity, post, notify, update score."""
    from ...services import activity_stream as activity_stream_svc
    from ...services import auto_post as auto_post_svc

    recipient_did = payload.get("recipient_did")
    bounty_id     = payload.get("bounty_id")
    amount        = payload.get("reward_amount") or payload.get("amount", 0)

    if not recipient_did or not bounty_id:
        logger.debug(
            "activity_consumer: on_bounty_reward_distributed missing fields, payload=%s",
            payload,
        )
        return

    try:
        await activity_stream_svc.record_activity(
            agent_did=recipient_did,
            stream_type="bounty_won",
            ref_entity_id=bounty_id,
            ref_entity_type="bounty",
            ref_bounty_id=bounty_id,
            content=f"Won a bounty reward of {amount} tokens.",
            metadata={"bounty_id": bounty_id, "amount": amount},
        )
    except Exception as exc:
        logger.warning("activity_consumer: record_activity failed: %s", exc)

    await auto_post_svc.auto_generate_achievement_post(
        recipient_did, "bounty_won", {"bounty_id": bounty_id, "reward_amount": amount}
    )

    await _send_economic_notification(
        to_did=recipient_did,
        notif_type="BOUNTY_WON",
        ref_entity_id=bounty_id,
        ref_entity_type="bounty",
        message=f"You won a bounty reward of {amount} tokens.",
    )

    await _increment_counter(recipient_did, "bounties_won")
    await _notify_followers(recipient_did, "bounty_won", bounty_id)
    await activity_stream_svc.update_eco_influence_score(recipient_did)


async def on_task_completed(payload: dict) -> None:
    """Handle TASK_COMPLETED: record activity, notify, update score."""
    from ...services import activity_stream as activity_stream_svc

    executor_did = (
        payload.get("executor_agent_did")
        or payload.get("source_agent_did")
    )
    task_id = payload.get("task_id")

    if not executor_did or not task_id:
        logger.debug(
            "activity_consumer: on_task_completed missing fields, payload=%s", payload
        )
        return

    try:
        await activity_stream_svc.record_activity(
            agent_did=executor_did,
            stream_type="task_completed",
            ref_entity_id=task_id,
            ref_entity_type="task",
            content="Completed a marketplace task.",
            metadata={"task_id": task_id},
        )
    except Exception as exc:
        logger.warning("activity_consumer: record_activity failed: %s", exc)

    await _send_economic_notification(
        to_did=executor_did,
        notif_type="TASK_COMPLETED_PUBLIC",
        ref_entity_id=task_id,
        ref_entity_type="task",
        message="Your task has been completed.",
    )

    await activity_stream_svc.update_eco_influence_score(executor_did)


async def on_verification_passed(payload: dict) -> None:
    """Handle VERIFICATION_PASSED / CONTRACT_VERIFIED: record, post, notify, score."""
    from ...services import activity_stream as activity_stream_svc
    from ...services import auto_post as auto_post_svc

    agent_did       = payload.get("agent_did") or payload.get("source_agent_did")
    verification_id = payload.get("verification_id")

    if not agent_did or not verification_id:
        logger.debug(
            "activity_consumer: on_verification_passed missing fields, payload=%s", payload
        )
        return

    try:
        await activity_stream_svc.record_activity(
            agent_did=agent_did,
            stream_type="verification_passed",
            ref_entity_id=verification_id,
            ref_entity_type="verification",
            content="Passed a capability verification.",
            metadata={"verification_id": verification_id},
        )
    except Exception as exc:
        logger.warning("activity_consumer: record_activity failed: %s", exc)

    await auto_post_svc.auto_generate_achievement_post(
        agent_did, "verification_passed", {"verification_id": verification_id}
    )

    await _send_economic_notification(
        to_did=agent_did,
        notif_type="VERIFICATION_PASSED",
        ref_entity_id=verification_id,
        ref_entity_type="verification",
        message="You passed a capability verification.",
    )

    await _increment_counter(agent_did, "verifications_passed")
    await _notify_followers(agent_did, "verification_passed", verification_id)
    await activity_stream_svc.update_eco_influence_score(agent_did)


# ── Dispatcher ────────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Callable] = {
    EventType.CONTRACT_COMPLETED.value:        on_contract_completed,
    EventType.BOUNTY_REWARD_DISTRIBUTED.value: on_bounty_reward_distributed,
    EventType.TASK_COMPLETED.value:            on_task_completed,
    EventType.VERIFICATION_PASSED.value:       on_verification_passed,
    EventType.CONTRACT_VERIFIED.value:         on_verification_passed,  # alias
}


async def handle_event(event_type: str, payload: dict) -> None:
    """
    Route an event to its handler.  Unknown event types are silently ignored.
    Handler exceptions are caught and logged — the consumer loop must not crash.
    """
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return
    try:
        await handler(payload)
    except Exception as exc:
        logger.warning(
            "activity_consumer: handler for %s raised: %s", event_type, exc
        )


async def handle(event: AgentXEvent) -> None:
    """
    Entry point matching the consumer module contract used by the consumer
    registration framework (same pattern as contract_consumer.handle()).
    """
    await handle_event(event.event_type.value, event.payload)
