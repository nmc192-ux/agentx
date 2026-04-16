"""
AgentX Platform — Task Marketplace Service
═══════════════════════════════════════════
Phase 4: Agent Task Economy
Phase 5: Capability Graph Integration

Business logic for the open marketplace:
  create_task()             — publish an open task
  list_tasks()              — discover available tasks
  submit_bid()              — agent bids on a task
  assign_task()             — creator accepts a bid
  submit_result()           — executor submits task result
  suggest_agents_for_task() — rank agents by capability fit (Phase 5)

All DB access uses asyncpg via get_db() / transaction() context managers.
Redis queue is used to dispatch accepted tasks to the worker.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

from ..cache import enqueue_task  # noqa: E402
from ..database import get_db, transaction  # noqa: E402
from ..events.publisher import publish_event  # noqa: E402
from ..events.types import EventType  # noqa: E402
from ..models.task import (  # noqa: E402
    TaskAssignmentResponse,
    TaskBidResponse,
    TaskResponse,
    TaskResultResponse,
)
from ..models.capability import EligibleAgentResponse  # noqa: E402
from ..services.reputation import record_event  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _row_to_task(row) -> TaskResponse:
    return TaskResponse(
        task_id=row["task_id"],
        creator_agent_id=row["creator_agent_id"],
        task_type=row["task_type"],
        payload=_decode_json(row.get("payload")),
        reward=row["reward"],
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_bid(row) -> TaskBidResponse:
    return TaskBidResponse(
        bid_id=row["bid_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        confidence=float(row["confidence"]),
        bid_price=row["bid_price"],
        created_at=row["created_at"],
    )


def _row_to_assignment(row) -> TaskAssignmentResponse:
    return TaskAssignmentResponse(
        assignment_id=row["assignment_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        status=row["status"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


def _row_to_result(row) -> TaskResultResponse:
    return TaskResultResponse(
        result_id=row["result_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        result_payload=_decode_json(row.get("result_payload")),
        verification_status=row["verification_status"],
        created_at=row["created_at"],
    )


# ── Service Functions ──────────────────────────────────────────────────────────

async def create_task(
    creator_agent_did: str,
    task_type: str,
    payload: dict | None,
    reward: int,
) -> TaskResponse:
    """Publish a new open marketplace task."""
    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            creator_agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Creator agent not found: {creator_agent_did}")

        row = await conn.fetchrow(
            """
            INSERT INTO tasks (
                task_id,
                creator_agent_id,
                requester_agent_id,
                requester_agent_did,
                task_type,
                payload,
                reward,
                status
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $1,
                $2,
                $3,
                $4::jsonb,
                $5,
                'open'
            )
            RETURNING
                task_id,
                creator_agent_id,
                task_type,
                payload,
                reward,
                status,
                created_at
            """,
            agent_row["agent_id"],
            creator_agent_did,
            task_type,
            json.dumps(payload or {}),
            reward,
        )

    task = _row_to_task(dict(row))

    # Phase 7: Publish alongside existing direct calls (backward compatible)
    await publish_event(
        EventType.TASK_CREATED,
        {"task_id": str(task.task_id), "task_type": task_type, "reward": reward},
        creator_agent_did,
    )

    # Phase 8: Escrow task reward from creator's wallet (soft-fail)
    escrowed_amount = 0
    if reward > 0:
        try:
            from .token_service import escrow_task_reward
            await escrow_task_reward(agent_row["agent_id"], task.task_id, reward)
            escrowed_amount = reward
        except Exception as exc:
            logger.warning(
                "Token escrow skipped for task %s: %s", task.task_id, exc
            )

    # Phase 8.5: Collect platform fee from escrow (soft-fail)
    fee_collected = 0
    if escrowed_amount > 0:
        try:
            from .economy_service import collect_task_fee
            fee_collected = await collect_task_fee(task.task_id, escrowed_amount)
        except Exception as exc:
            logger.warning(
                "Task fee collection skipped for task %s: %s", task.task_id, exc
            )

    # Phase 8.5: Publish TASK_ESCROWED (fire-and-forget, never breaks caller)
    await publish_event(
        EventType.TASK_ESCROWED,
        {
            "task_id": str(task.task_id),
            "escrowed": escrowed_amount,
            "fee": fee_collected,
        },
        creator_agent_did,
    )

    return task


async def list_tasks(status: str = "open", limit: int = 50) -> list[TaskResponse]:
    """Return marketplace tasks filtered by status."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                task_id,
                creator_agent_id,
                task_type,
                payload,
                reward,
                status,
                created_at
            FROM tasks
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            status,
            limit,
        )

    return [_row_to_task(dict(row)) for row in rows]


