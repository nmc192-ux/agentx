"""
Tests: src/services/task_service.py
Phase 4 — Agent Task Economy

Covers:
  - create_task()    persists row, returns TaskResponse
  - list_tasks()     filters by status
  - submit_bid()     validates task/agent, inserts bid
  - assign_task()    creates assignment, updates task, enqueues
  - submit_result()  inserts result, marks assignment done, records trust
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
        {"task_id": task_id, "status": "open"},  # task lookup
        {"agent_id": agent_id},                   # agent lookup
        bid,                                       # insert RETURNING
    ])

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.assign_task", new=AsyncMock()),
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

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open"},                          # task lookup
        {"bid_id": bid_id, "agent_id": agent_id, "agent_did": "did:agentx:exec-001"},  # bid lookup
        assignment,                                                        # insert assignment
    ])
    conn.execute = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.enqueue_task", new=AsyncMock()) as mock_enqueue,
    ):
        result = await task_service.assign_task(task_id=task_id, bid_id=bid_id)

    assert result.status == "assigned"
    mock_enqueue.assert_awaited_once_with(str(task_id))
    # tasks UPDATE called once
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_task_raises_if_task_not_open():
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"task_id": task_id, "status": "assigned"})

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="cannot be assigned"),
    ):
        await task_service.assign_task(task_id=task_id, bid_id=uuid4())


@pytest.mark.asyncio
async def test_assign_task_raises_if_bid_not_found():
    task_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open"},  # task lookup
        None,                                      # bid not found
    ])

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Bid not found"),
    ):
        await task_service.assign_task(task_id=task_id, bid_id=uuid4())


# ── submit_result ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_result_inserts_result_and_records_trust():
    task_id = uuid4()
    agent_id = uuid4()
    result_row = _result_row(task_id=task_id, agent_id=agent_id)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "assigned"},  # task lookup
        {"agent_id": agent_id},                       # agent lookup
        result_row,                                    # insert RETURNING
    ])
    conn.execute = AsyncMock()

    with (
        patch("src.services.task_service.transaction", return_value=_tx_context(conn)),
        patch("src.services.task_service.record_event", new=AsyncMock()) as mock_trust,
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
