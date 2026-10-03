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
  submit_result()           — executor submits task result (held for review)
  approve_result()          — creator approves the result; the reward is paid
  reject_result()           — creator sends the result back to the executor
  release_overdue_result()  — pays a result the creator left unanswered
  list_results()            — the task's results, for its creator and executor
  cancel_task()             — creator withdraws a task nobody took (refund)
  suggest_agents_for_task() — rank agents by capability fit (Phase 5)

All DB access uses asyncpg via get_db() / transaction() context managers.
Redis queue is used to dispatch accepted tasks to the worker.

Who may do what (Sprint 9, S9-6a) — the *_did arguments are the authenticated
caller, resolved by the router from the JWT, never from the request body:
  submit_bid()    — any agent except the task's creator
  assign_task()   — the task's creator only
  submit_result() — the assigned executor only; the task must be 'assigned'.
                    It moves to 'in_review' and NOTHING is paid.
  approve_result() / reject_result() — the task's creator only; the task must
                    be 'in_review'.
  release_overdue_result() — no caller identity: for the scheduled job only
                    (no route calls it); the database clock decides.
  list_results()  — the task's creator or executor only.
  cancel_task()   — the task's creator only, 'open' tasks only, refunded once.
Errors: PermissionError → 403, TaskConflictError → 409, InsufficientFundsError
→ 400, other ValueError → 404 / 422 (see routers/tasks.py).

Money (Sprint 9, S9-7b): a reward is always funded. create_task() inserts the
task, escrows the reward from the creator's wallet and takes the platform fee
in ONE transaction; a wallet that cannot cover a non-zero reward means no task
(it used to be created anyway, advertising a reward nobody would be paid).
cancel_task() gives the escrow and the fee back in the transaction that marks
the task 'cancelled'.

Creator approval (Sprint 12, S12-2, decision D2c): the escrow leaves in exactly
one place, _pay_reviewed_result(), reached only from approve_result() (the
creator) and release_overdue_result() (AUTO_RELEASE_DAYS after submission with
the creator silent). Both hold the task's row lock, require 'in_review' and
move the task to 'COMPLETED' in the transaction that pays, so a reward is paid
once however approvals, rejections and the automatic release race. A rejection
moves no token: the reward stays in escrow and the same executor may submit
again (a creator cannot get the reward back by rejecting).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
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
from ..services.reputation import record_task_completed  # noqa: E402
from .auto_release import AUTO_RELEASE_DAYS  # noqa: E402
from .token_service import InsufficientFundsError  # noqa: E402,F401  (re-exported for the router)

REVIEW_NOTE_MAX_CHARS = 1000


