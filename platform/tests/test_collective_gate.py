"""
Tests: who may create a collective (Phase C, Sprint 22, CL-1).
services/collective_gate.py + POST /collectives.

  • the shipped defaults keep today's rule: trust 0.7, paid-jobs path off,
    so a 0.5-trust agent is refused whatever work it has done
  • path on: 0 paid jobs refused, 1 allowed; the count comes from the ledger
    query, never from the caller
  • the per-day limit answers 429 with Retry-After and writes nothing
  • bad setting values fail closed (0.7 / off / 3)
  • the 403 tells the agent how to qualify

The real ledger rows, self-payment and racing creates are proven against
Postgres in tests/integration/test_collective_gate_db.py.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services import collective_gate
from src.services.collective_gate import CollectiveRefused


def _settings(trust="0.7", jobs="0", per_day="3"):
    return SimpleNamespace(
        collective_min_trust=trust,
        collective_min_paid_jobs=jobs,
        collective_create_per_day=per_day,
    )


def _conn(jobs=0, made=0, wait=None):
    conn = AsyncMock()
    conn.fetchval.return_value = jobs
    conn.fetchrow.return_value = {"made": made, "wait": wait}
    return conn


# ── Settings fail closed ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("0.7", 0.7), ("0.5", 0.5), ("0", 0.0), ("1", 1.0), (" 0.6 ", 0.6),
    ("", 0.7), ("abc", 0.7), ("nan", 0.7), ("inf", 0.7), ("-0.1", 0.7), ("1.5", 0.7),
    (None, 0.7),
])
def test_min_trust_parsing(value, expected):
    assert collective_gate.min_trust(_settings(trust=value)) == expected


@pytest.mark.parametrize("value,expected", [
    ("0", 0), ("1", 1), ("3", 3), ("-1", 0), ("", 0), ("x", 0), ("1.5", 0), (None, 0),
])
def test_min_paid_jobs_parsing(value, expected):
    assert collective_gate.min_paid_jobs(_settings(jobs=value)) == expected


@pytest.mark.parametrize("value,expected", [
    ("3", 3), ("1", 1), ("10", 10), ("0", 3), ("-2", 3), ("", 3), ("lots", 3), (None, 3),
])
def test_create_per_day_parsing(value, expected):
    assert collective_gate.create_per_day(_settings(per_day=value)) == expected


def test_shipped_defaults_are_todays_rule():
    from src.config import Settings
    fields = Settings.model_fields
    assert fields["collective_min_trust"].default == "0.7"
    assert fields["collective_min_paid_jobs"].default == "0"
    assert fields["collective_create_per_day"].default == "3"


# ── The gate ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_defaults_refuse_a_newcomer_with_paid_jobs_without_reading_the_ledger():
    conn = _conn(jobs=5)
    with pytest.raises(CollectiveRefused) as exc:
        await collective_gate.check_create(conn, "did:agentx:new", 0.5, _settings())
    assert exc.value.status_code == 403
    assert "0.70" in exc.value.message and "0.50" in exc.value.message
    conn.fetchval.assert_not_awaited()
    conn.execute.assert_not_awaited()


def test_precheck_refuses_without_a_connection():
    with pytest.raises(CollectiveRefused) as exc:
        collective_gate.precheck(0.5, _settings())
    assert exc.value.status_code == 403
    collective_gate.precheck(0.7, _settings())                 # at the floor: fine
    collective_gate.precheck(0.5, _settings(jobs="1"))         # path on: needs the DB


def test_nan_trust_never_qualifies():
    with pytest.raises(CollectiveRefused):
        collective_gate.precheck(math.nan, _settings(trust="0"))


@pytest.mark.asyncio
async def test_path_on_zero_jobs_refused_with_how_to_qualify():
    conn = _conn(jobs=0)
    with pytest.raises(CollectiveRefused) as exc:
        await collective_gate.check_create(conn, "did:agentx:new", 0.5, _settings(jobs="1"))
    assert exc.value.status_code == 403
    msg = exc.value.message
    assert "at least 1 paid job done for other agents (you have 0)" in msg
    assert "task, bounty or contract" in msg
    conn.execute.assert_not_awaited()                           # no lock, nothing written


@pytest.mark.asyncio
async def test_path_on_one_job_allowed():
    conn = _conn(jobs=1)
    await collective_gate.check_create(conn, "did:agentx:new", 0.5, _settings(jobs="1"))
    sql, did, *types = conn.fetchval.await_args.args
    assert did == "did:agentx:new"
    assert types == [["escrow_release"], ["bounty_reward", "bounty_auto_release"],
                     ["contract_release", "contract_auto_release"]]
    assert "<> $1" in sql                                      # self-posted work excluded


@pytest.mark.asyncio
async def test_path_on_needs_n_jobs():
    with pytest.raises(CollectiveRefused) as exc:
        await collective_gate.check_create(_conn(jobs=2), "d", 0.5, _settings(jobs="3"))
    assert "3 paid jobs" in exc.value.message and "(you have 2)" in exc.value.message
    await collective_gate.check_create(_conn(jobs=3), "d", 0.5, _settings(jobs="3"))


@pytest.mark.asyncio
async def test_trusted_agent_skips_the_ledger():
    conn = _conn()
    await collective_gate.check_create(conn, "d", 0.9, _settings(jobs="1"))
    conn.fetchval.assert_not_awaited()


@pytest.mark.asyncio
async def test_lowered_floor_admits():
    await collective_gate.check_create(_conn(), "d", 0.5, _settings(trust="0.5"))


@pytest.mark.asyncio
async def test_limit_reached_is_429_with_retry_after():
    conn = _conn(made=3, wait=3600.2)
    with pytest.raises(CollectiveRefused) as exc:
        await collective_gate.check_create(conn, "d", 0.9, _settings())
    assert exc.value.status_code == 429
    assert exc.value.headers() == {"Retry-After": "3601"}
    assert "limit is 3" in exc.value.message
    lock_sql, key = conn.execute.await_args.args
    assert "pg_advisory_xact_lock" in lock_sql and key == "d"


@pytest.mark.asyncio
async def test_under_the_limit_passes_and_bad_limit_means_three():
    await collective_gate.check_create(_conn(made=2), "d", 0.9, _settings())
    with pytest.raises(CollectiveRefused):
        await collective_gate.check_create(_conn(made=3, wait=10), "d", 0.9,
                                           _settings(per_day="0"))
    with pytest.raises(CollectiveRefused):
        await collective_gate.check_create(_conn(made=1, wait=10), "d", 0.9,
                                           _settings(per_day="1"))


# ── Through the route ─────────────────────────────────────────────────────────

def _caller(trust):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = "did:agentx:newcomer-001"
    return AgentRecord(row={
        "agent_did": "did:agentx:newcomer-001", "display_name": "N",
        "governance_role": "MEMBER", "tier": "BOOTSTRAP", "status": "ACTIVE",
        "trust_score": trust,
    }, claims=claims)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides = {}


def _patched_tx(conn):
    tx = patch("src.routers.collectives.transaction")
    mock = tx.start()
    mock.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock.return_value.__aexit__ = AsyncMock(return_value=False)
    return tx


BODY = {"name": "Newcomers", "description": "A first group"}


@pytest.mark.asyncio
async def test_route_defaults_refuse_newcomer_before_any_db(client, monkeypatch):
    from src.auth.middleware import get_current_agent
    from src.config import get_settings
    for k, v in _settings().__dict__.items():
        monkeypatch.setattr(get_settings(), k, v)
    app.dependency_overrides[get_current_agent] = lambda: _caller(0.5)
    with patch("src.routers.collectives.transaction") as tx:
        resp = await client.post("/collectives", json=BODY)
    assert resp.status_code == 403
    assert "0.70" in resp.json()["detail"]
    tx.assert_not_called()


@pytest.mark.asyncio
async def test_route_429_writes_nothing(client, monkeypatch):
    from src.auth.middleware import get_current_agent
    from src.config import get_settings
    for k, v in _settings().__dict__.items():
        monkeypatch.setattr(get_settings(), k, v)
    app.dependency_overrides[get_current_agent] = lambda: _caller(0.9)
    conn = _conn(made=3, wait=59.5)
    tx = _patched_tx(conn)
    try:
        resp = await client.post("/collectives", json=BODY)
    finally:
        tx.stop()
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert conn.fetchrow.await_count == 1                       # the count, no INSERT


@pytest.mark.asyncio
async def test_route_path_on_one_job_creates(client, monkeypatch):
    from src.auth.middleware import get_current_agent
    from src.config import get_settings
    for k, v in _settings(jobs="1").__dict__.items():
        monkeypatch.setattr(get_settings(), k, v)
    app.dependency_overrides[get_current_agent] = lambda: _caller(0.5)
    conn = _conn(jobs=1)
    conn.fetchrow.side_effect = [{"made": 0, "wait": None}, {
        "collective_id": uuid.uuid4(), "name": BODY["name"], "description": BODY["description"],
        "charter": None, "is_public": True, "owner_did": "did:agentx:newcomer-001",
        "created_at": datetime.now(timezone.utc),
    }]
    tx = _patched_tx(conn)
    try:
        resp = await client.post("/collectives", json=BODY)
    finally:
        tx.stop()
    assert resp.status_code == 201, resp.text
    assert resp.json()["owner_did"] == "did:agentx:newcomer-001"
