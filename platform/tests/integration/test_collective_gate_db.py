"""
Integration tests: who may create a collective, against REAL local Postgres.
Phase C, Sprint 22, CL-1.

Every caller here has trust 0.5 (the newcomer's score), below the 0.7 floor.

What is proven (HTTP → router → collective_gate → Postgres):
  • shipped defaults: a newcomer who has been paid for a task is still refused
  • path on (COLLECTIVE_MIN_PAID_JOBS=1): refused with no paid job; allowed
    after one task approved and paid by another agent; a paid bounty counts too
  • a task the caller posted itself, a payout still in escrow (not approved),
    and a payout for a bounty the caller created do not count
  • the per-day limit holds: the 4th create in 24 hours is 429 and writes
    nothing; a collective created over 24 hours ago no longer counts
  • 5 creates racing at the limit: at most the limit succeed

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_collective_gate_db.py -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent
from .test_bounty_escrow_db import evaluate, open_bounty, submit
from .test_task_escrow_db import assigned_task, open_task

pytestmark = pytest.mark.integration   # skipped unless --db is given

OLD = 30


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest.fixture
def gate(monkeypatch):
    """Set the three settings; defaults are the shipped ones."""
    from src.config import get_settings

    def set_(trust="0.7", jobs="0", per_day="3"):
        s = get_settings()
        monkeypatch.setattr(s, "collective_min_trust", trust)
        monkeypatch.setattr(s, "collective_min_paid_jobs", jobs)
        monkeypatch.setattr(s, "collective_create_per_day", per_day)

    set_()
    return set_


async def create(client, agent: Agent, name: str = "Group"):
    return await client.post(
        "/collectives", json={"name": name, "description": "a group"}, headers=agent.headers,
    )


async def owned(pool, agent: Agent) -> int:
    return await pool.fetchval("SELECT COUNT(*) FROM collectives WHERE owner_did = $1", agent.did)


async def paid_task(client, creator: Agent, worker: Agent) -> str:
    task_id = await assigned_task(client, creator, worker)
    resp = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {}}, headers=worker.headers)
    assert resp.status_code == 201, resp.text
    resp = await client.post(f"/tasks/{task_id}/approve", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    return task_id


# ── The gate ──────────────────────────────────────────────────────────────────

async def test_defaults_refuse_a_paid_newcomer(client, pool, agents, gate):
    poster = await agents("poster", START_BALANCE, age_days=OLD)
    newcomer = await agents("newcomer", 0)
    await paid_task(client, poster, newcomer)

    resp = await create(client, newcomer)
    assert resp.status_code == 403
    assert "0.70" in resp.json()["detail"]
    assert await owned(pool, newcomer) == 0


async def test_path_on_one_paid_task_qualifies(client, pool, agents, gate):
    gate(jobs="1")
    poster = await agents("poster", START_BALANCE, age_days=OLD)
    newcomer = await agents("newcomer", 0)

    refused = await create(client, newcomer)
    assert refused.status_code == 403
    assert "(you have 0)" in refused.json()["detail"]

    task_id = await assigned_task(client, poster, newcomer)
    await client.post(f"/tasks/{task_id}/result", json={"result_payload": {}},
                      headers=newcomer.headers)
    # Handed in but not approved: nothing paid yet, still refused.
    assert (await create(client, newcomer)).status_code == 403

    assert (await client.post(f"/tasks/{task_id}/approve",
                              headers=poster.headers)).status_code == 200
    resp = await create(client, newcomer)
    assert resp.status_code == 201, resp.text
    assert resp.json()["owner_did"] == newcomer.did
    assert await owned(pool, newcomer) == 1


async def test_path_on_a_paid_bounty_qualifies(client, pool, agents, gate):
    gate(jobs="1")
    poster = await agents("poster", START_BALANCE, age_days=OLD)
    winner = await agents("winner", 0)
    bounty_id = await open_bounty(client, poster)
    submission_id = await submit(client, bounty_id, winner)
    await evaluate(client, bounty_id, submission_id, poster, 0.9)
    assert (await create(client, winner)).status_code == 403
    paid = await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=poster.headers)
    assert paid.status_code == 200, paid.text
    assert (await create(client, winner)).status_code == 201


async def test_self_paid_work_does_not_count(client, pool, agents, gate):
    """The API refuses self-bids, so self-payment is written by hand: an
    escrow release and a bounty payout into the caller's wallet for work the
    caller posted. Neither counts."""
    gate(jobs="1")
    me = await agents("me", START_BALANCE, age_days=OLD)
    my_wallet = await pool.fetchval("SELECT wallet_id FROM wallets WHERE agent_id = $1", me.agent_id)
    task_id = await open_task(client, me)
    bounty_id = await open_bounty(client, me)
    for related, tx_type in ((task_id, "escrow_release"), (bounty_id, "bounty_reward")):
        await pool.execute(
            "INSERT INTO transactions (from_wallet, to_wallet, amount, type, related_id) "
            "VALUES (NULL, $1, 50, $2, $3)", my_wallet, tx_type, UUID(related))

    resp = await create(client, me)
    assert resp.status_code == 403
    assert "(you have 0)" in resp.json()["detail"]


async def test_a_ledger_type_outside_the_list_does_not_count(client, pool, agents, gate):
    gate(jobs="1")
    poster = await agents("poster", START_BALANCE, age_days=OLD)
    me = await agents("me", START_BALANCE)
    my_wallet = await pool.fetchval("SELECT wallet_id FROM wallets WHERE agent_id = $1", me.agent_id)
    task_id = await open_task(client, poster)
    for tx_type in ("faucet", "task_work_deadline_refund", "contract_dispute_release"):
        await pool.execute(
            "INSERT INTO transactions (from_wallet, to_wallet, amount, type, related_id) "
            "VALUES (NULL, $1, 50, $2, $3)", my_wallet, tx_type, UUID(task_id))
    assert (await create(client, me)).status_code == 403


# ── The per-day limit ─────────────────────────────────────────────────────────

async def test_fourth_create_in_a_day_is_429(client, pool, agents, gate):
    gate(trust="0.5")
    me = await agents("me", 0)
    for n in range(3):
        assert (await create(client, me, f"G{n}")).status_code == 201
    resp = await create(client, me, "G3")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    assert await owned(pool, me) == 3

    # A day later the oldest no longer counts.
    await pool.execute(
        "UPDATE collectives SET created_at = now() - interval '25 hours' WHERE owner_did = $1",
        me.did)
    assert (await create(client, me, "G4")).status_code == 201


async def test_racing_creates_never_pass_the_limit(client, pool, agents, gate, monkeypatch):
    """Each create pauses between the limit check and its INSERT, so without
    the per-agent lock all five would read 0 and all five would be written."""
    from src.routers import collectives as router
    real_insert = router._insert_collective

    async def slow_insert(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await real_insert(*args, **kwargs)

    monkeypatch.setattr(router, "_insert_collective", slow_insert)
    gate(trust="0.5", per_day="2")
    me = await agents("me", 0)
    results = await asyncio.gather(*(create(client, me, f"R{n}") for n in range(5)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 429, 429, 429], codes
    assert await owned(pool, me) == 2
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM collective_members WHERE agent_did = $1 AND role = 'OWNER'",
        me.did) == 2


async def test_the_limit_is_per_agent(client, pool, agents, gate):
    gate(trust="0.5", per_day="1")
    a = await agents("a", 0)
    b = await agents("b", 0)
    assert (await create(client, a)).status_code == 201
    assert (await create(client, a)).status_code == 429
    assert (await create(client, b)).status_code == 201
