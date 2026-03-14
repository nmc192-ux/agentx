"""
Tests: src/services/collective_service.py
Phase 6 — Agent Collectives

Covers:
  - create_collective()          — inserts collective + OWNER member, returns CollectiveResponse
  - join_collective()            — creates PENDING member, validates collective exists
  - list_collectives()           — paginated list, optional name filter
  - get_members()                — returns ACTIVE members, validates collective exists
  - assign_task_to_collective()  — validates collective/task/role, inserts record, updates task
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import collective_service


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _collective_row(col_id=None, owner="did:agentx:atlas-001"):
    col_id = col_id or uuid4()
    return {
        "collective_id":   col_id,
        "name":            "Founding Council",
        "description":     "The original eight",
        "charter":         None,
        "is_public":       True,
        "owner_did":       owner,
        "member_count":    1,
        "trust_score_avg": 0.90,
        "created_at":      _now(),
    }


def _member_row(
    agent_did="did:agentx:atlas-001",
    display_name="ATLAS",
    role="OWNER",
    status="ACTIVE",
    trust_score=0.98,
):
    return {
        "agent_did":    agent_did,
        "display_name": display_name,
        "role":         role,
        "status":       status,
        "trust_score":  trust_score,
        "joined_at":    _now(),
    }


def _col_task_row(col_id=None, task_id=None, assigned_by="did:agentx:atlas-001"):
    return {
        "collective_task_id": uuid4(),
        "collective_id":      col_id or uuid4(),
        "task_id":            task_id or uuid4(),
        "assigned_by_did":    assigned_by,
        "status":             "assigned",
        "assigned_at":        _now(),
    }


# ── create_collective ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_collective_returns_response():
    owner = "did:agentx:atlas-001"
    col_id = uuid4()
    row = _collective_row(col_id=col_id, owner=owner)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock()

    with patch("src.services.collective_service.transaction", return_value=_tx_context(conn)):
        result = await collective_service.create_collective(
            name="Founding Council",
            description="The original eight",
            charter=None,
            is_public=True,
            owner_did=owner,
        )

    assert result.name == "Founding Council"
    assert result.owner_did == owner
    assert result.member_count == 1
    conn.fetchrow.assert_awaited_once()
    conn.execute.assert_awaited_once()  # INSERT INTO collective_members


@pytest.mark.asyncio
async def test_create_collective_adds_owner_member():
    """The INSERT INTO collective_members call must include 'OWNER' and 'ACTIVE'."""
    owner = "did:agentx:atlas-001"
    row = _collective_row(owner=owner)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock()

    with patch("src.services.collective_service.transaction", return_value=_tx_context(conn)):
        await collective_service.create_collective(
            name="Test", description="Test collective",
            charter=None, is_public=True, owner_did=owner,
        )

    call_sql = conn.execute.await_args.args[0]
    assert "OWNER" in call_sql
    assert "ACTIVE" in call_sql


# ── join_collective ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_join_collective_creates_pending_member():
    col_id = uuid4()
    agent_did = "did:agentx:bruno-001"

    db_conn = AsyncMock()
    db_conn.fetchval = AsyncMock(return_value=1)  # collective exists

    tx_conn = AsyncMock()
    tx_conn.execute = AsyncMock()

    with (
        patch("src.services.collective_service.get_db", return_value=_tx_context(db_conn)),
        patch("src.services.collective_service.transaction", return_value=_tx_context(tx_conn)),
    ):
        result = await collective_service.join_collective(col_id, agent_did)

    assert result["status"] == "pending"
    assert result["agent_did"] == agent_did
    assert result["collective_id"] == str(col_id)
    tx_conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_collective_raises_if_collective_not_found():
    db_conn = AsyncMock()
    db_conn.fetchval = AsyncMock(return_value=None)  # not found

    with (
        patch("src.services.collective_service.get_db", return_value=_tx_context(db_conn)),
        pytest.raises(ValueError, match="Collective not found"),
    ):
        await collective_service.join_collective(uuid4(), "did:agentx:ghost-001")


# ── list_collectives ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_collectives_returns_paginated():
    rows = [_collective_row(), _collective_row()]

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=2)   # total count
    conn.fetch = AsyncMock(return_value=rows)

    with patch("src.services.collective_service.get_db", return_value=_tx_context(conn)):
        result = await collective_service.list_collectives(page=1, limit=20)

    assert len(result.collectives) == 2
    assert result.total == 2
    assert result.page == 1
    assert result.has_more is False


@pytest.mark.asyncio
async def test_list_collectives_empty_result():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    with patch("src.services.collective_service.get_db", return_value=_tx_context(conn)):
        result = await collective_service.list_collectives()

    assert result.collectives == []
    assert result.total == 0
    assert result.has_more is False


@pytest.mark.asyncio
async def test_list_collectives_has_more_when_page_partial():
    rows = [_collective_row() for _ in range(5)]

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=25)   # 25 total, page 1 of 5
    conn.fetch = AsyncMock(return_value=rows)

    with patch("src.services.collective_service.get_db", return_value=_tx_context(conn)):
        result = await collective_service.list_collectives(page=1, limit=5)

    assert result.has_more is True


# ── get_members ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_members_returns_active_list():
    col_id = uuid4()
    members = [
        _member_row("did:agentx:atlas-001", role="OWNER"),
        _member_row("did:agentx:bruno-001", role="MEMBER"),
    ]

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)  # collective exists
    conn.fetch = AsyncMock(return_value=members)

    with patch("src.services.collective_service.get_db", return_value=_tx_context(conn)):
        result = await collective_service.get_members(col_id)

    assert len(result) == 2
    assert result[0].agent_did == "did:agentx:atlas-001"
    assert result[0].role == "OWNER"


@pytest.mark.asyncio
async def test_get_members_empty_collective():
    col_id = uuid4()

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])

    with patch("src.services.collective_service.get_db", return_value=_tx_context(conn)):
        result = await collective_service.get_members(col_id)

    assert result == []


@pytest.mark.asyncio
async def test_get_members_raises_if_collective_not_found():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)

    with (
        patch("src.services.collective_service.get_db", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Collective not found"),
    ):
        await collective_service.get_members(uuid4())


# ── assign_task_to_collective ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_task_inserts_record_and_updates_task():
    col_id = uuid4()
    task_id = uuid4()
    assigner = "did:agentx:atlas-001"
    ct_row = _col_task_row(col_id=col_id, task_id=task_id, assigned_by=assigner)

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[
        1,          # collective exists
    ])
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open"},  # task exists
        ct_row,                                    # INSERT RETURNING
    ])
    conn.execute = AsyncMock()  # UPDATE tasks

    # fetchval for assigner role check (3rd call — after collective & task)
    conn.fetchval = AsyncMock(side_effect=[
        1,        # collective exists
        "OWNER",  # assigner role
    ])
    conn.fetchrow = AsyncMock(side_effect=[
        {"task_id": task_id, "status": "open"},  # task exists
        ct_row,                                    # INSERT collective_task
    ])

    with patch("src.services.collective_service.transaction", return_value=_tx_context(conn)):
        result = await collective_service.assign_task_to_collective(
            collective_id=col_id,
            task_id=task_id,
            assigned_by_did=assigner,
        )

    assert result.collective_id == ct_row["collective_id"]
    assert result.task_id == ct_row["task_id"]
    assert result.status == "assigned"
    # UPDATE tasks must have been called
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_task_raises_if_collective_not_found():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)  # collective missing

    with (
        patch("src.services.collective_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Collective not found"),
    ):
        await collective_service.assign_task_to_collective(
            collective_id=uuid4(),
            task_id=uuid4(),
            assigned_by_did="did:agentx:atlas-001",
        )


@pytest.mark.asyncio
async def test_assign_task_raises_if_task_not_found():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)    # collective exists
    conn.fetchrow = AsyncMock(return_value=None)  # task missing

    with (
        patch("src.services.collective_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="Task not found"),
    ):
        await collective_service.assign_task_to_collective(
            collective_id=uuid4(),
            task_id=uuid4(),
            assigned_by_did="did:agentx:atlas-001",
        )


@pytest.mark.asyncio
async def test_assign_task_raises_if_not_owner_or_admin():
    col_id = uuid4()
    task_id = uuid4()

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[
        1,        # collective exists
        "MEMBER", # assigner is only MEMBER
    ])
    conn.fetchrow = AsyncMock(return_value={"task_id": task_id, "status": "open"})

    with (
        patch("src.services.collective_service.transaction", return_value=_tx_context(conn)),
        pytest.raises(ValueError, match="must be OWNER or ADMIN"),
    ):
        await collective_service.assign_task_to_collective(
            collective_id=col_id,
            task_id=task_id,
            assigned_by_did="did:agentx:outsider-001",
        )
