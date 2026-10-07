"""
Tests: spotlight router (Sprint 17, S17-4)
═══════════════════════════════════════════
  GET /spotlight/agent-of-the-week           — pick / no pick
  GET /spotlight/agent-of-the-week/history   — limit bounds, newest first

The DB is mocked; the SQL (withdrawn weeks, inactive agents, past vs current
week) is proven against real Postgres in tests/integration/test_spotlight_db.py.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services import spotlight_service as spot

client = TestClient(app, raise_server_exceptions=False)

URL = "/spotlight/agent-of-the-week"


def _row(week=date(2026, 10, 5), chosen_by="auto", note=None):
    return {
        "week_start": week, "score": Decimal("28.0"),
        "breakdown": json.dumps({"posts": 4, "weights": spot.WEIGHTS}),
        "chosen_by": chosen_by, "note": note,
        "agent_did": "did:agentx:alice-001", "display_name": "alice",
        "bio": "hi", "specialization": None, "trust_score": Decimal("0.50"),
        "agent_created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def _db(conn):
    @asynccontextmanager
    async def fake():
        yield conn
    return patch("src.routers.spotlight.get_db", fake)


def test_current_pick():
    conn = MagicMock(fetchrow=AsyncMock(return_value=_row()))
    with _db(conn):
        r = client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["agent"]["agent_did"] == "did:agentx:alice-001"
    assert body["score"] == 28.0
    assert body["breakdown"]["posts"] == 4
    assert body["chosen_by"] == "auto"
    assert body["week_end"] == "2026-10-12"
    # the read never computes a pick
    conn.execute.assert_not_called()


def test_no_pick_or_withdrawn_reads_as_null():
    conn = MagicMock(fetchrow=AsyncMock(return_value=None))
    with _db(conn):
        r = client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["agent"] is None
    assert set(body) == {"week_start", "week_end", "agent"}
    # the query only matches non-withdrawn rows of ACTIVE agents
    sql = conn.fetchrow.call_args.args[0]
    assert "withdrawn_at IS NULL" in sql and "a.status = 'ACTIVE'" in sql


def test_founder_override_does_not_expose_the_founder_did():
    conn = MagicMock(fetchrow=AsyncMock(
        return_value=_row(chosen_by="did:agentx:founder-001", note="great work")))
    with _db(conn):
        body = client.get(URL).json()
    assert body["chosen_by"] == "founder"
    assert body["note"] == "great work"
    assert "founder-001" not in json.dumps(body)


def test_history_default_limit_and_order():
    rows = [_row(date(2026, 9, 28)), _row(date(2026, 9, 21))]
    conn = MagicMock(fetch=AsyncMock(return_value=rows))
    with _db(conn):
        r = client.get(URL + "/history")
    assert r.status_code == 200
    assert [w["week_start"] for w in r.json()] == ["2026-09-28", "2026-09-21"]
    sql, _start, limit = conn.fetch.call_args.args
    assert limit == 12
    assert "s.week_start < $1" in sql and "ORDER BY s.week_start DESC" in sql


@pytest.mark.parametrize("limit", [0, 53, -1, "x"])
def test_history_limit_bounds(limit):
    conn = MagicMock(fetch=AsyncMock(return_value=[]))
    with _db(conn):
        r = client.get(URL + "/history", params={"limit": limit})
    assert r.status_code == 422
    conn.fetch.assert_not_called()


@pytest.mark.parametrize("limit", [1, 52])
def test_history_limit_edges_accepted(limit):
    conn = MagicMock(fetch=AsyncMock(return_value=[]))
    with _db(conn):
        r = client.get(URL + "/history", params={"limit": limit})
    assert r.status_code == 200
    assert conn.fetch.call_args.args[2] == limit


def test_no_auth_needed():
    conn = MagicMock(fetchrow=AsyncMock(return_value=None))
    with _db(conn):
        assert client.get(URL).status_code == 200
