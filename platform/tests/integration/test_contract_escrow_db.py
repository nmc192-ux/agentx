"""
Integration tests: /contracts and /verifications against REAL local Postgres
Sprint 9, S9-6b — the proof behind enabling `contracts` and `verifications`.

Every request goes HTTP → routers/contracts.py → contract_service → Postgres
(and routers/verifications.py → verification_service). Only the JWT check is
replaced (the caller is set per request) and the Redis event bus is silenced;
no money path is mocked. The fixtures are in conftest.py.

What is proven:
  • a contract's budget leaves the creator's own wallet when it is created,
    or there is no contract
  • the escrow leaves exactly once: to the contractor when the creator
    completes a submitted contract, or back to the creator when the creator
    cancels an open one — however often or however concurrently it is tried
  • only the creator assigns, completes and cancels; only the assigned
    contractor submits; nobody acts without a login
  • only the two parties can dispute, and only a contract in flight
  • verifications are advisory: no vote by either party, finalised once, and
    they never move a token
  • tokens are conserved: wallets + escrow never change in total

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from .support import START_BALANCE, Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

BUDGET = 100


# ── DB probes ─────────────────────────────────────────────────────────────────

async def contract_row(pool, contract_id: str):
    return await pool.fetchrow(
        "SELECT status, budget, escrowed_budget, contractor_id FROM contracts WHERE contract_id = $1",
        UUID(contract_id),
    )


async def ledger(pool, contract_id: str, tx_type: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = $2",
        UUID(contract_id), tx_type,
    )


async def count(pool, table: str, contract_id: str) -> int:
    assert table in {"contract_bids", "contract_assignments", "contract_results", "contract_disputes"}
    return await pool.fetchval(
        f"SELECT COUNT(*) FROM {table} WHERE contract_id = $1", UUID(contract_id))


# ── Flow helpers ──────────────────────────────────────────────────────────────

async def open_contract(client, creator: Agent, budget: int = BUDGET) -> str:
    resp = await client.post(
        "/contracts",
        json={"title": "escrow test", "description": "integration", "budget": budget},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["contract_id"]


async def place_bid(client, contract_id: str, bidder: Agent) -> str:
    resp = await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": 10}, headers=bidder.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["bid_id"]


async def assigned_contract(client, creator: Agent, contractor: Agent, budget: int = BUDGET) -> str:
    contract_id = await open_contract(client, creator, budget)
    bid_id = await place_bid(client, contract_id, contractor)
    resp = await client.post(
        f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=creator.headers)
    assert resp.status_code == 200, resp.text
    return contract_id


async def submitted_contract(client, creator: Agent, contractor: Agent, budget: int = BUDGET) -> str:
    contract_id = await assigned_contract(client, creator, contractor, budget)
    resp = await client.post(
        f"/contracts/{contract_id}/result", json={"result_payload": {"done": True}},
        headers=contractor.headers,
    )
    assert resp.status_code == 201, resp.text
    return contract_id


# ── Creating a contract: the caller's own wallet, or no contract ──────────────

async def test_budget_is_escrowed_from_the_callers_own_wallet(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    before = await total_tokens(pool)

    contract_id = await open_contract(client, creator)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["budget"], row["escrowed_budget"]) == ("open", BUDGET, BUDGET)
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await ledger(pool, contract_id, "contract_escrow") == 1
    assert await total_tokens(pool) == before


async def test_unfunded_contract_is_refused_and_leaves_nothing_behind(client, pool, agents):
    """Was soft-fail: the contract was created advertising a budget nobody paid in."""
    no_wallet = await agents("nowallet")
    poor = await agents("poor", BUDGET - 1)
    contracts_before = await pool.fetchval("SELECT COUNT(*) FROM contracts")
    tokens_before = await total_tokens(pool)

    for creator in (no_wallet, poor):
        resp = await client.post(
            "/contracts", json={"title": "t", "description": "d", "budget": BUDGET},
            headers=creator.headers,
        )
        assert resp.status_code == 400, resp.text
        assert "Insufficient funds" in resp.json()["detail"]

    assert await pool.fetchval("SELECT COUNT(*) FROM contracts") == contracts_before
    assert await balance(pool, poor) == BUDGET - 1
    assert await balance(pool, no_wallet) is None
    assert await total_tokens(pool) == tokens_before


async def test_no_write_without_a_login(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor")
    contract_id = await submitted_contract(client, creator, contractor)
    snapshot = dict(await contract_row(pool, contract_id))
    contracts_before = await pool.fetchval("SELECT COUNT(*) FROM contracts")

    anonymous = [
        ("/contracts", {"title": "t", "description": "d", "budget": 1}),
        (f"/contracts/{contract_id}/bid", {"bid_amount": 1}),
        (f"/contracts/{contract_id}/assign", {"bid_id": contract_id}),
        (f"/contracts/{contract_id}/result", {"result_payload": {}}),
        (f"/contracts/{contract_id}/complete", None),
        (f"/contracts/{contract_id}/cancel", None),
        (f"/contracts/{contract_id}/dispute", {"reason": "grief"}),
    ]
    for path, body in anonymous:
        resp = await client.post(path, json=body)
        assert resp.status_code == 401, (path, resp.text)

    assert dict(await contract_row(pool, contract_id)) == snapshot
    assert await pool.fetchval("SELECT COUNT(*) FROM contracts") == contracts_before
    assert await count(pool, "contract_disputes", contract_id) == 0


# ── Bids and assignment ───────────────────────────────────────────────────────

async def test_creator_cannot_bid_on_own_contract(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contract_id = await open_contract(client, creator)

    resp = await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": 1}, headers=creator.headers)
    assert resp.status_code == 403
    assert await count(pool, "contract_bids", contract_id) == 0


async def test_one_bid_per_agent_even_concurrently(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bidder = await agents("bidder")
    contract_id = await open_contract(client, creator)

    responses = await asyncio.gather(*[
        client.post(f"/contracts/{contract_id}/bid", json={"bid_amount": 5}, headers=bidder.headers)
        for _ in range(6)
    ])
    assert sorted(r.status_code for r in responses) == [201] + [409] * 5
    assert await count(pool, "contract_bids", contract_id) == 1


async def test_only_the_creator_can_assign(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    bidder = await agents("bidder")
    attacker = await agents("attacker")
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, bidder)

    for intruder in (attacker, bidder):          # not even the bidder themself
        resp = await client.post(
            f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=intruder.headers)
        assert resp.status_code == 403
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["contractor_id"]) == ("open", None)

    ok = await client.post(
        f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=creator.headers)
    assert ok.status_code == 200
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["contractor_id"]) == ("assigned", bidder.agent_id)

    late = await agents("late")                  # no bids once assigned
    resp = await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": 1}, headers=late.headers)
    assert resp.status_code == 409


async def test_concurrent_assigns_pick_exactly_one_contractor(client, pool, agents):
    """The creator accepts eight different bids at the same moment: one wins."""
    creator = await agents("creator", START_BALANCE)
    contract_id = await open_contract(client, creator)
    bid_ids = [
        await place_bid(client, contract_id, await agents(f"bidder{i}")) for i in range(8)
    ]

    responses = await asyncio.gather(*[
        client.post(f"/contracts/{contract_id}/assign", json={"bid_id": b}, headers=creator.headers)
        for b in bid_ids
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 7

    assignments = await pool.fetch(
        "SELECT contractor_id FROM contract_assignments WHERE contract_id = $1", UUID(contract_id))
    assert len(assignments) == 1
    row = await contract_row(pool, contract_id)
    assert row["contractor_id"] == assignments[0]["contractor_id"]
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM contract_bids WHERE contract_id = $1 AND status = 'accepted'",
        UUID(contract_id)) == 1


# ── Results: the assigned contractor only, once, and it does not pay ──────────

async def test_only_the_assigned_contractor_submits_and_it_pays_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    attacker = await agents("attacker", 0)
    contract_id = await assigned_contract(client, creator, contractor)

    for intruder in (attacker, creator):
        resp = await client.post(
            f"/contracts/{contract_id}/result", json={"result_payload": {}}, headers=intruder.headers)
        assert resp.status_code == 403
    assert (await contract_row(pool, contract_id))["status"] == "assigned"

    responses = await asyncio.gather(*[
        client.post(
            f"/contracts/{contract_id}/result", json={"result_payload": {"n": n}},
            headers=contractor.headers,
        )
        for n in range(8)
    ])
    assert sorted(r.status_code for r in responses) == [201] + [409] * 7
    assert await count(pool, "contract_results", contract_id) == 1

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("submitted", BUDGET)
    assert await balance(pool, contractor) == 0          # only /complete pays


# ── Completing: creator only, pays the contractor once ────────────────────────

async def test_only_the_creator_completes_and_the_contractor_is_paid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor")              # no wallet yet
    attacker = await agents("attacker", 0)
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)

    # An outsider, and the contractor trying to release the escrow to themself.
    for intruder in (attacker, contractor):
        resp = await client.post(f"/contracts/{contract_id}/complete", headers=intruder.headers)
        assert resp.status_code == 403, resp.text
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("submitted", BUDGET)
    assert await balance(pool, contractor) is None
    assert await ledger(pool, contract_id, "contract_release") == 0

    ok = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
    assert ok.status_code == 200, ok.text
    assert (ok.json()["status"], ok.json()["escrowed_budget"]) == ("completed", 0)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
    # The contractor had no wallet: one is created holding exactly the escrow.
    assert await balance(pool, contractor) == BUDGET
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await balance(pool, attacker) == 0
    assert await ledger(pool, contract_id, "contract_release") == 1
    assert await total_tokens(pool) == before


async def test_cannot_complete_before_a_result_is_submitted(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    open_id = await open_contract(client, creator)
    assigned_id = await assigned_contract(client, creator, contractor)

    for contract_id in (open_id, assigned_id):
        resp = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
        assert resp.status_code == 409
        assert (await contract_row(pool, contract_id))["escrowed_budget"] == BUDGET
    assert await balance(pool, contractor) == 0


async def test_completing_twice_pays_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    contract_id = await submitted_contract(client, creator, contractor)

    first = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
    assert first.status_code == 200
    for _ in range(3):
        again = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
        assert again.status_code == 409

    assert await balance(pool, contractor) == BUDGET
    assert await ledger(pool, contract_id, "contract_release") == 1


async def test_concurrent_completes_pay_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)

    responses = await asyncio.gather(*[
        client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
        for _ in range(12)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 11, codes

    assert await balance(pool, contractor) == BUDGET
    assert await ledger(pool, contract_id, "contract_release") == 1
    assert (await contract_row(pool, contract_id))["escrowed_budget"] == 0
    assert await total_tokens(pool) == before


async def test_escrow_settlement_itself_is_locked(client, pool, agents):
    """Service level: even called directly and concurrently (bypassing every
    status guard), the escrow is paid out once — release and refund race."""
    from src.database import transaction
    from src.services import contract_service

    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)
    creator_after_escrow = await balance(pool, creator)

    async def settle(payee: Agent, tx_type: str) -> int:
        async with transaction() as conn:
            return await contract_service._settle_contract_escrow(
                conn, UUID(contract_id), payee.agent_id, tx_type)

    paid = await asyncio.gather(
        *[settle(contractor, "contract_release") for _ in range(6)],
        *[settle(creator, "contract_refund") for _ in range(6)],
    )
    assert sorted(paid) == [0] * 11 + [BUDGET]

    gained = (await balance(pool, contractor)) + (await balance(pool, creator)) - creator_after_escrow
    assert gained == BUDGET
    assert (await contract_row(pool, contract_id))["escrowed_budget"] == 0
    assert await total_tokens(pool) == before


# ── Cancelling: creator only, open contracts only, refunds once ───────────────

async def test_creator_cancels_an_open_contract_and_is_refunded_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    attacker = await agents("attacker", 0)
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bidder = await agents("bidder", 0)
    await place_bid(client, contract_id, bidder)

    for intruder in (attacker, bidder):
        resp = await client.post(f"/contracts/{contract_id}/cancel", headers=intruder.headers)
        assert resp.status_code == 403
    assert await balance(pool, creator) == START_BALANCE - BUDGET

    responses = await asyncio.gather(*[
        client.post(f"/contracts/{contract_id}/cancel", headers=creator.headers)
        for _ in range(8)
    ])
    assert sorted(r.status_code for r in responses) == [200] + [409] * 7

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, attacker) == 0 and await balance(pool, bidder) == 0
    assert await ledger(pool, contract_id, "contract_refund") == 1
    assert await total_tokens(pool) == before

    # A cancelled contract is dead: no bids, no assignment.
    resp = await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": 1}, headers=attacker.headers)
    assert resp.status_code == 409


async def test_creator_cannot_pull_the_escrow_back_once_assigned(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    assigned_id = await assigned_contract(client, creator, contractor)
    submitted_id = await submitted_contract(client, creator, contractor)

    for contract_id in (assigned_id, submitted_id):
        resp = await client.post(f"/contracts/{contract_id}/cancel", headers=creator.headers)
        assert resp.status_code == 409
        assert (await contract_row(pool, contract_id))["escrowed_budget"] == BUDGET
    assert await balance(pool, creator) == START_BALANCE - 2 * BUDGET


async def test_cancel_racing_assign_has_exactly_one_winner(client, pool, agents):
    """Cancel and assign at the same moment: either the creator is refunded and
    nobody is assigned, or a contractor is assigned and the escrow stays put."""
    for _ in range(5):
        creator = await agents("creator", START_BALANCE)
        bidder = await agents("bidder", 0)
        before = await total_tokens(pool)
        contract_id = await open_contract(client, creator)
        bid_id = await place_bid(client, contract_id, bidder)

        cancel, assign = await asyncio.gather(
            client.post(f"/contracts/{contract_id}/cancel", headers=creator.headers),
            client.post(
                f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=creator.headers),
        )
        assert sorted([cancel.status_code, assign.status_code]) == [200, 409]

        row = await contract_row(pool, contract_id)
        if cancel.status_code == 200:
            assert (row["status"], row["escrowed_budget"], row["contractor_id"]) == ("cancelled", 0, None)
            assert await balance(pool, creator) == START_BALANCE
            assert await count(pool, "contract_assignments", contract_id) == 0
        else:
            assert (row["status"], row["escrowed_budget"]) == ("assigned", BUDGET)
            assert await balance(pool, creator) == START_BALANCE - BUDGET
        assert await total_tokens(pool) == before


# ── Disputes: the two parties only, contracts in flight only ──────────────────

async def test_outsider_cannot_dispute_any_contract(client, pool, agents):
    """The hole S9-6 found: any agent could freeze anyone's contract for good."""
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    attacker = await agents("attacker")
    contracts = {
        "open": await open_contract(client, creator),
        "assigned": await assigned_contract(client, creator, contractor),
        "submitted": await submitted_contract(client, creator, contractor),
    }

    for status, contract_id in contracts.items():
        resp = await client.post(
            f"/contracts/{contract_id}/dispute", json={"reason": "grief"}, headers=attacker.headers)
        assert resp.status_code == 403, (status, resp.text)
        assert (await contract_row(pool, contract_id))["status"] == status
        assert await count(pool, "contract_disputes", contract_id) == 0

    # …so the creator can still complete the submitted one.
    ok = await client.post(f"/contracts/{contracts['submitted']}/complete", headers=creator.headers)
    assert ok.status_code == 200
    assert await balance(pool, contractor) == BUDGET


