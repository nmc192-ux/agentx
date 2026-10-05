"""
Integration tests: the `agent_economy` router against REAL local Postgres
Sprint 9, S9-7c — the proof behind moving `agent_economy` out of Tier A.

Every request goes HTTP → routers/agent_economy.py → service → Postgres. Only
the JWT check is replaced (the caller is set per request) and the Redis event
bus is silenced; no money path is mocked. The fixtures are in conftest.py.

What is proven:
  • `POST /markets/bounties/auto` — the router was Tier A because it once took
    the paying agent's DID from the request body with no login. Now: no login
    → 401; a body that names somebody else is ignored (the caller pays, from
    the caller's own wallet); a pool the caller cannot cover → no bounty
  • `POST /contracts/{id}/subcontract` — only the parent's assigned contractor
    (403 otherwise), only while the parent is in flight (409 otherwise); the
    child's budget is escrowed from the caller's own wallet or there is no
    child; the parent reference cannot be forged through the payload
  • the parent row is locked while the child is created: a sub-contract cannot
    slip in beside a parent that is being completed at the same moment
  • tokens are conserved throughout

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_contract_escrow_db import (
    BUDGET,
    assigned_contract,
    contract_row,
    ledger,
    open_contract,
    submitted_contract,
)

pytestmark = pytest.mark.integration   # skipped unless --db is given

POOL = 100
CHILD_BUDGET = 40


# ── DB probes ─────────────────────────────────────────────────────────────────

async def bounty_count(pool) -> int:
    return await pool.fetchval("SELECT COUNT(*) FROM capability_bounties")


async def children_of(pool, parent_id: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM contracts "
        "WHERE contract_type = 'subcontract' AND payload->>'parent_contract_id' = $1",
        parent_id,
    )


async def spawn(client, parent_id: str, caller: Agent, budget: int = CHILD_BUDGET, **extra):
    return await client.post(
        f"/contracts/{parent_id}/subcontract",
        json={"title": "delegated", "description": "part of the work", "budget": budget, **extra},
        headers=caller.headers,
    )


# ── POST /markets/bounties/auto ───────────────────────────────────────────────

async def test_auto_bounty_needs_a_login_and_creates_nothing_without_one(client, pool, agents):
    victim = await agents("victim", START_BALANCE)
    bounties_before = await bounty_count(pool)

    # The old hole: no token, the paying agent named in the body.
    resp = await client.post(
        "/markets/bounties/auto",
        json={"agent_did": victim.did, "capability": "forecast", "reward_pool": POOL},
    )

    assert resp.status_code == 401, resp.text
    assert await bounty_count(pool) == bounties_before
    assert await balance(pool, victim) == START_BALANCE


async def test_auto_bounty_is_paid_by_the_caller_whatever_the_body_says(client, pool, agents):
    caller = await agents("caller", START_BALANCE)
    victim = await agents("victim", START_BALANCE)
    before = await total_tokens(pool)

    resp = await client.post(
        "/markets/bounties/auto",
        json={"capability": "forecast", "reward_pool": POOL,
              "agent_did": victim.did, "creator_did": victim.did,
              "creator_id": str(victim.agent_id)},
        headers=caller.headers,
    )

    assert resp.status_code == 201, resp.text
    bounty = resp.json()
    assert bounty["creator_did"] == caller.did
    assert bounty["status"] == "open" and bounty["reward_pool"] == POOL
    row = await pool.fetchrow(
        "SELECT creator_did, creator_id FROM capability_bounties WHERE bounty_id = $1",
        UUID(bounty["bounty_id"]),
    )
    assert (row["creator_did"], row["creator_id"]) == (caller.did, caller.agent_id)
    assert await balance(pool, caller) == START_BALANCE - POOL
    assert await balance(pool, victim) == START_BALANCE
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = 'bounty_escrow'",
        UUID(bounty["bounty_id"]),
    ) == 1
    assert await total_tokens(pool) == before


async def test_unfunded_auto_bounty_is_refused_and_leaves_nothing_behind(client, pool, agents):
    no_wallet = await agents("nowallet")
    poor = await agents("poor", POOL - 1)
    before = await total_tokens(pool)
    bounties_before = await bounty_count(pool)

    for caller in (no_wallet, poor):
        resp = await client.post(
            "/markets/bounties/auto",
            json={"capability": "forecast", "reward_pool": POOL},
            headers=caller.headers,
        )
        assert resp.status_code == 400, resp.text
        assert "Insufficient funds" in resp.json()["detail"]

    assert await bounty_count(pool) == bounties_before
    assert await balance(pool, poor) == POOL - 1
    assert await balance(pool, no_wallet) is None      # no wallet appeared
    assert await total_tokens(pool) == before


async def test_auto_bounty_is_an_ordinary_bounty_the_creator_can_cancel(client, pool, agents):
    """It goes through the same service as POST /markets/bounties, so the
    S9-6c rules hold: the creator gets the pool back, once."""
    caller = await agents("caller", START_BALANCE)
    resp = await client.post(
        "/markets/bounties/auto", json={"capability": "c", "reward_pool": POOL},
        headers=caller.headers,
    )
    bounty_id = resp.json()["bounty_id"]

    first = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=caller.headers)
    second = await client.post(f"/markets/bounties/{bounty_id}/cancel", headers=caller.headers)

    assert (first.status_code, second.status_code) == (200, 409)
    assert await balance(pool, caller) == START_BALANCE


# ── POST /contracts/{id}/subcontract ──────────────────────────────────────────

async def test_contractor_spawns_a_child_paid_from_their_own_wallet(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    parent_id = await assigned_contract(client, creator, contractor)
    before = await total_tokens(pool)

    resp = await spawn(client, parent_id, contractor, payload={"note": "half of it"})

    assert resp.status_code == 201, resp.text
    child = resp.json()
    assert child["creator_did"] == contractor.did
    assert child["contract_type"] == "subcontract" and child["status"] == "open"
    assert child["parent_contract_id"] == parent_id
    assert child["payload"] == {"note": "half of it", "parent_contract_id": parent_id}
    assert (child["budget"], child["escrowed_budget"]) == (CHILD_BUDGET, CHILD_BUDGET)
    # The child's budget came out of the contractor's wallet; the parent's
    # escrow and the creator's wallet did not move.
    assert await balance(pool, contractor) == START_BALANCE - CHILD_BUDGET
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert (await contract_row(pool, parent_id))["escrowed_budget"] == BUDGET
    assert await ledger(pool, child["contract_id"], "contract_escrow") == 1
    assert await total_tokens(pool) == before


async def test_a_submitted_parent_can_still_be_subcontracted(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    parent_id = await submitted_contract(client, creator, contractor)

    resp = await spawn(client, parent_id, contractor)

    assert resp.status_code == 201, resp.text


async def test_payload_cannot_point_the_child_at_another_parent(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    parent_id = await assigned_contract(client, creator, contractor)
    other_id = await open_contract(client, creator)

    resp = await spawn(client, parent_id, contractor, payload={"parent_contract_id": other_id})

    assert resp.status_code == 201, resp.text
    assert resp.json()["payload"]["parent_contract_id"] == parent_id
    assert await children_of(pool, parent_id) == 1
    assert await children_of(pool, other_id) == 0


async def test_only_the_assigned_contractor_can_subcontract(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    outsider = await agents("outsider", START_BALANCE)
    parent_id = await assigned_contract(client, creator, contractor)
    before = await total_tokens(pool)

    anonymous = await client.post(
        f"/contracts/{parent_id}/subcontract",
        json={"title": "t", "description": "d", "budget": CHILD_BUDGET},
    )
    assert anonymous.status_code == 401, anonymous.text
    for caller in (outsider, creator):
        resp = await spawn(client, parent_id, caller)
        assert resp.status_code == 403, resp.text

    assert await children_of(pool, parent_id) == 0
    assert await balance(pool, outsider) == START_BALANCE
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await total_tokens(pool) == before


async def test_nobody_can_subcontract_an_open_contract(client, pool, agents):
    """An open contract has no contractor: not even its creator is one."""
    creator = await agents("creator", START_BALANCE)
    bidder = await agents("bidder", START_BALANCE)
    parent_id = await open_contract(client, creator)

    for caller in (creator, bidder):
        resp = await spawn(client, parent_id, caller)
        assert resp.status_code == 403, resp.text

    assert await children_of(pool, parent_id) == 0


async def test_a_finished_or_disputed_parent_cannot_be_subcontracted(client, pool, agents):
    creator = await agents("creator", 10 * START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)

    completed = await submitted_contract(client, creator, contractor)
    resp = await client.post(f"/contracts/{completed}/complete", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    disputed = await assigned_contract(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{disputed}/dispute", json={"reason": "integration test dispute"},
        headers=contractor.headers,
    )
    assert resp.status_code == 201, resp.text
    before = await total_tokens(pool)
    wallet_before = await balance(pool, contractor)

    for parent_id in (completed, disputed):
        resp = await spawn(client, parent_id, contractor)
        assert resp.status_code == 409, resp.text
        assert await children_of(pool, parent_id) == 0

    assert await balance(pool, contractor) == wallet_before
    assert await total_tokens(pool) == before


async def test_unfunded_subcontract_is_refused_and_leaves_nothing_behind(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    poor = await agents("poor", CHILD_BUDGET - 1)
    no_wallet = await agents("nowallet")
    before = await total_tokens(pool)

    for contractor in (poor, no_wallet):
        parent_id = await assigned_contract(client, creator, contractor)
        resp = await spawn(client, parent_id, contractor)
        assert resp.status_code == 400, resp.text
        assert "Insufficient funds" in resp.json()["detail"]
        assert await children_of(pool, parent_id) == 0

    assert await balance(pool, poor) == CHILD_BUDGET - 1
    assert await balance(pool, no_wallet) is None
    assert await total_tokens(pool) == before


async def test_missing_parent_is_a_404(client, pool, agents):
    contractor = await agents("contractor", START_BALANCE)

    resp = await spawn(client, str(uuid4()), contractor)

    assert resp.status_code == 404, resp.text
    assert await balance(pool, contractor) == START_BALANCE


async def test_oversized_amounts_are_refused_before_the_database(client, pool, agents):
    """A number beyond the BIGINT column used to reach the driver (a 500)."""
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    parent_id = await assigned_contract(client, creator, contractor)

    too_big = 2**63
    sub = await spawn(client, parent_id, contractor, budget=too_big)
    contract = await client.post(
        "/contracts", json={"title": "t", "description": "d", "budget": too_big},
        headers=creator.headers,
    )
    bounty = await client.post(
        "/markets/bounties/auto", json={"capability": "c", "reward_pool": too_big},
        headers=creator.headers,
    )

    assert (sub.status_code, contract.status_code, bounty.status_code) == (422, 422, 422)


# ── The parent row is locked while the child is created ───────────────────────

async def test_subcontract_waits_for_a_locked_parent_and_sees_its_new_status(client, pool, agents):
    """Hold the parent's row lock (as a completing transaction does), start a
    sub-contract, then finish the parent. The sub-contract must wait for the
    lock and then be refused: it never sees the stale 'submitted' status."""
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    parent_id = await submitted_contract(client, creator, contractor)
    before = await total_tokens(pool)

    async with pool.acquire() as holder:
        tx = holder.transaction()
        await tx.start()
        await holder.fetchval(
            "SELECT status FROM contracts WHERE contract_id = $1 FOR UPDATE", UUID(parent_id))

        pending = asyncio.create_task(spawn(client, parent_id, contractor))
        done, _ = await asyncio.wait({pending}, timeout=0.5)
        assert not done, "the sub-contract did not wait for the parent's row lock"

        await holder.execute(
            "UPDATE contracts SET status = 'completed' WHERE contract_id = $1", UUID(parent_id))
        await tx.commit()

    resp = await asyncio.wait_for(pending, timeout=10)
    assert resp.status_code == 409, resp.text
    assert await children_of(pool, parent_id) == 0
    assert await balance(pool, contractor) == START_BALANCE
    assert await total_tokens(pool) == before


async def test_subcontract_racing_complete_never_leaves_a_half_made_child(client, pool, agents):
    """Complete and sub-contract at the same moment, many times. Whichever
    wins, the books balance: a child exists only with its budget escrowed
    from the contractor, and the contractor is paid the parent's budget once."""
    creator = await agents("creator", 20 * START_BALANCE)
    contractor = await agents("contractor", START_BALANCE)
    before = await total_tokens(pool)
    children = 0

    for _ in range(8):
        parent_id = await submitted_contract(client, creator, contractor)
        complete, sub = await asyncio.gather(
            client.post(f"/contracts/{parent_id}/complete", headers=creator.headers),
            spawn(client, parent_id, contractor),
        )
        assert complete.status_code == 200, complete.text
        assert sub.status_code in (201, 409), sub.text
        made = await children_of(pool, parent_id)
        assert made == (1 if sub.status_code == 201 else 0)
        children += made

    # Paid 8 parent budgets, escrowed one child budget per child made.
    assert await balance(pool, contractor) == START_BALANCE + 8 * BUDGET - children * CHILD_BUDGET
    assert await total_tokens(pool) == before


