"""
AgentX Platform — Task Marketplace Service
═══════════════════════════════════════════
Phase 4: Agent Task Economy

Business logic for the open marketplace:
  create_task()    — publish an open task
  list_tasks()     — discover available tasks
  submit_bid()     — agent bids on a task
  assign_task()    — creator accepts a bid
  submit_result()  — executor submits task result

All DB access uses asyncpg via get_db() / transaction() context managers.
Redis queue is used to dispatch accepted tasks to the worker.
"""
from __future__ import annotations

import json
from uuid import UUID

from ..cache import enqueue_task
from ..database import get_db, transaction
from ..models.task import (
    TaskAssignmentResponse,
    TaskBidResponse,
    TaskResponse,
    TaskResultResponse,
)
from ..services.reputation import record_event


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

    return _row_to_task(dict(row))


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
    """Record an agent's bid on an open task."""
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

    return _row_to_bid(dict(row))


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
    await record_event(
        agent_did,
        "task_completed",
        {"task_id": str(task_id)},
    )

    return _row_to_result(dict(result_row))