class TaskConflictError(ValueError):
    """The task is not in a state that allows the requested action (HTTP 409)."""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _row_to_task(row) -> TaskResponse:
    # submitted_at only means something while the result is under review.
    submitted_at = row.get("submitted_at") if row["status"] == "in_review" else None
    return TaskResponse(
        task_id=row["task_id"],
        creator_agent_id=row["creator_agent_id"],
        task_type=row["task_type"],
        payload=_decode_json(row.get("payload")),
        reward=row["reward"],
        status=row["status"],
        created_at=row["created_at"],
        executor_agent_id=row.get("executor_agent_id"),
        submitted_at=submitted_at,
        auto_release_at=(
            submitted_at + timedelta(days=AUTO_RELEASE_DAYS) if submitted_at else None
        ),
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


def _row_to_result(row, reward_released: int | None = None) -> TaskResultResponse:
    return TaskResultResponse(
        result_id=row["result_id"],
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        result_payload=_decode_json(row.get("result_payload")),
        verification_status=row["verification_status"],
        created_at=row["created_at"],
        review_note=row.get("review_note"),
        reward_released=reward_released,
    )


# ── Service Functions ──────────────────────────────────────────────────────────

async def create_task(
    creator_agent_did: str,
    task_type: str,
    payload: dict | None,
    reward: int,
) -> TaskResponse:
    """
    Publish a new open marketplace task.

    The task row, the escrow of *reward* from the creator's wallet and the
    platform fee are ONE transaction: if the wallet cannot cover a non-zero
    reward, nothing is created and no token moves.

    Raises:
        ValueError: creator agent not found.
        InsufficientFundsError: reward > 0 and the creator has no wallet, or
            the wallet does not hold the reward.
    """
    escrowed_amount = 0
    fee_collected = 0

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

        if reward > 0:
            # Phase 8: escrow the reward from the creator's wallet. Raises on
            # a missing or short wallet → the INSERT above rolls back too.
            from .token_service import escrow_task_reward
            await escrow_task_reward(
                agent_row["agent_id"], row["task_id"], reward, conn=conn
            )
            escrowed_amount = reward

            # Phase 8.5: platform fee, out of the escrow, same transaction.
            from .economy_service import collect_task_fee
            fee_collected = await collect_task_fee(
                row["task_id"], escrowed_amount, conn=conn
            )

    task = _row_to_task(dict(row))

    # Phase 7: Publish alongside existing direct calls (backward compatible)
    await publish_event(
        EventType.TASK_CREATED,
        {"task_id": str(task.task_id), "task_type": task_type, "reward": reward},
        creator_agent_did,
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
                created_at,
                executor_agent_id,
                submitted_at
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

    Raises:
        PermissionError: the bidder is the task's creator (no self-dealing:
            a creator could otherwise win and "complete" their own task).
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            "SELECT task_id, status, creator_agent_id FROM tasks WHERE task_id = $1",
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
        if agent_row["agent_id"] == task_row["creator_agent_id"]:
            raise PermissionError("The task creator cannot bid on their own task")

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
            await _assign_bid(task_id, row["bid_id"], creator_did=None)
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


async def assign_task(
    task_id: UUID,
    bid_id: UUID,
    caller_did: str,
) -> TaskAssignmentResponse:
    """
    Creator accepts a bid: creates task_assignment, updates task to 'assigned',
    sets executor fields, and enqueues the task_id for worker execution.

    Raises:
        PermissionError: *caller_did* is not the task's creator.
        ValueError: task or bid not found, or the task is no longer open.
    """
    return await _assign_bid(task_id, bid_id, creator_did=caller_did)


async def _assign_bid(
    task_id: UUID,
    bid_id: UUID,
    *,
    creator_did: str | None,
) -> TaskAssignmentResponse:
    """
    Assign the task to the bid's agent.

    *creator_did* is the agent accepting the bid and must be the task's
    creator. None is reserved for the platform's own auto-accept rule in
    submit_bid() — never pass None for a caller-initiated accept.

    The task row is locked so two concurrent accepts (or auto-accepts) cannot
    both see 'open' and assign the task twice.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, status, creator_agent_id
            FROM tasks WHERE task_id = $1
            FOR UPDATE
            """,
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")
        if creator_did is not None:
            caller_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                creator_did,
            )
            if caller_id is None or caller_id != task_row["creator_agent_id"]:
                raise PermissionError("Only the task creator can accept a bid")
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
    Executor submits a task result for the creator's review. In ONE
    transaction:
      - locks the task row
      - checks the caller is the assigned executor and the task is 'assigned'
      - inserts the task_results row ('pending')
      - moves the task to 'in_review' and stamps submitted_at (database clock)

    NOTHING is paid here (S12-2): the reward stays in escrow until the creator
    approves (approve_result) or AUTO_RELEASE_DAYS pass with the creator
    silent (release_overdue_result). A second submit while the first is under
    review is refused; after a rejection the executor may submit again.

    Raises:
        ValueError: task or agent not found.
        PermissionError: *agent_did* is not the task's assigned executor.
        TaskConflictError: the task is not awaiting a result (under review,
            completed, or not a marketplace task).
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, status, executor_agent_id
            FROM tasks WHERE task_id = $1
            FOR UPDATE
            """,
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

        if task_row["executor_agent_id"] != agent_row["agent_id"]:
            raise PermissionError("Only the assigned executor can submit a result")
        if task_row["status"] != "assigned":
            raise TaskConflictError(
                f"Task is not awaiting a result (status={task_row['status']})"
            )

        result_row = await conn.fetchrow(
            """
            INSERT INTO task_results (
                result_id, task_id, agent_id, result_payload, verification_status
            )
            VALUES (gen_random_uuid(), $1, $2, $3::jsonb, 'pending')
            RETURNING
                result_id, task_id, agent_id,
                result_payload, verification_status, created_at, review_note
            """,
            task_id,
            agent_row["agent_id"],
            json.dumps(result_payload),
        )

        await conn.execute(
            """
            UPDATE tasks
            SET status       = 'in_review',
                submitted_at = CURRENT_TIMESTAMP,
                updated_at   = CURRENT_TIMESTAMP
            WHERE task_id = $1
            """,
            task_id,
        )

    return _row_to_result(dict(result_row), reward_released=0)


async def _lock_task_for_review(conn, task_id: UUID, caller_did: str, action: str):
    """Lock the task and check that *caller_did* is its creator and that a
    result is under review. Returns the locked task row."""
    task_row = await conn.fetchrow(
        """
        SELECT task_id, status, creator_agent_id, executor_agent_id, executor_agent_did
        FROM tasks WHERE task_id = $1
        FOR UPDATE
        """,
        task_id,
    )
    if task_row is None:
        raise ValueError(f"Task not found: {task_id}")

    caller_id = await conn.fetchval(
        "SELECT agent_id FROM agents WHERE agent_did = $1",
        caller_did,
    )
    # A direct task has no marketplace creator (NULL), so nobody passes this.
    if caller_id is None or caller_id != task_row["creator_agent_id"]:
        raise PermissionError(f"Only the task creator can {action} a result")
    if task_row["status"] != "in_review":
        raise TaskConflictError(
            f"Task has no result under review (status={task_row['status']})"
        )
    return task_row


async def _pay_reviewed_result(conn, task_row) -> tuple[dict, int]:
    """
    THE place a task reward leaves escrow for the executor. The caller holds
    the task's row lock and has checked status == 'in_review'.

    In the caller's transaction: marks the result under review 'verified',
    completes the assignment, moves the task to 'COMPLETED' and releases the
    escrow to the task's executor (read from the locked row, never from a
    caller). Returns (result row, amount released).
    """
    task_id = task_row["task_id"]
    executor_id = task_row["executor_agent_id"]
    if executor_id is None:
        raise TaskConflictError("Task has no executor to pay")

    result_row = await conn.fetchrow(
        """
        UPDATE task_results
           SET verification_status = 'verified'
         WHERE result_id = (
                SELECT result_id FROM task_results
                 WHERE task_id = $1 AND agent_id = $2
                   AND verification_status = 'pending'
                 ORDER BY created_at DESC, result_id
                 LIMIT 1
               )
        RETURNING
            result_id, task_id, agent_id,
            result_payload, verification_status, created_at, review_note
        """,
        task_id,
        executor_id,
    )
    if result_row is None:
        # 'in_review' without a pending result from the executor: pay nothing.
        raise TaskConflictError("Task has no pending result to pay for")

    await conn.execute(
        """
        UPDATE task_assignments
        SET
            status       = 'completed',
            completed_at = CURRENT_TIMESTAMP
        WHERE task_id = $1 AND agent_id = $2
        """,
        task_id,
        executor_id,
    )

    updated = await conn.fetchval(
        """
        UPDATE tasks
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE task_id = $1 AND status = 'in_review'
        RETURNING task_id
        """,
        task_id,
    )
    if updated is None:
        raise TaskConflictError("Task has no result under review")

    # Same transaction, so "completed" and "paid" cannot come apart.
    from .token_service import release_task_escrow
    released = await release_task_escrow(task_id, executor_id, conn=conn)
    return dict(result_row), released


async def _after_payment(task_id: UUID, executor_did: str | None, released: int, source: str) -> None:
    """Trust event and bus events for a task that was just paid (outside the
    transaction, as before S12-2)."""
    # S9-9b: counted once per task, and only if the escrow paid a reward.
    await record_task_completed(task_id)

    await publish_event(
        EventType.TASK_COMPLETED,
        {"task_id": str(task_id), "released_by": source},
        executor_did,
    )
    await publish_event(
        EventType.TASK_REWARD_RELEASED,
        {"task_id": str(task_id), "released": released, "released_by": source},
        executor_did,
    )


async def approve_result(task_id: UUID, caller_did: str) -> TaskResultResponse:
    """
    Creator approves the result under review; the escrowed reward is paid to
    the executor and the task becomes 'COMPLETED' — one locked transaction,
    so it happens once however many approvals (or an approval and the
    automatic release) race.

    Raises:
        ValueError: task not found.
        PermissionError: *caller_did* is not the task's creator.
        TaskConflictError: the task has no result under review.
    """
    async with transaction() as conn:
        task_row = await _lock_task_for_review(conn, task_id, caller_did, "approve")
        result_row, released = await _pay_reviewed_result(conn, task_row)

    await _after_payment(task_id, task_row["executor_agent_did"], released, "creator")
    return _row_to_result(result_row, reward_released=released)


async def reject_result(
    task_id: UUID,
    caller_did: str,
    note: str | None = None,
) -> TaskResultResponse:
    """
    Creator rejects the result under review. The result is marked 'rejected'
    (with *note*, the reason shown to the executor) and the task goes back to
    'assigned': the same executor may submit again, and the automatic-release
    period starts afresh with that new submission.

    No token moves: the reward stays in escrow, so rejecting never returns it
    to the creator.

    Raises:
        ValueError: task not found.
        PermissionError: *caller_did* is not the task's creator.
        TaskConflictError: the task has no result under review.
    """
    note = (note or "").strip()[:REVIEW_NOTE_MAX_CHARS] or None
    async with transaction() as conn:
        task_row = await _lock_task_for_review(conn, task_id, caller_did, "reject")

        result_row = await conn.fetchrow(
            """
            UPDATE task_results
               SET verification_status = 'rejected',
                   review_note         = $3
             WHERE result_id = (
                    SELECT result_id FROM task_results
                     WHERE task_id = $1 AND agent_id = $2
                       AND verification_status = 'pending'
                     ORDER BY created_at DESC, result_id
                     LIMIT 1
                   )
            RETURNING
                result_id, task_id, agent_id,
                result_payload, verification_status, created_at, review_note
            """,
            task_id,
            task_row["executor_agent_id"],
            note,
        )
        if result_row is None:
            raise TaskConflictError("Task has no pending result to reject")

        await conn.execute(
            """
            UPDATE tasks
            SET status       = 'assigned',
                submitted_at = NULL,
                updated_at   = CURRENT_TIMESTAMP
            WHERE task_id = $1 AND status = 'in_review'
            """,
            task_id,
        )

    return _row_to_result(dict(result_row), reward_released=0)


async def release_overdue_result(task_id: UUID) -> int:
    """
    Pay a result the creator has left unanswered for AUTO_RELEASE_DAYS, so a
    silent creator cannot withhold the reward (decision D2c). Returns the
    amount released.

    For the scheduled job only — no route calls this and it takes no caller
    and no time: with the task row locked, the DATABASE clock is compared
    with the submitted_at the database stamped. A task not under review, not
    yet due, or with no submission time is refused and nothing moves.

    Raises:
        ValueError: task not found.
        TaskConflictError: nothing under review, or the period has not passed.
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, status, creator_agent_id, executor_agent_id, executor_agent_did,
                   COALESCE(
                       submitted_at <= CURRENT_TIMESTAMP - make_interval(days => $2),
                       FALSE
                   ) AS due
            FROM tasks WHERE task_id = $1
            FOR UPDATE
            """,
            task_id,
            AUTO_RELEASE_DAYS,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")
        if task_row["status"] != "in_review":
            raise TaskConflictError(
                f"Task has no result under review (status={task_row['status']})"
            )
        if not task_row["due"]:
            raise TaskConflictError(
                f"The creator still has time to answer ({AUTO_RELEASE_DAYS} days from submission)"
            )
        _, released = await _pay_reviewed_result(conn, task_row)

    logger.info(
        "task_service: task %s released automatically after %d days (%d tokens)",
        task_id, AUTO_RELEASE_DAYS, released,
    )
    await _after_payment(task_id, task_row["executor_agent_did"], released, "auto_release")
    return released


async def list_results(task_id: UUID, caller_did: str) -> list[TaskResultResponse]:
    """The results submitted for a task, newest first — for its creator (who
    has to judge them) and its executor only.

    Raises:
        ValueError: task not found.
        PermissionError: *caller_did* is neither the creator nor the executor.
    """
    async with get_db() as conn:
        task_row = await conn.fetchrow(
            "SELECT creator_agent_id, executor_agent_id FROM tasks WHERE task_id = $1",
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")
        caller_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if caller_id is None or caller_id not in (
            task_row["creator_agent_id"], task_row["executor_agent_id"],
        ):
            raise PermissionError("Only the task's creator or executor can read its results")
        rows = await conn.fetch(
            """
            SELECT result_id, task_id, agent_id,
                   result_payload, verification_status, created_at, review_note
            FROM task_results
            WHERE task_id = $1
            ORDER BY created_at DESC, result_id
            """,
            task_id,
        )
    return [_row_to_result(dict(r)) for r in rows]


async def cancel_task(task_id: UUID, caller_did: str) -> TaskResponse:
    """
    Creator withdraws a marketplace task that nobody has taken.

    In ONE transaction, with the task row locked: marks the task 'cancelled',
    refunds the escrowed reward to the creator and gives the platform fee
    back (the task never ran, so the platform keeps nothing). Only an 'open'
    task can be cancelled: once an executor is assigned, the escrow is theirs
    to earn and the creator cannot pull it back.

    Because the status check, the status change and the refunds share one
    locked transaction, a task is refunded once however many cancels race —
    and a cancel racing a bid either wins (the bid finds the task closed) or
    loses (409, the task is assigned).

    Raises:
        ValueError: task not found.
        PermissionError: *caller_did* is not the task's creator (a direct
            task has no marketplace creator, so nobody can cancel it here).
        TaskConflictError: the task is not 'open' (assigned, finished or
            already cancelled).
    """
    async with transaction() as conn:
        task_row = await conn.fetchrow(
            """
            SELECT task_id, status, creator_agent_id
            FROM tasks WHERE task_id = $1
            FOR UPDATE
            """,
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        caller_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if caller_id is None or caller_id != task_row["creator_agent_id"]:
            raise PermissionError("Only the task creator can cancel it")
        if task_row["status"] != "open":
            raise TaskConflictError(
                f"Only an open task can be cancelled (status={task_row['status']})"
            )

        from .economy_service import refund_task_fee
        from .token_service import refund_task_escrow
        refunded = await refund_task_escrow(task_id, caller_id, conn=conn)
        fee_refunded = await refund_task_fee(conn, task_id, caller_id)

        updated = await conn.fetchrow(
            """
            UPDATE tasks
               SET status     = 'cancelled',
                   updated_at = CURRENT_TIMESTAMP
             WHERE task_id = $1
               AND status  = 'open'
            RETURNING
                task_id, creator_agent_id, task_type, payload,
                reward, status, created_at
            """,
            task_id,
        )

    logger.info(
        "task_service: task %s cancelled by %s (refunded %d + fee %d)",
        task_id, caller_did, refunded, fee_refunded,
    )
    return _row_to_task(dict(updated))


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