# ── Sign-up tells the truth about the wallet (S9-7c (f)) ──────────────────────

async def test_onboarding_reports_an_empty_wallet_and_creates_no_tokens(client, pool, monkeypatch):
    """/onboard used to answer "wallet_balance: 100" and send the agent to a
    route that did not exist. The 100 is a legacy points row, not tokens."""
    from unittest.mock import AsyncMock

    from src.middleware.rate_limits import limiter
    from src.services import onboard_service
    monkeypatch.setattr(onboard_service, "publish_event", AsyncMock(return_value=None))
    limiter.reset()
    before = await total_tokens(pool)
    wallets_before = await pool.fetchval("SELECT COUNT(*) FROM wallets")

    resp = await client.post("/onboard", json={"name": f"newcomer-{uuid4().hex[:10]}"})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    did = body["agent_did"]
    assert (body["wallet_balance"], body["welcome_points"]) == (0, 100)
    # Nothing spendable was created …
    assert await pool.fetchval("SELECT COUNT(*) FROM wallets") == wallets_before
    assert await total_tokens(pool) == before
    # … the bonus is only the legacy points row.
    assert await pool.fetchval(
        "SELECT balance FROM token_balances WHERE agent_did = $1 AND token_type = 'WORK'", did,
    ) == 100
    # The route the response points at exists and says so plainly.
    step = next(s for s in body["next_steps"] if "/wallets/by-did" in s)
    assert step.endswith(f"GET /wallets/by-did?agent_did={did}")
    check = await client.get("/wallets/by-did", params={"agent_did": did})
    assert check.status_code == 404
    assert "POST /wallets" in check.json()["detail"]


async def test_wallet_opened_by_its_owner_starts_at_zero_and_is_readable_by_did(client, pool, agents):
    newcomer = await agents("newcomer")
    before = await total_tokens(pool)

    opened = await client.post("/wallets", json={}, headers=newcomer.headers)
    by_did = await client.get("/wallets/by-did", params={"agent_did": newcomer.did})
    by_id = await client.get(f"/wallets/{newcomer.agent_id}")

    assert opened.status_code == 200, opened.text
    assert by_did.status_code == 200, by_did.text
    assert by_did.json() == by_id.json()
    assert by_did.json()["balance"] == 0
    assert await total_tokens(pool) == before
