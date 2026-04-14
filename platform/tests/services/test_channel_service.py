"""
Tests: src/services/channel_service.py
Phase 1 Enhanced Social Layer — Topic Channels

Covers:
  create_channel()
  list_channels()
  get_channel()
  add_post_to_channel()
  get_channel_feed()

All DB calls fully mocked via patched get_db / transaction context managers.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.channel_service import (
    create_channel,
    list_channels,
    get_channel,
    add_post_to_channel,
    get_channel_feed,
)
from src.models.channel import ChannelCreate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _channel_row(**overrides):
    defaults = {
        "channel_id": uuid4(),
        "community_id": uuid4(),
        "name": "general",
        "slug": "general",
        "description": "General discussion",
        "channel_type": "GENERAL",
        "is_default": True,
        "post_count": 0,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return defaults


class _FakeConn:
    """Minimal asyncpg connection stub.

    fetch() / fetchrow() return plain dicts so that dict(row) in service code
    produces a proper copy rather than an empty dict (MagicMock mapping trap).
    """
    def __init__(self, rows=None, fetchrow_val=None, fetchval_val=None, execute_val="INSERT 0 1"):
        self._rows = rows or []
        self._fetchrow_val = fetchrow_val
        self._fetchval_val = fetchval_val
        self._execute_val = execute_val

    async def fetch(self, *a, **kw):
        return list(self._rows)  # plain dicts — dict(r) works correctly

    async def fetchrow(self, *a, **kw):
        return self._fetchrow_val  # plain dict or None

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


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_channel_success():
    community_id = uuid4()
    row = _channel_row(community_id=community_id)
    member_row = {"role": "ADMIN"}
    conn = _FakeConn()

    calls = []
    async def mock_fetchrow(sql, *args, **kwargs):
        calls.append(sql)
        if "community_members" in sql:
            return member_row
        return row

    conn.fetchrow = mock_fetchrow

    with patch("src.services.channel_service.transaction", return_value=_TxCtx(conn)):
        result = await create_channel(
            community_id=community_id,
            creator_did="did:agentx:atlas-001",
            data=ChannelCreate(name="general", slug="general"),
        )

    assert result.name == "general"
    assert result.community_id == community_id


@pytest.mark.asyncio
async def test_create_channel_not_member():
    conn = _FakeConn(fetchrow_val=None)

    with patch("src.services.channel_service.transaction", return_value=_TxCtx(conn)):
        with pytest.raises(ValueError, match="Not a member"):
            await create_channel(
                community_id=uuid4(),
                creator_did="did:agentx:test-001",
                data=ChannelCreate(name="test", slug="test"),
            )


@pytest.mark.asyncio
async def test_list_channels():
    rows = [_channel_row(name="general"), _channel_row(name="announcements")]
    conn = _FakeConn(rows=rows)

    with patch("src.services.channel_service.get_db", return_value=_DbCtx(conn)):
        result = await list_channels(uuid4())

    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_channel_not_found():
    conn = _FakeConn(fetchrow_val=None)

    with patch("src.services.channel_service.get_db", return_value=_DbCtx(conn)):
        with pytest.raises(ValueError, match="Channel not found"):
            await get_channel(uuid4())


@pytest.mark.asyncio
async def test_get_channel_feed_empty():
    conn = _FakeConn(rows=[])

    with patch("src.services.channel_service.get_db", return_value=_DbCtx(conn)):
        result = await get_channel_feed(uuid4())

    assert result == []
