"""
Tests: src/services/room_service.py
Phase 1 Enhanced Social Layer — Collaboration Rooms

Covers:
  create_room()
  get_room()
  list_rooms()
  join_room()
  leave_room()
  add_artifact()
  close_room()
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.room_service import (
    create_room,
    get_room,
    list_rooms,
    join_room,
    leave_room,
    add_artifact,
    close_room,
)
from src.models.room import RoomCreate, ArtifactCreate


def _room_row(**overrides):
    defaults = {
        "room_id": uuid4(),
        "name": "Test Room",
        "description": "",
        "community_id": None,
        "room_type": "WORKSHOP",
        "status": "OPEN",
        "max_participants": 12,
        "creator_did": "did:agentx:atlas-001",
        "participant_count": 1,
        "created_at": datetime.now(UTC),
        "closed_at": None,
    }
    defaults.update(overrides)
    return defaults


def _artifact_row(**overrides):
    defaults = {
        "artifact_id": uuid4(),
        "room_id": uuid4(),
        "author_did": "did:agentx:atlas-001",
        "artifact_type": "NOTE",
        "title": "Test Note",
        "content": json.dumps({"text": "hello"}),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


class _FakeConn:
    def __init__(self, rows=None, fetchrow_val=None, fetchval_val=None, execute_val="INSERT 0 1"):
        self._rows = rows or []
        self._fetchrow_val = fetchrow_val
        self._fetchval_val = fetchval_val
        self._execute_val = execute_val

    async def fetch(self, *a, **kw):
        return [MagicMock(**{k: v for k, v in r.items()}, __getitem__=lambda s, k: r[k]) for r in self._rows]

    async def fetchrow(self, *a, **kw):
        if self._fetchrow_val is not None:
            r = self._fetchrow_val
            return MagicMock(**{k: v for k, v in r.items()}, __getitem__=lambda s, k: r[k])
        return None

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


@pytest.mark.asyncio
async def test_create_room():
    row = _room_row()
    conn = _FakeConn(fetchrow_val=row)

    with patch("src.services.room_service.transaction", return_value=_TxCtx(conn)):
        result = await create_room(
            creator_did="did:agentx:atlas-001",
            data=RoomCreate(name="Test Room"),
        )

    assert result.name == "Test Room"
    assert result.room_type == "WORKSHOP"


@pytest.mark.asyncio
async def test_list_rooms_empty():
    conn = _FakeConn(rows=[])

    with patch("src.services.room_service.get_db", return_value=_DbCtx(conn)):
        result = await list_rooms()

    assert result == []


@pytest.mark.asyncio
async def test_join_room_full():
    room_row = {"room_id": uuid4(), "status": "OPEN", "max_participants": 2}
    conn = _FakeConn(fetchrow_val=room_row, fetchval_val=2)

    with patch("src.services.room_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Room is full"):
            await join_room(uuid4(), "did:agentx:test-001")


@pytest.mark.asyncio
async def test_leave_room_not_in():
    conn = _FakeConn(execute_val="DELETE 0")

    with patch("src.services.room_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Not in this room"):
            await leave_room(uuid4(), "did:agentx:test-001")


@pytest.mark.asyncio
async def test_add_artifact_observer_blocked():
    conn = _FakeConn()
    participant_row = {"role": "OBSERVER"}

    async def mock_fetchrow(sql, *args, **kwargs):
        if "room_participants" in sql:
            return MagicMock(**participant_row, __getitem__=lambda s, k: participant_row[k])
        return None

    conn.fetchrow = mock_fetchrow

    with patch("src.services.room_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Observers cannot add artifacts"):
            await add_artifact(
                uuid4(),
                "did:agentx:test-001",
                ArtifactCreate(title="test"),
            )
