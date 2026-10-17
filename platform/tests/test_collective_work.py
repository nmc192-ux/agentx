"""
Tests: work a collective has done (Phase C, Sprint 22, CL-3).

  GET /collectives/{id}/work — tasks assigned to the collective, counts by
  status, tokens earned (from the ledger), cached per collective.

Fails closed: a missing collective is 404; a private collective is 404 to an
anonymous caller and to anyone not an ACTIVE member, even when a copy is in
the cache; an unreadable cached copy is rebuilt from the database.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.middleware import public_list_limit as pll
from src.services import collective_work

ME = "did:agentx:me-001"
NOW = datetime.now(timezone.utc)
COL = uuid.uuid4()
TASK = uuid.uuid4()


def _caller(did=ME):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={"agent_did": did, "display_name": "me", "governance_role": "MEMBER",
             "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5},
        claims=claims,
    )


def _work_json():
    return {
        "collective_id": str(COL), "total_tasks": 1, "counts_by_status": {"completed": 1},
        "tokens_earned": 95,
        "tasks": [{"task_id": str(TASK), "title": "t", "status": "completed", "reward": 100,
                   "assigned_at": NOW.isoformat(), "tokens_earned": 95}],
    }


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture
def no_cache(monkeypatch):
    store = {}

    async def get(key):
        return store.get(key)

    async def set_(key, value, ttl=None):
        store[key] = value

    monkeypatch.setattr(collective_work.cache, "cache_get", get)
    monkeypatch.setattr(collective_work.cache, "cache_set", set_)
    return store


def _db(vis_row, counts=(), earned=0, rows=()):
    conn = AsyncMock()
    conn.fetchrow.return_value = vis_row
    conn.fetchval.return_value = earned
    conn.fetch.side_effect = [list(counts), list(rows)]
    ctx = patch("src.services.collective_work.get_db")
    mock_db = ctx.start()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, conn


async def _get(client, vis_row, auth=False, **db):
    from src.auth.middleware import get_current_agent_optional
    if auth:
        app.dependency_overrides[get_current_agent_optional] = lambda: _caller()
    ctx, conn = _db(vis_row, **db)
    try:
        resp = await client.get(f"/collectives/{COL}/work")
    finally:
        ctx.stop()
    return resp, conn


ROWS = [
    {"task_id": TASK, "title": "Review a PR", "status": "completed", "reward": 100,
     "assigned_at": NOW, "earned": 95},
    {"task_id": uuid.uuid4(), "title": "summarise", "status": "assigned", "reward": 40,
     "assigned_at": NOW, "earned": 0},
]
COUNTS = [{"status": "completed", "n": 1}, {"status": "assigned", "n": 1}]


async def test_public_collective_anonymous(client, no_cache):
    resp, conn = await _get(client, {"is_public": True, "active": False},
                            counts=COUNTS, earned=95, rows=ROWS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_tasks"] == 2
    assert body["counts_by_status"] == {"completed": 1, "assigned": 1}
    assert body["tokens_earned"] == 95
    assert [t["tokens_earned"] for t in body["tasks"]] == [95, 0]
    assert body["tasks"][0]["title"] == "Review a PR"
    # anonymous: no DID passed to the visibility read
    assert conn.fetchrow.await_args.args[2] is None
    # ledger read restricted to the task payout type
    assert conn.fetchval.await_args.args[2] == ["escrow_release"]


async def test_missing_collective_404(client, no_cache):
    resp, conn = await _get(client, None)
    assert resp.status_code == 404
    assert conn.fetch.await_count == 0


async def test_private_collective_404_anonymous_and_non_member(client, no_cache):
    resp, conn = await _get(client, {"is_public": False, "active": False})
    assert resp.status_code == 404
    assert conn.fetch.await_count == 0 and conn.fetchval.await_count == 0
    resp, conn = await _get(client, {"is_public": False, "active": False}, auth=True)
    assert resp.status_code == 404
    assert conn.fetchrow.await_args.args[2] == ME
    assert conn.fetch.await_count == 0


async def test_private_collective_member_200(client, no_cache):
    resp, _ = await _get(client, {"is_public": False, "active": True}, auth=True,
                         counts=COUNTS, earned=95, rows=ROWS)
    assert resp.status_code == 200
    assert resp.json()["tokens_earned"] == 95


async def test_public_answer_cached(client, no_cache):
    await _get(client, {"is_public": True, "active": False}, counts=COUNTS, earned=95, rows=ROWS)
    resp, conn = await _get(client, {"is_public": True, "active": False})
    assert resp.status_code == 200
    assert resp.json()["tokens_earned"] == 95
    assert conn.fetchrow.await_count == 0          # served from the cache


async def test_private_cached_copy_still_checks_caller(client, no_cache):
    no_cache[collective_work._cache_key(COL)] = {"is_public": False, "work": _work_json()}
    resp, conn = await _get(client, {"is_public": False, "active": False}, auth=True)
    assert resp.status_code == 404
    assert conn.fetchrow.await_count == 1
    resp, conn = await _get(client, {"is_public": False, "active": True}, auth=True)
    assert resp.status_code == 200
    assert conn.fetch.await_count == 0             # work from cache, visibility from DB


@pytest.mark.parametrize("junk", [
    "garbage", {"is_public": True}, {"is_public": True, "work": {"bad": 1}},
    {"is_public": "yes", "work": "x"},
])
async def test_unreadable_cache_rebuilt(client, no_cache, junk):
    no_cache[collective_work._cache_key(COL)] = junk
    resp, conn = await _get(client, {"is_public": False, "active": False})
    assert resp.status_code == 404                 # junk never short-cuts the check
    resp, conn = await _get(client, {"is_public": True, "active": False},
                            counts=COUNTS, earned=95, rows=ROWS)
    assert resp.status_code == 200
    assert conn.fetch.await_count == 2


async def test_bad_id_422(client, no_cache):
    resp = await client.get("/collectives/not-a-uuid/work")
    assert resp.status_code == 422


def test_on_the_per_ip_list_budget():
    assert pll.is_list_path(f"/collectives/{COL}/work")
    assert not pll.is_list_path(f"/collectives/{COL}/work/extra")