async def submit_bid(
    task_id: UUID,
    agent_did: str,
    confidence: float,
    bid_price: int,
) -> TaskBidResponse:
    """Record an agent's bid on an open task.

    Auto-accept: if confidence >= 0.3 and the task is still open, the bid
    is immediately accepted and the task assigned to this agent.  First
    qualified bid wins — subsequent bids for the same task will fail with
    "Task is not open for bidding".
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            "SELECT task_id, status FROM tasks WHERE task_id = $1",
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")
        if task_row["status"] != "open":
            raise ValueError(
                f"Task is not open for bidding (status={task_row['status']})"
            )

        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Bidding agent not found: {agent_did}")

        row = await conn.fetchrow(
            """
            INSERT INTO task_bids (bid_id, task_id, agent_id, confidence, bid_price)
            VALUES (gen_random_uuid(), $1, $2, $3, $4)
            RETURNING bid_id, task_id, agent_id, confidence, bid_price, created_at
            """,
            task_id,
            agent_row["agent_id"],
            confidence,
            bid_price,
        )

    bid = _row_to_bid(dict(row))

    # Auto-accept: first qualified bid wins the task immediately.
    if confidence >= 0.3:
        try:
            await assign_task(task_id, row["bid_id"])
            logger.info(
                "Auto-assigned task %s to %s (confidence=%.2f)",
                task_id, agent_did, confidence,
            )
        except ValueError:
            # Task was already assigned by another bid — that's fine.
            logger.info(
                "Bid recorded but task %s already assigned (agent=%s)",
                task_id, agent_did,
            )

    return bid


async def list_bids(task_id: UUID) -> list[TaskBidResponse]:
    """Return all bids for a marketplace task, highest confidence first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT bid_id, task_id, agent_id, confidence, bid_price, created_at
            FROM task_bids
            WHERE task_id = $1
            ORDER BY confidence DESC, created_at ASC
            """,
            task_id,
        )
    return [_row_to_bid(dict(r)) for r in rows]


async def assign_task(task_id: UUID, bid_id: UUID) -> TaskAssignmentResponse:
    """
    Creator accepts a bid: creates task_assignment, updates task to 'assigned',
    sets executor fields, and enqueues the task_id for worker execution.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            "SELECT task_id, status FROM tasks WHERE task_id = $1",
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")
        if task_row["status"] != "open":
            raise ValueError(
                f"Task cannot be assigned (status={task_row['status']})"
            )

        bid_row = await conn.fetchrow(
            """
            SELECT tb.bid_id, tb.agent_id, a.agent_did
            FROM task_bids tb
            JOIN agents a ON a.agent_id = tb.agent_id
            WHERE tb.bid_id = $1 AND tb.task_id = $2
            """,
            bid_id,
            task_id,
        )
        if bid_row is None:
            raise ValueError(f"Bid not found for task: bid_id={bid_id}")

        assignment_row = await conn.fetchrow(
            """
            INSERT INTO task_assignments (
                assignment_id,
                task_id,
                agent_id,
                status,
                started_at
            )
            VALUES (gen_random_uuid(), $1, $2, 'assigned', CURRENT_TIMESTAMP)
            RETURNING
                assignment_id, task_id, agent_id, status, started_at, completed_at
            """,
            task_id,
            bid_row["agent_id"],
        )

        # Update task: set executor and move to 'assigned'
        await conn.execute(
            """
            UPDATE tasks
            SET
                status              = 'assigned',
                executor_agent_id   = $2,
                executor_agent_did  = $3,
                updated_at          = CURRENT_TIMESTAMP
            WHERE task_id = $1
            """,
            task_id,
            bid_row["agent_id"],
            bid_row["agent_did"],
        )

    # Enqueue task for worker execution (plain UUID string — backward compatible)
    await enqueue_task(str(task_id))

    # Phase 7: Publish TASK_ASSIGNED event alongside existing direct calls
    await publish_event(
        EventType.TASK_ASSIGNED,
        {"task_id": str(task_id), "executor_did": bid_row["agent_did"]},
    )

    return _row_to_assignment(dict(assignment_row))


