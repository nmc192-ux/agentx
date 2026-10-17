"""
Integration tests: work a collective has done, against REAL local Postgres.
Phase C, Sprint 22, CL-3.

What is proven (HTTP → router → collective_work → Postgres):
  • tasks assigned to a collective are listed (newest first) with counts by
    status; tokens earned equal the escrow_release rows in the ledger for
    those tasks, not the reward on the task row
  • a task handed in but not approved earns nothing yet
  • a task not assigned to the collective is not counted
  • a private collective's work is 404 to anonymous callers and outsiders,
    200 to an ACTIVE member; a missing collective is 404

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_collective_work_db.py -v --db
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from .support import START_BALANCE
from .test_collective_membership_db import make_collective
from .test_task_escrow_db import assigned_task

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest.fixture(autouse=True)
def fresh_reads(monkeypatch):
    """Every read rebuilds from the database (the cache is unit-tested)."""
    from src.services import collective_work

    async def miss(key):
        return None

    monkeypatch.setattr(collective_work.cache, "cache_get", miss)


@pytest_asyncio.fixture(autouse=True)
async def optional_caller(agents):
    """The conftest stands in for get_current_agent only; the work read uses the
    optional login, so map it onto the same stand-in (no header → anonymous)."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    async def _optional(request: Request):
        try:
            return await app.dependency_overrides[get_current_agent](request)
        except HTTPException:
            return None

    app.dependency_overrides[get_current_agent_optional] = _optional
    yield
    app.dependency_overrides.pop(get_current_agent_optional, None)


async def work(client, col, headers=None):
    return await client.get(f"/collectives/{col}/work", headers=headers or {})


async def ledger_paid(pool, task_ids) -> int:
    return int(await pool.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions"
        " WHERE type = 'escrow_release' AND related_id = ANY($1::uuid[])",
        [uuid.UUID(t) for t in task_ids],
    ))


@pytest.mark.asyncio
async def test_work_matches_the_ledger(client, pool, agents):
    poster = await agents("poster", START_BALANCE, age_days=30)
    worker = await agents("worker", 0)
    col = await make_collective(pool, worker)

    done = await assigned_task(client, poster, worker, reward=100)
    handed_in = await assigned_task(client, poster, worker, reward=60)
    elsewhere = await assigned_task(client, poster, worker, reward=40)   # not the group's
    for t in (done, handed_in):
        r = await client.post(f"/collectives/{col}/tasks", json={"task_id": t},
                              headers=worker.headers)
        assert r.status_code == 201, r.text

    r = await work(client, col)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_tasks"] == 2 and body["tokens_earned"] == 0
    assert body["counts_by_status"] == {"assigned": 2}

    for t in (done, handed_in, elsewhere):
        r = await client.post(f"/tasks/{t}/result", json={"result_payload": {}},
                              headers=worker.headers)
        assert r.status_code == 201, r.text
    for t in (done, elsewhere):
        r = await client.post(f"/tasks/{t}/approve", headers=poster.headers)
        assert r.status_code == 200, r.text

    resp = await work(client, col)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    paid = await ledger_paid(pool, [done])
    assert paid > 0
    assert body["tokens_earned"] == paid
    assert body["counts_by_status"] == {"completed": 1, "in_review": 1}
    by_id = {t["task_id"]: t for t in body["tasks"]}
    assert set(by_id) == {done, handed_in}
    assert by_id[done]["tokens_earned"] == paid and by_id[done]["status"] == "completed"
    assert by_id[done]["reward"] == 100
    assert by_id[handed_in]["tokens_earned"] == 0
    assert [t["task_id"] for t in body["tasks"]] == [handed_in, done]   # newest first


@pytest.mark.asyncio
async def test_private_work_hidden_from_outsiders(client, pool, agents):
    owner, outsider, asker = [await agents(n) for n in ("own", "out", "ask")]
    col = await make_collective(pool, owner, is_public=False)
    r = await client.post(f"/collectives/{col}/join", json={}, headers=asker.headers)
    assert r.status_code == 202

    assert (await work(client, col)).status_code == 404
    for who in (outsider, asker):                 # a PENDING asker is not a member yet
        assert (await work(client, col, who.headers)).status_code == 404
    r = await work(client, col, owner.headers)
    assert r.status_code == 200
    assert r.json()["total_tasks"] == 0


@pytest.mark.asyncio
async def test_missing_collective_404(client):
    assert (await work(client, uuid.uuid4())).status_code == 404
