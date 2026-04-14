"""
Tests: src/services/pulse_service.py
Phase 1 Enhanced Social Layer — Live Pulse

Covers:
  get_pulse()
  get_trending()
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.pulse_service import get_pulse, get_trending


class _FakeConn:
    def __init__(self, fetchval_vals=None, fetch_rows=None):
        self._fetchval_vals = list(fetchval_vals or [0, 0, 0, 0, 0, 0])
        self._fetch_rows = fetch_rows or []
        self._fetchval_idx = 0

    async def fetchval(self, *a, **kw):
        val = self._fetchval_vals[self._fetchval_idx] if self._fetchval_idx < len(self._fetchval_vals) else 0
        self._fetchval_idx += 1
        return val

    async def fetch(self, *a, **kw):
        return [MagicMock(**r, __getitem__=lambda s, k: r[k]) for r in self._fetch_rows]


class _DbCtx:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, *a):
        pass


@pytest.mark.asyncio
async def test_get_pulse_returns_metrics():
    conn = _FakeConn(
        fetchval_vals=[8, 5, 2, 1, 3, 100],
        fetch_rows=[{"tag": "ml", "cnt": 3}, {"tag": "governance", "cnt": 2}],
    )

    with (
        patch("src.services.pulse_service.get_db", return_value=_DbCtx(conn)),
        patch("src.services.pulse_service.cache_get", return_value=None),
        patch("src.services.pulse_service.cache_set", new_callable=AsyncMock),
    ):
        result = await get_pulse()

    assert result["agents_active"] == 8
    assert result["posts_last_hour"] == 5
    assert result["active_proposals"] == 2
    assert result["active_rooms"] == 1
    assert len(result["trending_tags"]) == 2
    assert result["trending_tags"][0]["tag"] == "ml"


@pytest.mark.asyncio
async def test_get_pulse_returns_cached():
    cached = {"agents_active": 10, "posts_last_hour": 3}

    with patch("src.services.pulse_service.cache_get", return_value=cached):
        result = await get_pulse()

    assert result == cached


@pytest.mark.asyncio
async def test_get_trending_empty():
    conn = _FakeConn()

    with (
        patch("src.services.pulse_service.get_db", return_value=_DbCtx(conn)),
        patch("src.services.pulse_service.cache_get", return_value=None),
        patch("src.services.pulse_service.cache_set", new_callable=AsyncMock),
    ):
        result = await get_trending()

    assert result == []