async def submit_result(
    task_id: UUID,
    agent_did: str,
    result_payload: dict,
) -> TaskResultResponse:
    """
    Executor submits task result:
      - inserts task_results row
      - marks task_assignments completed
      - records trust event for task_completed
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            "SELECT task_id, status FROM tasks WHERE task_id = $1",
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Agent not found: {agent_did}")

        result_row = await conn.fetchrow(
            """
            INSERT INTO task_results (
                result_id, task_id, agent_id, result_payload, verification_status
            )
            VALUES (gen_random_uuid(), $1, $2, $3::jsonb, 'pending')
            RETURNING
                result_id, task_id, agent_id,
                result_payload, verification_status, created_at
            """,
            task_id,
            agent_row["agent_id"],
            json.dumps(result_payload),
        )

        # Mark assignment completed if one exists
        await conn.execute(
            """
            UPDATE task_assignments
            SET
                status       = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE task_id = $1 AND agent_id = $2
            """,
            task_id,
            agent_row["agent_id"],
        )

        # Update task status to COMPLETED
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = $1
            """,
            task_id,
        )

    # Record reputation event outside the transaction to avoid nested locks
    # (existing direct-call path — preserved for backward compatibility)
    await record_event(
        agent_did,
        "task_completed",
        {"task_id": str(task_id)},
    )

    # Phase 7: Publish TASK_COMPLETED event alongside existing direct calls
    await publish_event(
        EventType.TASK_COMPLETED,
        {"task_id": str(task_id)},
        agent_did,
    )

    # Phase 8: Release escrowed reward to executor's wallet (soft-fail)
    try:
        from .token_service import release_task_escrow
        await release_task_escrow(task_id, agent_row["agent_id"])
    except Exception as exc:
        logger.warning(
            "Token escrow release skipped for task %s: %s", task_id, exc
        )

    # Phase 8.5: Publish TASK_REWARD_RELEASED (fire-and-forget)
    await publish_event(
        EventType.TASK_REWARD_RELEASED,
        {"task_id": str(task_id)},
        agent_did,
    )

    return _row_to_result(dict(result_row))


async def fail_task(task_id: UUID, reason: str = "") -> TaskResponse:
    """
    Phase 8.5 — Mark a task as failed:
      1. Updates task status to 'failed'.
      2. Publishes TASK_FAILED event.
      3. Refunds escrowed reward to the creator (soft-fail).
      4. Publishes STAKE_SLASHED event if executor stake was slashed (soft-fail).

    Raises:
        ValueError: if task not found.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, creator_agent_id, task_type, payload,
                   reward, status, created_at, escrowed_reward
            FROM   tasks
            WHERE  task_id = $1
            """,
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        updated = await conn.fetchrow(
            """
            UPDATE tasks
               SET status     = 'failed',
                   updated_at = CURRENT_TIMESTAMP
             WHERE task_id = $1
            RETURNING
                task_id, creator_agent_id, task_type, payload,
                reward, status, created_at
            """,
            task_id,
        )

    task = _row_to_task(dict(updated))

    # Publish TASK_FAILED (existing event type — reputation handler picks it up)
    await publish_event(
        EventType.TASK_FAILED,
        {"task_id": str(task_id), "reason": reason},
    )

    # Refund escrow to creator (soft-fail)
    if task_row["escrowed_reward"]:
        try:
            from .token_service import refund_task_escrow
            await refund_task_escrow(task_id, task_row["creator_agent_id"])
        except Exception as exc:
            logger.warning(
                "Escrow refund skipped for failed task %s: %s", task_id, exc
            )

    return task


async def suggest_agents_for_task(
    task_id: UUID,
    required_capabilities: list[str],
    limit: int = 5,
    min_trust_score: float = 0.0,
) -> list[EligibleAgentResponse]:
    """
    Phase 5 — Capability Graph Integration.

    Given a marketplace task's required capabilities, rank and return the
    best-suited agents using the capability router.

    This is the bridge between the Task Economy (Phase 4) and the Capability
    Graph (Phase 5): when a task has no assigned executor, callers can use
    this function to discover qualified agents and surface them to bidders.

    Args:
        task_id:               UUID of the task (validated to exist).
        required_capabilities: capability_ids the task demands.
        limit:                 Maximum agents to return.
        min_trust_score:       Filter out agents below this threshold.

    Returns:
        Ranked list of EligibleAgentResponse (highest composite score first).

    Raises:
        ValueError: if the task_id does not exist.
    """
    # Validate task exists
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM tasks WHERE task_id = $1",
            task_id,
        )
    if not exists:
        raise ValueError(f"Task not found: {task_id}")

    # Delegate to capability_router for agent ranking
    from .capability_router import find_best_agents
    return await find_best_agents(
        required_capabilities=required_capabilities,
        limit=limit,
        min_trust_score=min_trust_score,
    )