async def test_parties_can_dispute_only_a_contract_in_flight(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)

    open_id = await open_contract(client, creator)
    resp = await client.post(
        f"/contracts/{open_id}/dispute", json={"reason": "early"}, headers=creator.headers)
    assert resp.status_code == 409
    assert (await contract_row(pool, open_id))["status"] == "open"

    done_id = await submitted_contract(client, creator, contractor)
    assert (await client.post(
        f"/contracts/{done_id}/complete", headers=creator.headers)).status_code == 200
    for party in (creator, contractor):
        resp = await client.post(
            f"/contracts/{done_id}/dispute", json={"reason": "late"}, headers=party.headers)
        assert resp.status_code == 409
    assert (await contract_row(pool, done_id))["status"] == "completed"
    assert await count(pool, "contract_disputes", done_id) == 0


async def test_a_dispute_freezes_the_escrow_where_it_is(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)

    responses = await asyncio.gather(*[
        client.post(
            f"/contracts/{contract_id}/dispute", json={"reason": f"r{n}"}, headers=party.headers)
        for n, party in enumerate([creator, contractor] * 3)
    ])
    assert sorted(r.status_code for r in responses) == [201] + [409] * 5
    assert await count(pool, "contract_disputes", contract_id) == 1

    # Nothing moves the escrow of a disputed contract, in either direction.
    for path, caller, body in (
        ("complete", creator, None),
        ("cancel", creator, None),
        ("result", contractor, {"result_payload": {}}),
    ):
        resp = await client.post(f"/contracts/{contract_id}/{path}", json=body, headers=caller.headers)
        assert resp.status_code == 409, (path, resp.text)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
    assert await balance(pool, contractor) == 0
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await total_tokens(pool) == before


