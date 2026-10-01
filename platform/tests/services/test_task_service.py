"""
Tests: src/services/task_service.py
Phase 4 — Agent Task Economy

Covers:
  - create_task()    persists row, returns TaskResponse
  - list_tasks()     filters by status
  - submit_bid()     validates task/agent, inserts bid
  - assign_task()    creates assignment, updates task, enqueues
  - submit_result()  inserts result, marks assignment done, records trust

Sprint 9 (S9-6a) ownership rules, mocked here and proven against real Postgres
in tests/integration/test_task_escrow_db.py:
  - submit_bid()     refuses the task's creator
  - assign_task()    creator only
  - submit_result()  assigned executor only, task must be 'assigned'
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import task_service


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _task_row(task_id=None, creator_id=None, status="open", reward=100):
    return {
        "task_id":          task_id or uuid4(),
        "creator_agent_id": creator_id or uuid4(),
        "task_type":        "marketplace.test",
        "payload":          "{}",
        "reward":           reward,
        "status":           status,
        "created_at":       _now(),
    }


def _bid_row(bid_id=None, task_id=None, agent_id=None):
    return {
        "bid_id":     bid_id or uuid4(),
        "task_id":    task_id or uuid4(),
        "agent_id":   agent_id or uuid4(),
        "confidence": 0.9,
        "bid_price":  50,
        "created_at": _now(),
    }


def _assignment_row(assignment_id=None, task_id=None, agent_id=None):
    return {
        "assignment_id": assignment_id or uuid4(),
        "task_id":       task_id or uuid4(),
        "agent_id":      agent_id or uuid4(),
        "status":        "assigned",
        "started_at":    _now(),
        "completed_at":  None,
    }


def _result_row(result_id=None, task_id=None, agent_id=None):
    return {
        "result_id":           result_id or uuid4(),
        "task_id":             task_id or uuid4(),
        "agent_id":            agent_id or uuid4(),
        "result_payload":      '{"score": 99}',
        "verification_status": "pending",
        "created_at":          _now(),
    }


# ── create_task ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_returns_task_response():
    creator_id = uuid4()
    row = _task_row(creator_id=creator_id)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"agent_id": creator_id},  # agent lookup
        row,                        # insert RETURNING
    ])

    with patch("src.services.task_service.transaction", return_value=_tx_context(conn)):
        result = await task_service.create_task(
            creator_agent_did="did:agentx:atlas-001",
            task_type="marketplace.test",
            payload={"key": "value"},
            reward=100,
        )

    assert result.task_type == "marketplace.test"
    assert result.reward == 100
    assert result.status == "open"
    assert conn.fetchrow.await_count == 2


@pytest.mark.asyncio
async def test_create_task_raises_if_agent_not_found():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Creator agent not found"),
    ):
        await task_service.create_task(
            creator_agent_did="did:agentx:ghost-001",
            task_type="x",
            payload=None,
            reward=0,
        )


# ── list_tasks ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_returns_matching_rows():
    rows = [_task_row(), _task_row()]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    with patch("src.services.task_service.get_db", return_value=_tx_context(conn)):
        results = await task_service.list_tasks(status="open", limit=10)

    assert len(results) == 2
    conn.fetch.assert_awaited_once()
    call_args = conn.fetch.await_args.args
    assert "open" in call_args


@pytest.mark.asyncio
async def test_list_tasks_empty():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    with patch("src.services.task_service.get_db", return_value=_tx_context(conn)):
        results = await task_service.list_tasks(status="open")

    assert results == []


# ── submit_bid ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_bid_inserts_bid_record():
    task_id = uuid4()
    agent_id = uuid4()
    bid = _bid_row(task_id=task_id, agent_id=agent_id)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "creator_agent_id": uuid4()},  # task lookup
        {"agent_id": agent_id},                   # agent lookup
        bid,                                       # insert RETURNING
    ])

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service._assign_bid", new=AsyncMock()) as mock_assign,
    ):
        result = await task_service.submit_bid(
            task_id=task_id,
            agent_did="did:agentx:bidder-001",
            confidence=0.9,
            bid_price=50,
        )

    assert result.confidence == 0.9
    assert result.bid_price == 50
    assert conn.fetchrow.await_count == 3
    # Auto-accept is the platform's own rule: no caller to check.
    mock_assign.assert_awaited_once_with(task_id, bid["bid_id"], creator_did=None)


@pytest.mark.asyncio
async def test_submit_bid_refuses_the_task_creator():
    """S9-6a: a creator cannot bid on (and so win) their own task."""
    task_id = uuid4()
    creator_id = uuid4()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "creator_agent_id": creator_id},
        {"agent_id": creator_id},  # the bidder IS the creator
    ])

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service._assign_bid", new=AsyncMock()) as mock_assign,
        pytest.raises(PermissionError, match="cannot bid on their own task"),
    ):
        await task_service.submit_bid(
            task_id=task_id,
            agent_did="did:agentx:creator-001",
            confidence=0.9,
            bid_price=50,
        )

    assert conn.fetchrow.await_count == 2  # no bid row inserted
    mock_assign.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_bid_rejects_non_open_task():
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"task_id": task_id, "status": "assigned"})

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="not open for bidding"),
    ):
        await task_service.submit_bid(
            task_id=task_id,
            agent_did="did:agentx:bidder-001",
            confidence=0.5,
            bid_price=10,
        )


@pytest.mark.asyncio
async def test_submit_bid_raises_if_task_not_found():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Task not found"),
    ):
        await task_service.submit_bid(
            task_id=uuid4(),
            agent_did="did:agentx:bidder-001",
            confidence=0.5,
            bid_price=10,
        )


# ── assign_task ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_task_creates_assignment_and_enqueues():
    task_id = uuid4()
    bid_id = uuid4()
    agent_id = uuid4()
    assignment = _assignment_row(task_id=task_id, agent_id=agent_id)

    creator_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "creator_agent_id": creator_id},  # task lookup
        {"bid_id": bid_id, "agent_id": agent_id, "agent_did": "did:agentx:exec-001"},  # bid lookup
        assignment,                                                        # insert assignment
    ])
    conn.fetchval = AsyncMock(return_value=creator_id)  # caller DID → agent_id
    conn.execute = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.enqueue_task", new=AsyncMock()) as mock_enqueue,
    ):
        result = await task_service.assign_task(
            task_id=task_id, bid_id=bid_id, caller_did="did:agentx:creator-001",
        )

    assert result.status == "assigned"
    mock_enqueue.assert_awaited_once_with(str(task_id))
    # tasks UPDATE called once
    conn.execute.assert_awaited_once()
    # The task row is locked before its status is read.
    assert "FOR UPDATE" in conn.fetchrow.await_args_list[0].args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_agent_id", [uuid4(), None])
async def test_assign_task_refuses_anyone_but_the_creator(caller_agent_id):
    """S9-6a: another agent (or a DID with no agent record) cannot accept a bid."""
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "creator_agent_id": uuid4()},
    ])
    conn.fetchval = AsyncMock(return_value=caller_agent_id)
    conn.execute = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.enqueue_task", new=AsyncMock()) as mock_enqueue,
        pytest.raises(PermissionError, match="Only the task creator"),
    ):
        await task_service.assign_task(
            task_id=task_id, bid_id=uuid4(), caller_did="did:agentx:intruder-001",
        )

    conn.execute.assert_not_awaited()
    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_assign_task_raises_if_task_not_open():
    task_id = uuid4()
    creator_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={"task_id": task_id, "status": "assigned", "creator_agent_id": creator_id}
    )
    conn.fetchval = AsyncMock(return_value=creator_id)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="cannot be assigned"),
    ):
        await task_service.assign_task(
            task_id=task_id, bid_id=uuid4(), caller_did="did:agentx:creator-001",
        )


@pytest.mark.asyncio
async def test_assign_task_raises_if_bid_not_found():
    task_id = uuid4()
    creator_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "creator_agent_id": creator_id},  # task lookup
        None,                                      # bid not found
    ])
    conn.fetchval = AsyncMock(return_value=creator_id)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Bid not found"),
    ):
        await task_service.assign_task(
            task_id=task_id, bid_id=uuid4(), caller_did="did:agentx:creator-001",
        )


# ── submit_result ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_result_inserts_result_and_records_trust():
    task_id = uuid4()
    agent_id = uuid4()
    result_row = _result_row(task_id=task_id, agent_id=agent_id)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "assigned", "executor_agent_id": agent_id},  # task lookup
        {"agent_id": agent_id},                       # agent lookup
        result_row,                                    # insert RETURNING
    ])
    conn.execute = AsyncMock()
    release = AsyncMock(return_value=100)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.record_event", new=AsyncMock()) as mock_trust,
        patch("src.services.token_service.release_task_escrow", new=release),
    ):
        result = await task_service.submit_result(
            task_id=task_id,
            agent_did="did:agentx:exec-001",
            result_payload={"score": 99},
        )

    assert result.verification_status == "pending"
    mock_trust.assert_awaited_once_with(
        "did:agentx:exec-001",
        "task_completed",
        {"task_id": str(task_id)},
    )
    # assignment + task UPDATE
    assert conn.execute.await_count == 2
    # The task row is locked, and the payout runs on the SAME connection
    # (same transaction) as the status change.
    assert "FOR UPDATE" in conn.fetchrow.await_args_list[0].args[0]
    release.assert_awaited_once_with(task_id, agent_id, conn=conn)


@pytest.mark.asyncio
async def test_submit_result_refuses_anyone_but_the_executor():
    """S9-6a: nobody else can complete the task or collect its reward."""
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "assigned", "executor_agent_id": uuid4()},
        {"agent_id": uuid4()},  # caller is a different agent
    ])
    conn.execute = AsyncMock()
    release = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.record_event", new=AsyncMock()) as mock_trust,
        patch("src.services.token_service.release_task_escrow", new=release),
        pytest.raises(PermissionError, match="Only the assigned executor"),
    ):
        await task_service.submit_result(
            task_id=task_id,
            agent_did="did:agentx:intruder-001",
            result_payload={"score": 99},
        )

    conn.execute.assert_not_awaited()
    release.assert_not_awaited()
    mock_trust.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_result_refuses_open_task_with_no_executor():
    """An open task has no executor yet: any result is refused (fail closed)."""
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open", "executor_agent_id": None},
        {"agent_id": uuid4()},
    ])
    release = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.token_service.release_task_escrow", new=release),
        pytest.raises(PermissionError),
    ):
        await task_service.submit_result(
            task_id=task_id, agent_did="did:agentx:exec-001", result_payload={},
        )
    release.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_status", ["COMPLETED", "FAILED", "PENDING", "IN_PROGRESS"])
async def test_submit_result_refuses_a_task_not_awaiting_a_result(task_status):
    """S9-6a: a second submit (task already COMPLETED) pays nothing and records nothing."""
    task_id = uuid4()
    agent_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": task_status, "executor_agent_id": agent_id},
        {"agent_id": agent_id},
    ])
    conn.execute = AsyncMock()
    release = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.record_event", new=AsyncMock()) as mock_trust,
        patch("src.services.token_service.release_task_escrow", new=release),
        pytest.raises(task_service.TaskConflictError, match="not awaiting a result"),
    ):
        await task_service.submit_result(
            task_id=task_id, agent_did="did:agentx:exec-001", result_payload={},
        )

    conn.execute.assert_not_awaited()
    release.assert_not_awaited()
    mock_trust.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_result_raises_if_task_not_found():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Task not found"),
    ):
        await task_service.submit_result(
            task_id=uuid4(),
            agent_did="did:agentx:exec-001",
            result_payload={},
        )


@pytest.mark.asyncio
async def test_submit_result_raises_if_agent_not_found():
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "assigned"},  # task found
        None,                                          # agent not found
    ])

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Agent not found"),
    ):
        await task_service.submit_result(
            task_id=task_id,
            agent_did="did:agentx:ghost-001",
            result_payload={},
        )
