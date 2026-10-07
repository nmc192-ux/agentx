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


# ── S17-5: founder override (fails closed) ────────────────────────────────────
# Auth is checked before the week or the body: every refusal below happens
# without the service being called.

WEEK_URL = URL + "/2099-01-05"          # a Monday, far in the future
BODY = {"agent_did": "did:agentx:alice-001", "note": "great work"}


def _caller(role: str):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    did = f"did:agentx:{role.lower()}-001"
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(row={
        "agent_did": did, "display_name": role, "governance_role": role,
        "tier": "STANDARD", "status": "ACTIVE", "trust_score": 0.9,
    }, claims=claims)


@pytest.fixture
def login():
    from src.auth.middleware import get_current_agent

    def as_role(role: str):
        app.dependency_overrides[get_current_agent] = lambda: _caller(role)
    yield as_role
    app.dependency_overrides.pop(get_current_agent, None)


def _stored(**kw):
    row = {"week_start": date(2099, 1, 5), "agent_did": BODY["agent_did"],
           "chosen_by": "did:agentx:founder-001", "note": "great work",
           "withdrawn_at": None}
    row.update(kw)
    return row


def _service(name, **kw):
    return patch(f"src.routers.spotlight.spotlight_service.{name}",
                 new_callable=AsyncMock, **kw)


_WRITES = [("put", BODY, "override_week"), ("delete", None, "withdraw_week")]


def _send(method, body, url=WEEK_URL, **kw):
    if body is None:
        return client.request(method.upper(), url, **kw)
    return client.request(method.upper(), url, json=body, **kw)


@pytest.mark.parametrize("method,body,fn", _WRITES)
def test_override_unauthenticated_is_401(method, body, fn):
    with _service(fn) as svc:
        r = _send(method, body)
        r2 = _send(method, body, headers={"Authorization": "Bearer not-a-jwt"})
        # a malformed week or body still answers 401 to an anonymous caller
        r3 = _send(method, {} if body else None, url=URL + "/not-a-week")
    assert r.status_code == r2.status_code == r3.status_code == 401
    svc.assert_not_called()


@pytest.mark.parametrize("role", ["MEMBER", "OPERATOR", "OBSERVER"])
@pytest.mark.parametrize("method,body,fn", _WRITES)
def test_override_non_founder_is_403(login, role, method, body, fn):
    login(role)
    with _service(fn) as svc:
        r = _send(method, body)
        r2 = _send(method, body, url=URL + "/not-a-week")
    assert r.status_code == r2.status_code == 403
    svc.assert_not_called()


@pytest.mark.parametrize("week", ["not-a-week", "2099-01-06", "2099-1-5",
                                  "2099-02-30", "20990105", "2099-01-05T00:00",
                                  "\u0662\u0660\u0669\u0669-\u0660\u0661-\u0660\u0665",  # Arabic-Indic digits pass \d
                                  "2099-01-05%0A", "2099-01-05%20", "2099-01-05;DROP"])
@pytest.mark.parametrize("method,body,fn", _WRITES)
def test_override_malformed_week_is_422(login, week, method, body, fn):
    login("FOUNDER")
    with _service(fn) as svc:
        r = _send(method, body, url=f"{URL}/{week}")
    assert r.status_code == 422
    svc.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"agent_did": ""}, {"agent_did": "did:x", "note": "n" * 501}])
def test_override_bad_body_is_422(login, body):
    login("FOUNDER")
    with _service("override_week") as svc:
        r = client.put(WEEK_URL, json=body)
    assert r.status_code == 422
    svc.assert_not_called()


def test_founder_override_records_the_caller_not_the_body(login):
    login("FOUNDER")
    body = {**BODY, "chosen_by": "did:agentx:someone-else"}   # ignored
    with _db(MagicMock()), _service("override_week", return_value=_stored()) as svc:
        r = client.put(WEEK_URL, json=body)
    assert r.status_code == 200
    assert r.json() == {"week_start": "2099-01-05", "agent_did": BODY["agent_did"],
                        "chosen_by": "did:agentx:founder-001", "note": "great work",
                        "withdrawn": False}
    args = svc.call_args.args
    assert args[1:] == (date(2099, 1, 5), BODY["agent_did"], "great work",
                        "did:agentx:founder-001")


def test_founder_withdraw(login):
    login("FOUNDER")
    stored = _stored(withdrawn_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
    with _db(MagicMock()), _service("withdraw_week", return_value=stored) as svc:
        r = client.delete(WEEK_URL)
    assert r.status_code == 200 and r.json()["withdrawn"] is True
    assert svc.call_args.args[1:] == (date(2099, 1, 5), "did:agentx:founder-001")


@pytest.mark.parametrize("code", [400, 404, 409, 422])
@pytest.mark.parametrize("method,body,fn", _WRITES)
def test_service_refusals_pass_through(login, code, method, body, fn):
    login("FOUNDER")
    err = spot.SpotlightRefused(code, "no")
    with _db(MagicMock()), _service(fn, side_effect=err):
        r = _send(method, body)
    assert r.status_code == code and r.json()["detail"] == "no"


def test_misconfigured_roster_is_503(login):
    from src.founders.roster import RosterConfigError
    login("FOUNDER")
    with _db(MagicMock()), _service("override_week", side_effect=RosterConfigError("bad")):
        r = client.put(WEEK_URL, json=BODY)
    assert r.status_code == 503