async def test_complete_racing_dispute_has_exactly_one_winner(client, pool, agents):
    for _ in range(5):
        creator = await agents("creator", START_BALANCE)
        contractor = await agents("contractor", 0)
        before = await total_tokens(pool)
        contract_id = await submitted_contract(client, creator, contractor)

        complete, dispute = await asyncio.gather(
            client.post(f"/contracts/{contract_id}/complete", headers=creator.headers),
            client.post(
                f"/contracts/{contract_id}/dispute", json={"reason": "race"},
                headers=contractor.headers),
        )
        assert sorted([complete.status_code, dispute.status_code]) in ([200, 409], [201, 409])

        row = await contract_row(pool, contract_id)
        if complete.status_code == 200:
            assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
            assert await balance(pool, contractor) == BUDGET
            assert await count(pool, "contract_disputes", contract_id) == 0
        else:
            assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
            assert await balance(pool, contractor) == 0
        assert await total_tokens(pool) == before


# ── Verifications: advisory, neither party votes, finalised once ──────────────

async def open_verification(client, pool, creator: Agent, contract_id: str) -> str:
    result_id = await pool.fetchval(
        "SELECT result_id FROM contract_results WHERE contract_id = $1", UUID(contract_id))
    resp = await client.post(
        "/verifications",
        json={"contract_id": contract_id, "result_id": str(result_id)},
        headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "active"
    return resp.json()["verification_id"]


async def verification_row(pool, verification_id: str):
    return await pool.fetchrow(
        "SELECT status, vote_count, yes_power, no_power FROM verifications WHERE verification_id = $1",
        UUID(verification_id),
    )


async def test_only_the_contract_creator_requests_a_verification(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    attacker = await agents("attacker")
    contract_id = await submitted_contract(client, creator, contractor)
    result_id = await pool.fetchval(
        "SELECT result_id FROM contract_results WHERE contract_id = $1", UUID(contract_id))
    body = {"contract_id": contract_id, "result_id": str(result_id)}

    assert (await client.post("/verifications", json=body)).status_code == 401
    for intruder in (attacker, contractor):
        resp = await client.post("/verifications", json=body, headers=intruder.headers)
        assert resp.status_code == 400
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM verifications WHERE contract_id = $1", UUID(contract_id)) == 0


async def test_neither_party_to_the_contract_can_vote(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    contract_id = await submitted_contract(client, creator, contractor)
    verification_id = await open_verification(client, pool, creator, contract_id)

    for party in (creator, contractor):
        resp = await client.post(
            f"/verifications/{verification_id}/vote", json={"vote": "approve"},
            headers=party.headers,
        )
        assert resp.status_code == 403, resp.text
    anon = await client.post(f"/verifications/{verification_id}/vote", json={"vote": "approve"})
    assert anon.status_code == 401

    row = await verification_row(pool, verification_id)
    assert (row["status"], row["vote_count"]) == ("active", 0)


async def test_verification_is_finalised_once_and_moves_no_tokens(client, pool, agents):
    """Six verifiers vote at the same moment on a verification that needs three.
    Exactly three votes are recorded, none lands after it is finalised, and a
    reward pool that nothing funded is not paid out."""
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    verifiers = [await agents(f"verifier{i}", 0) for i in range(6)]
    contract_id = await submitted_contract(client, creator, contractor)
    verification_id = await open_verification(client, pool, creator, contract_id)
    # Only a direct database write can set a pool; the API always creates 0.
    await pool.execute(
        "UPDATE verifications SET reward_pool = 900 WHERE verification_id = $1",
        UUID(verification_id),
    )
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[
        client.post(
            f"/verifications/{verification_id}/vote", json={"vote": "approve"}, headers=v.headers)
        for v in verifiers
    ])
    assert sorted(r.status_code for r in responses) == [201] * 3 + [400] * 3

    row = await verification_row(pool, verification_id)
    assert (row["status"], row["vote_count"]) == ("verified", 3)
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM verification_votes WHERE verification_id = $1",
        UUID(verification_id)) == 3
    assert row["yes_power"] == 3.0 and row["no_power"] == 0.0

    # No tokens from nothing.
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM verification_rewards WHERE verification_id = $1",
        UUID(verification_id)) == 0
    for v in verifiers:
        assert await balance(pool, v) == 0
    assert await total_tokens(pool) == before

    # Advisory: the contract is untouched; the creator still decides.
    contract = await contract_row(pool, contract_id)
    assert (contract["status"], contract["escrowed_budget"]) == ("submitted", BUDGET)
    assert await balance(pool, contractor) == 0


async def test_one_vote_per_verifier(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    verifier = await agents("verifier")
    contract_id = await submitted_contract(client, creator, contractor)
    verification_id = await open_verification(client, pool, creator, contract_id)

    responses = await asyncio.gather(*[
        client.post(
            f"/verifications/{verification_id}/vote", json={"vote": "reject"},
            headers=verifier.headers)
        for _ in range(6)
    ])
    assert sorted(r.status_code for r in responses) == [201] + [400] * 5
    row = await verification_row(pool, verification_id)
    assert (row["status"], row["vote_count"], row["no_power"]) == ("active", 1, 1.0)
