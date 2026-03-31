"""
AgentX Platform — Task Marketplace Service
═══════════════════════════════════════════
Phase 4: Agent Task Economy
Phase 5: Capability Graph Integration

Business logic for the open marketplace:
  create_task()             — publish an open task
  list_tasks()              — discover available tasks
  submit_bid()              — agent bids on a task
  list_bids()               — ranked bid list by composite score
  assign_task()             — creator accepts a bid
  submit_result()           — executor submits task result
  expire_stale_bids()       — flag tasks with no recent bid activity
  suggest_agents_for_task() — rank agents by capability fit (Phase 5)

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
from ..models.capability import EligibleAgentResponse
from ..services.reputation import record_event
from ..services import token_service


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
        feedback=row.get("feedback"),
        verified_by_did=row.get("verified_by_did"),
        verified_at=row.get("verified_at"),
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
    sets executor fields, escrows the reward, and enqueues the task for workers.

    Raises ValueError if the creator cannot afford the task reward.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            "SELECT task_id, status, reward, requester_agent_did FROM tasks WHERE task_id = $1",
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

    # Escrow the task reward from the creator's balance.
    # This runs in its own transaction so the assignment above is committed
    # even if escrow fails (callers catch ValueError for insufficient funds).
    reward = int(task_row["reward"])
    creator_did = task_row["requester_agent_did"]
    if reward > 0 and creator_did:
        await token_service.escrow_hold(
            task_id=task_id,
            from_did=creator_did,
            token_type="WORK",
            amount=reward,
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


async def verify_result(
    task_id: UUID,
    creator_did: str,
    verdict: str,
    feedback: str | None = None,
) -> TaskResultResponse:
    """
    Task creator verifies the submitted result.
    verdict must be 'approved' or 'rejected'.
    Only the original task creator may call this.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, requester_agent_did, creator_agent_id
            FROM tasks
            WHERE task_id = $1
            """,
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        # Resolve creator DID: marketplace tasks store creator in creator_agent_id,
        # direct tasks store it in requester_agent_did.
        actual_creator_did = task_row.get("requester_agent_did")
        if actual_creator_did is None:
            # Fallback: look up DID from creator_agent_id
            creator_agent_id = task_row.get("creator_agent_id")
            if creator_agent_id is not None:
                did_row = await conn.fetchrow(
                    "SELECT agent_did FROM agents WHERE agent_id = $1",
                    creator_agent_id,
                )
                if did_row:
                    actual_creator_did = did_row["agent_did"]

        if actual_creator_did != creator_did:
            raise PermissionError("Only the task creator can verify results")

        result_row = await conn.fetchrow(
            """
            SELECT result_id, task_id, agent_id,
                   result_payload, verification_status, feedback,
                   verified_by_did, verified_at, created_at
            FROM task_results
            WHERE task_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            task_id,
        )
        if result_row is None:
            raise ValueError(f"No results found for task: {task_id}")

        if result_row["verification_status"] not in ("pending",):
            raise ValueError(
                f"Result already reviewed (status={result_row['verification_status']})"
            )

        new_status = "verified" if verdict == "approved" else "rejected"

        updated_row = await conn.fetchrow(
            """
            UPDATE task_results
            SET
                verification_status = $2,
                feedback            = $3,
                verified_by_did     = $4,
                verified_at         = CURRENT_TIMESTAMP
            WHERE result_id = $1
            RETURNING
                result_id, task_id, agent_id,
                result_payload, verification_status,
                feedback, verified_by_did, verified_at, created_at
            """,
            result_row["result_id"],
            new_status,
            feedback,
            creator_did,
        )

        # Look up executor DID for events
        executor_row = await conn.fetchrow(
            "SELECT agent_did FROM agents WHERE agent_id = $1",
            result_row["agent_id"],
        )
        executor_did = executor_row["agent_did"] if executor_row else None

    # Record reputation event outside transaction
    if executor_did:
        event_type = "task_success" if verdict == "approved" else "task_failed"
        await record_event(
            executor_did,
            event_type,
            {"task_id": str(task_id), "verdict": verdict},
        )

    # Settlement: release escrow on approval, refund on rejection
    try:
        if verdict == "approved" and executor_did:
            await token_service.escrow_release(task_id, executor_did)
        elif verdict == "rejected":
            await token_service.escrow_refund(task_id)
    except ValueError:
        # No escrow hold exists (e.g. zero-reward task) — that's fine
        pass

    return _row_to_result(dict(updated_row))


