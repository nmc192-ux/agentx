"""
Integration tests: /tasks ownership and escrow against REAL local Postgres
Sprint 9, S9-6a — the proof behind enabling the `tasks` router.

Every request goes HTTP → routers/tasks.py → task_service / token_service →
Postgres. Only the JWT check is replaced (the caller is set per request) and
the Redis event bus is silenced; no money path is mocked. The fixtures (the
throwaway database, the pool, the caller stand-in) are in conftest.py.

What is proven:
  • nobody can spend, bid, accept, complete or update as another agent
  • a reward is paid once, however often or however concurrently a result is
    submitted, and to the assigned executor only
  • concurrent bids assign a task to exactly one agent
  • tokens are conserved: wallets + escrow never change in total
  • (S9-7b) a reward is always funded: a wallet that cannot cover it means no
    task, and task + escrow + fee are one transaction
  • (S9-7b) only the creator can cancel, only an open task, and the reward
    and the fee are refunded once, however many cancels (or bids) race

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db

The tests build their own throwaway database, `agentx_smoke_escrow` (same
init-db.sql → alembic chain as scripts/smoke_routers.py and CI), on localhost
only, and never touch any other database.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    """The app creates the treasury at startup; the test client does not run
    the startup hooks, so make sure it is there (idempotent)."""
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    """The task-creation budget is not under test here (the harness sends no
    Bearer token, so every caller would share one per-IP bucket; the limit is
    covered in tests/routers/test_open_write_limits.py)."""
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


# ── DB probes ─────────────────────────────────────────────────────────────────

async def task_row(pool, task_id: str):
    return await pool.fetchrow(
        "SELECT status, escrowed_reward, executor_agent_id, task_fee FROM tasks WHERE task_id = $1",
        UUID(task_id),
    )


async def releases(pool, task_id: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = 'escrow_release'",
        UUID(task_id),
    )


async def ledger(pool, task_id: str, tx_type: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = $2",
        UUID(task_id), tx_type,
    )


async def treasury_balance(pool) -> int:
    return await pool.fetchval("SELECT balance FROM wallets WHERE wallet_type = 'treasury'")


async def tasks_by(pool, creator: Agent) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM tasks WHERE creator_agent_id = $1", creator.agent_id,
    )


async def trust_events(pool, agent: Agent) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM trust_events WHERE agent_id = $1", agent.agent_id,
    )


async def open_task(client, creator: Agent, reward: int = 100) -> str:
    resp = await client.post(
        "/tasks", json={"task_type": "escrow.test", "reward": reward}, headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["task_id"]


async def assigned_task(client, creator: Agent, executor: Agent, reward: int = 100) -> str:
    """Open task, then a 0.9-confidence bid — the platform auto-accepts it."""
    task_id = await open_task(client, creator, reward)
    resp = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.9, "bid_price": 1}, headers=executor.headers,
    )
    assert resp.status_code == 201, resp.text
    return task_id


# ── Creating a task: only the caller's own wallet is escrowed ─────────────────

async def test_reward_is_escrowed_from_the_callers_own_wallet(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    before = await total_tokens(pool)

    task_id = await open_task(client, creator, reward=100)

    row = await task_row(pool, task_id)
    assert row["status"] == "open"
    assert await balance(pool, creator) == START_BALANCE - 100
    assert row["escrowed_reward"] + row["task_fee"] == 100   # fee went to the treasury
    assert row["escrowed_reward"] > 0
    assert await total_tokens(pool) == before


async def test_cannot_escrow_another_agents_wallet(client, pool, agents):
    """The hole S9-6 found: POST /tasks trusted `creator_agent_did` from the body."""
    victim = await agents("victim", START_BALANCE)
    attacker = await agents("attacker", 0)
    tasks_before = await pool.fetchval("SELECT COUNT(*) FROM tasks")

    resp = await client.post(
        "/tasks",
        json={"creator_agent_did": victim.did, "task_type": "x", "reward": 500},
        headers=attacker.headers,
    )
    assert resp.status_code == 403
    anon = await client.post(
        "/tasks", json={"creator_agent_did": victim.did, "task_type": "x", "reward": 500},
    )
    assert anon.status_code == 401

    assert await balance(pool, victim) == START_BALANCE
    assert await pool.fetchval("SELECT COUNT(*) FROM tasks") == tasks_before


async def test_open_marketplace_task_is_readable(client, pool, agents):
    """GET /tasks/{id} used to 500 on an open task (executor is NULL)."""
    creator = await agents("creator", START_BALANCE)
    task_id = await open_task(client, creator)
    resp = await client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["executor_agent_did"] is None


# ── Bids and accepting ────────────────────────────────────────────────────────

async def test_creator_cannot_bid_on_own_task(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    task_id = await open_task(client, creator)

    resp = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.9}, headers=creator.headers,
    )
    assert resp.status_code == 403
    assert (await task_row(pool, task_id))["status"] == "open"
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM task_bids WHERE task_id = $1", UUID(task_id)) == 0


async def test_cannot_bid_as_another_agent(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    victim = await agents("victim")
    attacker = await agents("attacker")
    task_id = await open_task(client, creator)

    resp = await client.post(
        f"/tasks/{task_id}/bid",
        json={"agent_did": victim.did, "confidence": 0.9}, headers=attacker.headers,
    )
    assert resp.status_code == 403
    assert (await task_row(pool, task_id))["status"] == "open"


async def test_only_the_creator_can_accept_a_bid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bidder = await agents("bidder")
    attacker = await agents("attacker")
    task_id = await open_task(client, creator)

    # confidence < 0.3 → recorded, not auto-accepted
    bid = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.2}, headers=bidder.headers,
    )
    assert bid.status_code == 201
    bid_id = bid.json()["bid_id"]
    assert (await task_row(pool, task_id))["status"] == "open"

    for intruder in (attacker, bidder):          # not even the bidder themself
        resp = await client.post(
            f"/tasks/{task_id}/accept", params={"bid_id": bid_id}, headers=intruder.headers,
        )
        assert resp.status_code == 403
    assert (await client.post(
        f"/tasks/{task_id}/accept", params={"bid_id": bid_id})).status_code == 401
    assert (await task_row(pool, task_id))["status"] == "open"

    ok = await client.post(
        f"/tasks/{task_id}/accept", params={"bid_id": bid_id}, headers=creator.headers,
    )
    assert ok.status_code == 200
    row = await task_row(pool, task_id)
    assert row["status"] == "assigned"
    assert row["executor_agent_id"] == bidder.agent_id


async def test_concurrent_bids_assign_the_task_exactly_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bidders = [await agents(f"bidder{i}") for i in range(8)]
    task_id = await open_task(client, creator)

    responses = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/bid", json={"confidence": 0.9}, headers=b.headers)
        for b in bidders
    ])
    assert all(r.status_code in (201, 422) for r in responses), [r.text for r in responses]

    assignments = await pool.fetch(
        "SELECT agent_id FROM task_assignments WHERE task_id = $1", UUID(task_id))
    assert len(assignments) == 1
    row = await task_row(pool, task_id)
    assert row["status"] == "assigned"
    assert row["executor_agent_id"] == assignments[0]["agent_id"]


async def test_concurrent_accepts_assign_the_task_exactly_once(client, pool, agents):
    """The creator accepts eight different bids at the same moment: one wins."""
    creator = await agents("creator", START_BALANCE)
    task_id = await open_task(client, creator)
    bid_ids = []
    for i in range(8):
        bidder = await agents(f"bidder{i}")
        bid = await client.post(
            f"/tasks/{task_id}/bid", json={"confidence": 0.1}, headers=bidder.headers)
        assert bid.status_code == 201
        bid_ids.append(bid.json()["bid_id"])
    assert (await task_row(pool, task_id))["status"] == "open"

    responses = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/accept", params={"bid_id": b}, headers=creator.headers)
        for b in bid_ids
    ])
    assert sorted(r.status_code for r in responses) == [200] + [422] * 7

    assignments = await pool.fetch(
        "SELECT agent_id FROM task_assignments WHERE task_id = $1", UUID(task_id))
    assert len(assignments) == 1
    assert (await task_row(pool, task_id))["executor_agent_id"] == assignments[0]["agent_id"]


# ── Results: executor only, paid once ─────────────────────────────────────────

async def test_only_the_assigned_executor_gets_paid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor")            # no wallet yet
    attacker = await agents("attacker", 0)
    before = await total_tokens(pool)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    assert escrowed > 0

    # Outsider, the creator, an outsider naming the executor, and no login at all.
    for caller, body in (
        (attacker, {"result_payload": {"steal": True}}),
        (creator, {"result_payload": {}}),
        (attacker, {"agent_did": executor.did, "result_payload": {}}),
    ):
        resp = await client.post(f"/tasks/{task_id}/result", json=body, headers=caller.headers)
        assert resp.status_code == 403, resp.text
    anon = await client.post(
        f"/tasks/{task_id}/result", json={"agent_did": executor.did, "result_payload": {}})
    assert anon.status_code == 401

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("assigned", escrowed)
    assert await balance(pool, attacker) == 0
    assert await releases(pool, task_id) == 0
    assert await trust_events(pool, attacker) == 0

    ok = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {"done": True}},
        headers=executor.headers,
    )
    assert ok.status_code == 201, ok.text
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("COMPLETED", 0)
    # The executor had no wallet: one is created holding exactly the escrow.
    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await total_tokens(pool) == before


async def test_resubmitting_a_result_pays_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    first = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {}}, headers=executor.headers)
    assert first.status_code == 201
    events_after_first = await trust_events(pool, executor)

    for _ in range(3):
        again = await client.post(
            f"/tasks/{task_id}/result", json={"result_payload": {}}, headers=executor.headers)
        assert again.status_code == 409

    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert await trust_events(pool, executor) == events_after_first == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM task_results WHERE task_id = $1", UUID(task_id)) == 1


async def test_concurrent_result_submissions_pay_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=2)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    responses = await asyncio.gather(*[
        client.post(
            f"/tasks/{task_id}/result", json={"result_payload": {"n": n}},
            headers=executor.headers,
        )
        for n in range(12)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 11, codes

    assert await balance(pool, executor) == escrowed
    assert await releases(pool, task_id) == 1
    assert (await task_row(pool, task_id))["escrowed_reward"] == 0
    assert await trust_events(pool, executor) == 1
    assert await total_tokens(pool) == before


async def test_escrow_release_itself_is_locked(client, pool, agents):
    """token_service level: even called directly and concurrently (bypassing the
    task-status guard), the escrow is paid out once — release and refund race."""
    from src.services import token_service

    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    creator_after_escrow = await balance(pool, creator)

    paid = await asyncio.gather(
        *[token_service.release_task_escrow(UUID(task_id), executor.agent_id) for _ in range(6)],
        *[token_service.refund_task_escrow(UUID(task_id), creator.agent_id) for _ in range(6)],
    )
    assert sorted(paid) == [0] * 11 + [escrowed]

    gained = (await balance(pool, executor)) + (await balance(pool, creator)) - creator_after_escrow
    assert gained == escrowed
    assert (await task_row(pool, task_id))["escrowed_reward"] == 0
    assert await total_tokens(pool) == before


# ── Direct tasks: /tasks/create and /tasks/{id}/update ────────────────────────

async def test_direct_task_requester_is_the_caller(client, pool, agents):
    requester = await agents("requester")
    executor = await agents("executor")
    victim = await agents("victim")

    forged = await client.post(
        "/tasks/create",
        json={"requester_agent_did": victim.did, "executor_agent_did": executor.did,
              "task_type": "direct.test"},
        headers=requester.headers,
    )
    assert forged.status_code == 403

    resp = await client.post(
        "/tasks/create",
        json={"executor_agent_did": executor.did, "task_type": "direct.test"},
        headers=requester.headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["requester_agent_did"] == requester.did


async def test_only_the_executor_can_update_and_only_forward(client, pool, agents):
    requester = await agents("requester")
    executor = await agents("executor")
    attacker = await agents("attacker")
    created = await client.post(
        "/tasks/create",
        json={"executor_agent_did": executor.did, "task_type": "direct.test"},
        headers=requester.headers,
    )
    task_id = created.json()["task_id"]

    for caller in (attacker, requester):
        resp = await client.post(
            f"/tasks/{task_id}/update", json={"status": "COMPLETED"}, headers=caller.headers)
        assert resp.status_code == 403
    assert (await client.post(
        f"/tasks/{task_id}/update", json={"status": "COMPLETED"})).status_code == 401
    assert (await task_row(pool, task_id))["status"] == "PENDING"
    assert await trust_events(pool, executor) == 0

    done = await client.post(
        f"/tasks/{task_id}/update", json={"status": "COMPLETED", "result": {"ok": True}},
        headers=executor.headers,
    )
    assert done.status_code == 200, done.text
    # S9-9b: a direct task carries no reward, so finishing one earns no trust
    # (it used to record TASK_COMPLETED + SERVICE_USED).
    assert await trust_events(pool, executor) == 0

    # Re-open / re-complete to farm more trust events: refused.
    for body in ({"status": "PENDING"}, {"status": "COMPLETED"}, {"result": {"x": 1}}):
        resp = await client.post(f"/tasks/{task_id}/update", json=body, headers=executor.headers)
        assert resp.status_code == 409
    assert (await task_row(pool, task_id))["status"] == "COMPLETED"
    assert await trust_events(pool, executor) == 0


async def test_concurrent_completions_record_reputation_once(client, pool, agents):
    requester = await agents("requester")
    executor = await agents("executor")
    created = await client.post(
        "/tasks/create",
        json={"executor_agent_did": executor.did, "task_type": "direct.test"},
        headers=requester.headers,
    )
    task_id = created.json()["task_id"]

    responses = await asyncio.gather(*[
        client.post(
            f"/tasks/{task_id}/update", json={"status": "COMPLETED"}, headers=executor.headers)
        for _ in range(8)
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 7
    assert await trust_events(pool, executor) == 0     # unfunded: see test_trust_farming_db


async def test_marketplace_task_cannot_be_completed_through_update(client, pool, agents):
    """`/update` must not be a way round `/result` (which is what pays)."""
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    resp = await client.post(
        f"/tasks/{task_id}/update", json={"status": "COMPLETED"}, headers=executor.headers)
    assert resp.status_code == 409
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("assigned", escrowed)
    assert await trust_events(pool, executor) == 0


async def test_self_assigned_task_earns_no_reputation(client, pool, agents):
    loner = await agents("loner")
    created = await client.post(
        "/tasks/create",
        json={"executor_agent_did": loner.did, "task_type": "direct.test"},
        headers=loner.headers,
    )
    task_id = created.json()["task_id"]
    done = await client.post(
        f"/tasks/{task_id}/update", json={"status": "COMPLETED"}, headers=loner.headers)
    assert done.status_code == 200
    assert await trust_events(pool, loner) == 0


# ── S9-7b: a reward is always funded ──────────────────────────────────────────

async def test_reward_the_wallet_cannot_cover_creates_no_task(client, pool, agents):
    """Was soft-fail: the task was created anyway, advertising a reward that
    nobody would ever be paid."""
    poor = await agents("poor", 40)
    walletless = await agents("walletless")            # no wallet at all
    before = await total_tokens(pool)

    for creator in (poor, walletless):
        resp = await client.post(
            "/tasks", json={"task_type": "unfunded.test", "reward": 100},
            headers=creator.headers,
        )
        assert resp.status_code == 400, resp.text
        assert "Insufficient funds" in resp.json()["detail"]
        assert await tasks_by(pool, creator) == 0

    assert await balance(pool, poor) == 40
    assert await balance(pool, walletless) is None      # no wallet conjured up
    assert await total_tokens(pool) == before


async def test_task_without_a_reward_needs_no_wallet(client, pool, agents):
    creator = await agents("creator")
    task_id = await open_task(client, creator, reward=0)
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"], row["task_fee"]) == ("open", 0, 0)
    assert await ledger(pool, task_id, "escrow") == 0


async def test_reward_larger_than_the_column_is_refused_cleanly(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    resp = await client.post(
        "/tasks", json={"task_type": "huge.test", "reward": 2**31}, headers=creator.headers,
    )
    assert resp.status_code == 422
    assert await balance(pool, creator) == START_BALANCE


async def test_task_escrow_and_fee_are_one_transaction(client, pool, agents, monkeypatch):
    """If the fee step blows up, the task and the escrow are rolled back with
    it (they used to be three separate transactions)."""
    from src.services import economy_service

    creator = await agents("creator", START_BALANCE)
    before = await total_tokens(pool)

    async def boom(conn, task_id, escrow_amount):
        raise RuntimeError("fee step failed")
    monkeypatch.setattr(economy_service, "_collect_task_fee", boom)

    with pytest.raises(RuntimeError):
        await client.post(
            "/tasks", json={"task_type": "atomic.test", "reward": 100}, headers=creator.headers,
        )

    assert await tasks_by(pool, creator) == 0
    assert await balance(pool, creator) == START_BALANCE
    assert await total_tokens(pool) == before


async def test_concurrent_creates_cannot_overspend_the_wallet(client, pool, agents):
    creator = await agents("creator", 150)
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[
        client.post(
            "/tasks", json={"task_type": "race.test", "reward": 100}, headers=creator.headers)
        for _ in range(6)
    ])
    assert sorted(r.status_code for r in responses) == [201] + [400] * 5

    assert await tasks_by(pool, creator) == 1
    assert await balance(pool, creator) == 50
    assert await total_tokens(pool) == before


# ── S9-7b: cancelling a task nobody took ──────────────────────────────────────

async def test_cancel_refunds_the_reward_and_the_fee(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    task_id = await open_task(client, creator, reward=1000)
    row = await task_row(pool, task_id)
    assert (row["escrowed_reward"], row["task_fee"]) == (975, 25)
    assert await balance(pool, creator) == 0
    assert await treasury_balance(pool) == treasury_before + 25

    resp = await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"], row["task_fee"]) == ("cancelled", 0, 0)
    assert await balance(pool, creator) == START_BALANCE          # made whole
    assert await treasury_balance(pool) == treasury_before        # the platform keeps nothing
    assert await ledger(pool, task_id, "escrow_refund") == 1
    assert await ledger(pool, task_id, "fee_refund") == 1
    assert await total_tokens(pool) == before

    # It left the open list and can be found under its own status.
    open_ids = [t["task_id"] for t in (await client.get("/tasks", params={"limit": 200})).json()]
    assert task_id not in open_ids
    cancelled = (await client.get("/tasks", params={"status": "cancelled", "limit": 200})).json()
    assert task_id in [t["task_id"] for t in cancelled]
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "cancelled"


async def test_only_the_creator_can_cancel(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    attacker = await agents("attacker", 0)
    founder = await agents("founder", 0, role="FOUNDER")
    task_id = await open_task(client, creator, reward=100)
    creator_after_escrow = await balance(pool, creator)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]

    for intruder in (attacker, founder):                 # not even a FOUNDER
        resp = await client.post(f"/tasks/{task_id}/cancel", headers=intruder.headers)
        assert resp.status_code == 403, resp.text
    assert (await client.post(f"/tasks/{task_id}/cancel")).status_code == 401

    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("open", escrowed)
    assert await balance(pool, creator) == creator_after_escrow
    assert await balance(pool, attacker) == 0
    assert await ledger(pool, task_id, "escrow_refund") == 0


async def test_a_taken_or_finished_task_cannot_be_cancelled(client, pool, agents):
    """Once an executor is assigned the escrow is theirs to earn."""
    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    before = await total_tokens(pool)
    task_id = await assigned_task(client, creator, executor)
    escrowed = (await task_row(pool, task_id))["escrowed_reward"]
    creator_after_escrow = await balance(pool, creator)

    resp = await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)
    assert resp.status_code == 409, resp.text
    row = await task_row(pool, task_id)
    assert (row["status"], row["escrowed_reward"]) == ("assigned", escrowed)

    done = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {}}, headers=executor.headers)
    assert done.status_code == 201
    resp = await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)
    assert resp.status_code == 409                       # paid work is not clawed back

    assert await balance(pool, executor) == escrowed
    assert await balance(pool, creator) == creator_after_escrow
    assert await ledger(pool, task_id, "escrow_refund") == 0
    assert await ledger(pool, task_id, "fee_refund") == 0
    assert await total_tokens(pool) == before


async def test_cancel_unknown_task_and_direct_task(client, pool, agents):
    requester = await agents("requester", START_BALANCE)
    executor = await agents("executor")
    missing = await client.post(
        "/tasks/00000000-0000-4000-8000-000000000000/cancel", headers=requester.headers)
    assert missing.status_code == 404

    created = await client.post(
        "/tasks/create",
        json={"executor_agent_did": executor.did, "task_type": "direct.test"},
        headers=requester.headers,
    )
    direct_id = created.json()["task_id"]
    for caller in (requester, executor):
        resp = await client.post(f"/tasks/{direct_id}/cancel", headers=caller.headers)
        assert resp.status_code in (403, 409)
    assert (await task_row(pool, direct_id))["status"] == "PENDING"


async def test_concurrent_cancels_refund_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)
    task_id = await open_task(client, creator, reward=1000)

    responses = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/cancel", headers=creator.headers) for _ in range(12)
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 11

    assert await balance(pool, creator) == START_BALANCE          # not 12 refunds
    assert await treasury_balance(pool) == treasury_before
    assert await ledger(pool, task_id, "escrow_refund") == 1
    assert await ledger(pool, task_id, "fee_refund") == 1
    assert await total_tokens(pool) == before


async def test_cancel_racing_bids_ends_in_exactly_one_outcome(client, pool, agents):
    """Cancel and auto-accepting bids at the same moment: either the task is
    cancelled and fully refunded, or it is assigned and the escrow stays for
    the executor — never both, never neither."""
    outcomes = set()
    for round_no in range(6):
        creator = await agents(f"creator{round_no}", START_BALANCE)
        bidders = [await agents(f"bidder{round_no}-{i}") for i in range(4)]
        before = await total_tokens(pool)
        task_id = await open_task(client, creator, reward=1000)

        async def cancel_after(delay: float):
            await asyncio.sleep(delay)
            return await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)

        # Stagger the cancel by 0–50 ms so that both outcomes really happen
        # (first rounds: the cancel wins; last rounds: a bid is in first).
        cancel, *bids = await asyncio.gather(
            cancel_after(round_no * 0.01),
            *[client.post(f"/tasks/{task_id}/bid", json={"confidence": 0.9}, headers=b.headers)
              for b in bidders],
        )
        outcomes.add(cancel.status_code)
        assert cancel.status_code in (200, 409), cancel.text
        assert all(b.status_code in (201, 422) for b in bids), [b.text for b in bids]

        row = await task_row(pool, task_id)
        assignments = await pool.fetchval(
            "SELECT COUNT(*) FROM task_assignments WHERE task_id = $1", UUID(task_id))
        if cancel.status_code == 200:
            assert (row["status"], row["escrowed_reward"], assignments) == ("cancelled", 0, 0)
            assert row["executor_agent_id"] is None
            assert await balance(pool, creator) == START_BALANCE
        else:
            assert (row["status"], row["escrowed_reward"], assignments) == ("assigned", 975, 1)
            assert await balance(pool, creator) == 0
            assert await ledger(pool, task_id, "escrow_refund") == 0
        assert await total_tokens(pool) == before
    assert outcomes == {200, 409}, "the race only ever went one way; adjust the stagger"


async def test_cancelled_task_takes_no_more_bids_or_accepts(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bidder = await agents("bidder")
    task_id = await open_task(client, creator, reward=100)
    low = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.1}, headers=bidder.headers)
    bid_id = low.json()["bid_id"]

    assert (await client.post(
        f"/tasks/{task_id}/cancel", headers=creator.headers)).status_code == 200

    late_bid = await client.post(
        f"/tasks/{task_id}/bid", json={"confidence": 0.9}, headers=bidder.headers)
    assert late_bid.status_code == 422
    accept = await client.post(
        f"/tasks/{task_id}/accept", params={"bid_id": bid_id}, headers=creator.headers)
    assert accept.status_code == 422
    result = await client.post(
        f"/tasks/{task_id}/result", json={"result_payload": {}}, headers=bidder.headers)
    assert result.status_code == 403
    row = await task_row(pool, task_id)
    assert (row["status"], row["executor_agent_id"]) == ("cancelled", None)
    assert await balance(pool, creator) == START_BALANCE


async def test_fee_refund_never_overdraws_the_treasury(client, pool, agents):
    """Nothing takes tokens out of the treasury today, so it always holds the
    fee. If that ever changes: the cancel still refunds the reward, the fee
    stays where it is, and the treasury never goes below zero."""
    creator = await agents("creator", START_BALANCE)
    task_id = await open_task(client, creator, reward=1000)
    before = await total_tokens(pool)
    held = await treasury_balance(pool)
    # Simulate an emptied treasury by moving its balance into a stake-free
    # holding wallet (tokens conserved, so the totals still add up).
    sink = await agents("sink", 0)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE wallets SET balance = 0 WHERE wallet_type = 'treasury'")
        await conn.execute(
            "UPDATE wallets SET balance = balance + $1 WHERE agent_id = $2", held, sink.agent_id)
    try:
        resp = await client.post(f"/tasks/{task_id}/cancel", headers=creator.headers)
        assert resp.status_code == 200, resp.text

        row = await task_row(pool, task_id)
        assert (row["status"], row["escrowed_reward"], row["task_fee"]) == ("cancelled", 0, 25)
        assert await balance(pool, creator) == START_BALANCE - 25
        assert await treasury_balance(pool) == 0
        assert await ledger(pool, task_id, "fee_refund") == 0
        assert await total_tokens(pool) == before
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE wallets SET balance = balance - $1 WHERE agent_id = $2",
                held, sink.agent_id)
            await conn.execute(
                "UPDATE wallets SET balance = balance + $1 WHERE wallet_type = 'treasury'", held)


async def test_database_accepts_cancelled_and_still_refuses_junk(pool, agents):
    """Migration 042 widened the status CHECK by one word, not removed it."""
    import asyncpg

    creator = await agents("creator")
    insert = """
        INSERT INTO tasks (task_id, creator_agent_id, requester_agent_id,
                           requester_agent_did, task_type, payload, status)
        VALUES (gen_random_uuid(), $1, $1, $2, 'constraint.test', '{}'::jsonb, $3)
    """
    await pool.execute(insert, creator.agent_id, creator.did, "cancelled")
    for junk in ("failed", "CANCELLED", "anything"):
        with pytest.raises(asyncpg.CheckViolationError):
            await pool.execute(insert, creator.agent_id, creator.did, junk)
