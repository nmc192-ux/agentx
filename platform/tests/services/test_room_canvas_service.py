"""
Tests: src/services/room_canvas_service.py
Phase 1 Collaboration Rooms — Canvas nodes + activity log

Covers:
  create_node()
  list_nodes()
  update_node()
  batch_move_nodes()
  delete_node()
  record_activity()
  get_activity()

All DB calls fully mocked via patched get_db / transaction context managers.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.services.room_canvas_service import (
    create_node,
    list_nodes,
    update_node,
    batch_move_nodes,
    delete_node,
    record_activity,
    get_activity,
)
from src.models.room import CanvasNodeCreate, CanvasNodeUpdate


# ── Helpers ──────────────────────────────────────────────────────────────────

def _node_row(**overrides):
    defaults = {
        "node_id": uuid4(),
        "room_id": uuid4(),
        "artifact_id": None,
        "node_type": "artifact",
        "label": "Test Node",
        "x": 100.0,
        "y": 200.0,
        "width": 180.0,
        "height": 80.0,
        "style": "{}",
        "created_by": "did:agentx:atlas-001",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


def _activity_row(**overrides):
    defaults = {
        "activity_id": uuid4(),
        "room_id": uuid4(),
        "agent_did": "did:agentx:atlas-001",
        "action": "joined",
        "detail": "{}",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


class _FakeConn:
    """Minimal asyncpg connection stub returning plain dicts."""
    def __init__(self, rows=None, fetchrow_val=None, fetchval_val=None, execute_val="INSERT 0 1"):
        self._rows = rows or []
        self._fetchrow_val = fetchrow_val
        self._fetchval_val = fetchval_val
        self._execute_val = execute_val

    async def fetch(self, *a, **kw):
        return list(self._rows)

    async def fetchrow(self, *a, **kw):
        return self._fetchrow_val

    async def fetchval(self, *a, **kw):
        return self._fetchval_val

    async def execute(self, *a, **kw):
        return self._execute_val


class _TxCtx:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        pass


class _DbCtx(_TxCtx):
    pass


# ── Canvas node tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_node_success():
    room_id = uuid4()
    node_row = _node_row(room_id=room_id)

    room_row = {"room_id": room_id, "status": "OPEN"}
    participant_row = {"role": "PARTICIPANT"}

    call_count = {"fetchrow": 0}

    async def mock_fetchrow(sql, *args, **kw):
        call_count["fetchrow"] += 1
        if call_count["fetchrow"] == 1:
            return room_row  # room check
        if call_count["fetchrow"] == 2:
            return participant_row  # participant check
        return node_row  # INSERT RETURNING

    conn = _FakeConn()
    conn.fetchrow = mock_fetchrow

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        result = await create_node(
            room_id=room_id,
            agent_did="did:agentx:atlas-001",
            data=CanvasNodeCreate(label="Test Node", x=100, y=200),
        )

    assert result.label == "Test Node"
    assert result.x == 100.0
    assert result.y == 200.0


@pytest.mark.asyncio
async def test_create_node_room_closed():
    room_row = {"room_id": uuid4(), "status": "CLOSED"}
    conn = _FakeConn(fetchrow_val=room_row)

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Room is closed"):
            await create_node(
                room_id=uuid4(),
                agent_did="did:agentx:test-001",
                data=CanvasNodeCreate(label="X"),
            )


@pytest.mark.asyncio
async def test_create_node_observer_blocked():
    room_row = {"room_id": uuid4(), "status": "OPEN"}
    participant_row = {"role": "OBSERVER"}

    call_count = {"fetchrow": 0}

    async def mock_fetchrow(sql, *args, **kw):
        call_count["fetchrow"] += 1
        if call_count["fetchrow"] == 1:
            return room_row
        return participant_row

    conn = _FakeConn()
    conn.fetchrow = mock_fetchrow

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Observers cannot modify"):
            await create_node(
                room_id=uuid4(),
                agent_did="did:agentx:test-001",
                data=CanvasNodeCreate(label="X"),
            )


@pytest.mark.asyncio
async def test_list_nodes_empty():
    conn = _FakeConn(rows=[])

    with patch("src.services.room_canvas_service.get_db", return_value=_DbCtx(conn)):
        result = await list_nodes(uuid4())

    assert result == []


@pytest.mark.asyncio
async def test_list_nodes_returns_items():
    rows = [_node_row(label="A"), _node_row(label="B")]
    conn = _FakeConn(rows=rows)

    with patch("src.services.room_canvas_service.get_db", return_value=_DbCtx(conn)):
        result = await list_nodes(uuid4())

    assert len(result) == 2
    assert result[0].label == "A"
    assert result[1].label == "B"


@pytest.mark.asyncio
async def test_update_node_not_found():
    conn = _FakeConn(fetchrow_val=None)

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Canvas node not found"):
            await update_node(
                uuid4(),
                "did:agentx:test-001",
                CanvasNodeUpdate(x=50),
            )


@pytest.mark.asyncio
async def test_delete_node_not_found():
    conn = _FakeConn(fetchrow_val=None)

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Canvas node not found"):
            await delete_node(uuid4(), "did:agentx:test-001")


@pytest.mark.asyncio
async def test_batch_move_not_participant():
    conn = _FakeConn(fetchrow_val=None)  # no participant row

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Not a participant"):
            await batch_move_nodes(
                uuid4(),
                "did:agentx:test-001",
                [{"node_id": str(uuid4()), "x": 10, "y": 20}],
            )


# ── Activity log tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_activity():
    room_id = uuid4()
    row = _activity_row(room_id=room_id, action="joined")
    conn = _FakeConn(fetchrow_val=row)

    with patch("src.services.room_canvas_service.transaction", return_value=_TxCtx(conn)):
        result = await record_activity(room_id, "did:agentx:atlas-001", "joined")

    assert result.action == "joined"
    assert result.room_id == room_id


@pytest.mark.asyncio
async def test_get_activity_empty():
    conn = _FakeConn(rows=[])

    with patch("src.services.room_canvas_service.get_db", return_value=_DbCtx(conn)):
        result = await get_activity(uuid4())

    assert result == []


@pytest.mark.asyncio
async def test_get_activity_returns_items():
    rows = [
        _activity_row(action="joined"),
        _activity_row(action="artifact_added"),
    ]
    conn = _FakeConn(rows=rows)

    with patch("src.services.room_canvas_service.get_db", return_value=_DbCtx(conn)):
        result = await get_activity(uuid4())

    assert len(result) == 2
    assert result[0].action == "joined"
    assert result[1].action == "artifact_added"