async def get_task_results(task_id: UUID) -> list[TaskResultResponse]:
    """Return all results submitted for a task, with verification info."""
    async with get_db() as conn:
        task_exists = await conn.fetchval(
            "SELECT 1 FROM tasks WHERE task_id = $1",
            task_id,
        )
        if not task_exists:
            raise ValueError(f"Task not found: {task_id}")

        rows = await conn.fetch(
            """
            SELECT
                result_id, task_id, agent_id,
                result_payload, verification_status,
                feedback, verified_by_did, verified_at, created_at
            FROM task_results
            WHERE task_id = $1
            ORDER BY created_at DESC
            """,
            task_id,
        )

    return [_row_to_result(dict(row)) for row in rows]


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


async def cancel_task(task_id: UUID, creator_did: str) -> dict:
    """
    Cancel an open or assigned task. Refunds escrowed tokens if any.
    Only the task creator may cancel.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, status, requester_agent_did
            FROM tasks
            WHERE task_id = $1
            """,
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        if task_row["requester_agent_did"] != creator_did:
            raise PermissionError("Only the task creator can cancel")

        if task_row["status"] not in ("open", "assigned"):
            raise ValueError(
                f"Task cannot be cancelled (status={task_row['status']})"
            )

        await conn.execute(
            """
            UPDATE tasks
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = $1
            """,
            task_id,
        )

        # Cancel any active assignments
        await conn.execute(
            """
            UPDATE task_assignments
            SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP
            WHERE task_id = $1 AND status = 'assigned'
            """,
            task_id,
        )

    # Refund escrowed funds
    try:
        await token_service.escrow_refund(task_id)
    except ValueError:
        pass  # No escrow hold — zero-reward task

    return {"task_id": str(task_id), "status": "cancelled"}


async def list_bids(
    task_id: UUID,
    limit: int = 50,
) -> list[dict]:
    """
    Return bids for a task ranked by composite score:
      50% capability match + 35% trust score + 15% REP balance

    Falls back to confidence * (1 - price_ratio) when trust/REP data
    is unavailable.
    """
    async with get_db() as conn:
        task_row = await conn.fetchval(
            "SELECT 1 FROM tasks WHERE task_id = $1", task_id
        )
        if not task_row:
            raise ValueError(f"Task not found: {task_id}")

        rows = await conn.fetch(
            """
            SELECT
                tb.bid_id,
                tb.task_id,
                tb.agent_id,
                tb.confidence,
                tb.bid_price,
                tb.created_at,
                a.agent_did,
                a.display_name,
                COALESCE(ts.overall_score, 0.5) AS trust_score,
                COALESCE(bal.balance, 0) AS rep_balance
            FROM task_bids tb
            JOIN agents a ON a.agent_id = tb.agent_id
            LEFT JOIN trust_scores ts ON ts.agent_did = a.agent_did
            LEFT JOIN token_balances bal
                ON bal.agent_did = a.agent_did AND bal.token_type = 'REP'
            WHERE tb.task_id = $1
            ORDER BY tb.created_at DESC
            LIMIT $2
            """,
            task_id,
            limit,
        )

    if not rows:
        return []

    # Normalize REP balances for scoring
    max_rep = max(float(r["rep_balance"]) for r in rows) or 1.0

    scored = []
    for row in rows:
        capability_score = float(row["confidence"])  # self-reported capability
        trust = float(row["trust_score"])
        rep_norm = float(row["rep_balance"]) / max_rep

        composite = (
            0.50 * capability_score
            + 0.35 * trust
            + 0.15 * rep_norm
        )

        scored.append({
            "bid_id": str(row["bid_id"]),
            "task_id": str(row["task_id"]),
            "agent_id": str(row["agent_id"]),
            "agent_did": row["agent_did"],
            "display_name": row["display_name"],
            "confidence": float(row["confidence"]),
            "bid_price": row["bid_price"],
            "trust_score": round(trust, 3),
            "rep_balance": row["rep_balance"],
            "composite_score": round(composite, 4),
            "created_at": row["created_at"].isoformat(),
        })

    scored.sort(key=lambda b: b["composite_score"], reverse=True)
    return scored
