"""
Integration tests: the accepted bid is the price, against REAL local Postgres.
Sprint 12, S12-5 (decision D4b).

Every request goes HTTP → routers/contracts.py → contract_service → Postgres.
Only the JWT check is replaced (the caller is set per request) and the Redis
event bus is silenced; no money path is mocked. The fixtures are in
conftest.py.

What is proven:
  • a bid above the budget is refused (422) and leaves no bid behind
  • accepting a bid returns the escrow above it to the creator, once, in the
    assigning transaction; the escrow left is exactly the bid
  • every way out then moves the bid and nothing more: complete, automatic
    release, a FOUNDER's ruling either way, reclaim after a missed deadline
  • the amount comes from the bid row: nothing in the assign request, and no
    other contract's bid, changes it
  • an over-budget bid already in the table cannot be accepted; nothing is
    ever taken from the creator's wallet to cover a bid
  • only the creator triggers the refund, and only they receive it
  • concurrent assigns refund once; a failure rolls everything back; tokens
    are conserved

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.services import contract_service

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_contract_deadline_db import age_delivery, deliver, move_deadline, reclaim
from .test_contract_escrow_db import BUDGET, contract_row, count, ledger, open_contract, place_bid

pytestmark = pytest.mark.integration   # skipped unless --db is given

BID = 60
REMAINDER = BUDGET - BID
BID_REFUND_TX = "contract_bid_refund"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def bid(client, contract_id: str, bidder: Agent, amount):
    return await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": amount}, headers=bidder.headers)


async def assign(client, contract_id: str, bid_id: str, caller: Agent | None, **extra):
    return await client.post(
        f"/contracts/{contract_id}/assign", json={"bid_id": bid_id, **extra},
        headers=caller.headers if caller else {},
    )


async def assigned_at(client, creator: Agent, contractor: Agent, amount: int = BID) -> str:
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, amount)
    resp = await assign(client, contract_id, bid_id, creator)
    assert resp.status_code == 200, resp.text
    return contract_id


async def submitted_at(client, creator: Agent, contractor: Agent, amount: int = BID) -> str:
    contract_id = await assigned_at(client, creator, contractor, amount)
    assert (await deliver(client, contract_id, contractor)).status_code == 201
    return contract_id


async def force_bid(pool, contract_id: str, bidder: Agent, amount: int) -> str:
    """A bid row written straight into the table, as if it predated the rule."""
    return str(await pool.fetchval(
        "INSERT INTO contract_bids (contract_id, bidder_did, bidder_id, bid_amount) "
        "VALUES ($1, $2, $3, $4) RETURNING bid_id",
        UUID(contract_id), bidder.did, bidder.agent_id, amount,
    ))


async def assert_still_open(pool, contract_id: str, creator: Agent, contractor: Agent):
    """Nothing has moved: whole budget held, nobody assigned, nobody refunded."""
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"], row["contractor_id"]) == ("open", BUDGET, None)
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await balance(pool, contractor) == 0
    assert await ledger(pool, contract_id, BID_REFUND_TX) == 0
    assert await count(pool, "contract_assignments", contract_id) == 0


@pytest.fixture
async def parties(agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    return creator, contractor


# ── Bids above the budget are refused ─────────────────────────────────────────

async def test_a_bid_above_the_budget_is_refused(client, pool, parties):
    creator, contractor = parties
    contract_id = await open_contract(client, creator)

    for amount in (BUDGET + 1, BUDGET * 10, 2**63 - 1):
        resp = await bid(client, contract_id, contractor, amount)
        assert resp.status_code == 422, (amount, resp.text)
    assert "budget" in resp.json()["detail"]
    assert await count(pool, "contract_bids", contract_id) == 0

    # The refusal did not use up the agent's one bid.
    assert (await bid(client, contract_id, contractor, BUDGET)).status_code == 201


@pytest.mark.parametrize("amount", [0, -1, -BUDGET, 2**63, 59.5, "60 tokens", None])
async def test_a_bid_that_is_not_a_positive_whole_amount_is_refused(client, pool, parties, amount):
    creator, contractor = parties
    contract_id = await open_contract(client, creator)

    assert (await bid(client, contract_id, contractor, amount)).status_code == 422
    assert await count(pool, "contract_bids", contract_id) == 0


async def test_a_bid_equal_to_the_budget_is_accepted_and_refunds_nothing(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await assigned_at(client, creator, contractor, BUDGET)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("assigned", BUDGET)
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await ledger(pool, contract_id, BID_REFUND_TX) == 0
    assert await total_tokens(pool) == before


# ── Accepting a bid refunds the rest ──────────────────────────────────────────

async def test_accepting_a_bid_returns_the_rest_to_the_creator(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    resp = await assign(client, contract_id, bid_id, creator)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["budget"], body["escrowed_budget"]) == ("assigned", BUDGET, BID)
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("assigned", BID)
    assert await balance(pool, creator) == START_BALANCE - BID
    assert await balance(pool, contractor) == 0            # accepting pays nobody
    entry = await pool.fetchrow(
        "SELECT t.amount, t.from_wallet, w.agent_id FROM transactions t "
        "JOIN wallets w ON w.wallet_id = t.to_wallet "
        "WHERE t.related_id = $1 AND t.type = $2",
        UUID(contract_id), BID_REFUND_TX,
    )
    assert (entry["amount"], entry["from_wallet"], entry["agent_id"]) == (
        REMAINDER, None, creator.agent_id)
    assert await total_tokens(pool) == before


async def test_the_contractor_is_paid_the_bid_on_completion(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_at(client, creator, contractor)

    resp = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["escrowed_budget"]) == ("completed", 0)
    assert await balance(pool, contractor) == BID
    assert await balance(pool, creator) == START_BALANCE - BID
    paid = await pool.fetchval(
        "SELECT amount FROM transactions WHERE related_id = $1 AND type = 'contract_release'",
        UUID(contract_id))
    assert paid == BID
    assert await ledger(pool, contract_id, BID_REFUND_TX) == 1
    assert await total_tokens(pool) == before

    # Completing again moves nothing more.
    again = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
    assert again.status_code == 409
    assert await balance(pool, contractor) == BID
    assert await balance(pool, creator) == START_BALANCE - BID


async def test_the_ledger_adds_up_to_the_budget(client, pool, parties):
    """Escrowed in = refunded at acceptance + paid at completion."""
    creator, contractor = parties
    contract_id = await submitted_at(client, creator, contractor)
    await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)

    rows = await pool.fetch(
        "SELECT type, amount FROM transactions WHERE related_id = $1 ORDER BY timestamp",
        UUID(contract_id))
    assert sorted((r["type"], r["amount"]) for r in rows) == sorted([
        ("contract_escrow", BUDGET), (BID_REFUND_TX, REMAINDER), ("contract_release", BID),
    ])


# ── Every other way out moves the bid, not the budget ─────────────────────────

async def test_automatic_release_pays_the_bid(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_at(client, creator, contractor)
    await age_delivery(pool, contract_id, "7 days 1 minute")

    assert await contract_service.release_overdue_contract(UUID(contract_id)) == BID

    assert await balance(pool, contractor) == BID
    assert await balance(pool, creator) == START_BALANCE - BID
    assert await total_tokens(pool) == before


@pytest.mark.parametrize("outcome, creator_ends, contractor_ends", [
    ("pay_contractor", START_BALANCE - BID, BID),
    ("refund_creator", START_BALANCE, 0),
])
async def test_a_founders_ruling_moves_the_bid(
    client, pool, parties, agents, outcome, creator_ends, contractor_ends,
):
    creator, contractor = parties
    founder = await agents("founder", role="FOUNDER")
    before = await total_tokens(pool)
    contract_id = await submitted_at(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{contract_id}/dispute", json={"reason": "bad"}, headers=creator.headers)
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        f"/contracts/{contract_id}/settle", json={"outcome": outcome, "note": "ruled"},
        headers=founder.headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == BID
    assert await balance(pool, creator) == creator_ends
    assert await balance(pool, contractor) == contractor_ends
    assert (await contract_row(pool, contract_id))["escrowed_budget"] == 0
    assert await total_tokens(pool) == before


async def test_reclaim_after_a_missed_deadline_returns_the_bid(client, pool, parties):
    """The creator ends whole: the rest came back at acceptance, the bid now."""
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await assigned_at(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    resp = await reclaim(client, contract_id, creator)

    assert resp.status_code == 200, resp.text
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, contractor) == 0
    refunded = await pool.fetchval(
        "SELECT amount FROM transactions WHERE related_id = $1 "
        "AND type = 'contract_deadline_refund'", UUID(contract_id))
    assert refunded == BID
    assert await total_tokens(pool) == before


# ── The amount comes from the bid row, nothing else ───────────────────────────

async def test_the_assign_request_cannot_name_the_amount(client, pool, parties):
    creator, contractor = parties
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    resp = await assign(
        client, contract_id, bid_id, creator,
        bid_amount=1, amount=1, escrowed_budget=0, budget=1, refund=BUDGET,
        contractor_did=creator.did,
    )

    assert resp.status_code == 200, resp.text
    row = await contract_row(pool, contract_id)
    assert (row["escrowed_budget"], row["budget"], row["contractor_id"]) == (
        BID, BUDGET, contractor.agent_id)
    assert await balance(pool, creator) == START_BALANCE - BID


async def test_a_bid_from_another_contract_cannot_be_accepted(client, pool, parties, agents):
    """A 1-token bid on contract B does not set the price of contract A."""
    creator, contractor = parties
    cheap = await agents("cheap", 0)
    contract_a = await open_contract(client, creator)
    contract_b = await open_contract(client, creator)
    await place_bid(client, contract_a, contractor, BUDGET)
    bid_on_b = await place_bid(client, contract_b, cheap, 1)

    resp = await assign(client, contract_a, bid_on_b, creator)

    assert resp.status_code == 404
    row = await contract_row(pool, contract_a)
    assert (row["status"], row["escrowed_budget"]) == ("open", BUDGET)
    assert await balance(pool, creator) == START_BALANCE - 2 * BUDGET
    assert await ledger(pool, contract_a, BID_REFUND_TX) == 0


async def test_the_price_is_the_accepted_bid_not_the_lowest(client, pool, parties, agents):
    creator, contractor = parties
    low = await agents("low", 0)
    contract_id = await open_contract(client, creator)
    await place_bid(client, contract_id, low, 1)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    assert (await assign(client, contract_id, bid_id, creator)).status_code == 200

    assert (await contract_row(pool, contract_id))["escrowed_budget"] == BID
    assert await balance(pool, creator) == START_BALANCE - BID
    assert await balance(pool, low) == 0


async def test_a_bid_cannot_be_changed_after_it_is_placed(client, pool, parties):
    """One bid per agent: a low bid cannot be raised once it looks like winning."""
    creator, contractor = parties
    contract_id = await open_contract(client, creator)
    await place_bid(client, contract_id, contractor, 1)

    assert (await bid(client, contract_id, contractor, BUDGET)).status_code == 409
    assert await pool.fetchval(
        "SELECT bid_amount FROM contract_bids WHERE contract_id = $1", UUID(contract_id)) == 1


# ── Over-budget or broken bids already in the table ───────────────────────────

@pytest.mark.parametrize("amount", [BUDGET + 1, BUDGET * 1000, 0, -BID])
async def test_a_stored_bid_outside_the_budget_cannot_be_accepted(
    client, pool, parties, amount,
):
    """Such a bid can only predate the rule. Accepting it must not pay more
    than was escrowed, must not draw on the creator's wallet, and a negative
    one must not 'refund' more than the budget."""
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bid_id = await force_bid(pool, contract_id, contractor, amount)

    resp = await assign(client, contract_id, bid_id, creator)

    assert resp.status_code == 409, resp.text
    await assert_still_open(pool, contract_id, creator, contractor)
    assert await pool.fetchval(
        "SELECT status FROM contract_bids WHERE bid_id = $1", UUID(bid_id)) == "pending"
    assert await total_tokens(pool) == before

    # The creator is not stuck: the contract can still be cancelled in full.
    assert (await client.post(
        f"/contracts/{contract_id}/cancel", headers=creator.headers)).status_code == 200
    assert await balance(pool, creator) == START_BALANCE


async def test_a_bid_is_measured_against_what_is_held_not_what_is_advertised(
    client, pool, parties,
):
    """If the row ever advertised more than it holds, the bid cannot exceed
    what is held (and the reverse)."""
    creator, contractor = parties
    contract_id = await open_contract(client, creator)
    await pool.execute(
        "UPDATE contracts SET budget = $2 WHERE contract_id = $1", UUID(contract_id), BUDGET * 5)

    assert (await bid(client, contract_id, contractor, BUDGET + 1)).status_code == 422
    assert (await bid(client, contract_id, contractor, BUDGET)).status_code == 201


# ── Who can trigger the refund ────────────────────────────────────────────────

async def test_only_the_creator_can_accept_a_bid_and_trigger_the_refund(
    client, pool, parties, agents,
):
    creator, contractor = parties
    stranger = await agents("stranger", START_BALANCE)
    founder = await agents("founder", role="FOUNDER")
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    for caller, code in ((contractor, 403), (stranger, 403), (founder, 403), (None, 401)):
        resp = await assign(client, contract_id, bid_id, caller)
        assert resp.status_code == code, (caller and caller.role, resp.text)
    with pytest.raises(PermissionError):
        await contract_service.assign_contract(UUID(contract_id), stranger.did, UUID(bid_id))

    await assert_still_open(pool, contract_id, creator, contractor)
    assert await balance(pool, stranger) == START_BALANCE


async def test_no_second_refund_from_assigning_again(client, pool, parties, agents):
    creator, contractor = parties
    other = await agents("other", 0)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)
    other_bid = await place_bid(client, contract_id, other, 1)
    assert (await assign(client, contract_id, bid_id, creator)).status_code == 200

    for again in (bid_id, other_bid):
        assert (await assign(client, contract_id, again, creator)).status_code == 409

    row = await contract_row(pool, contract_id)
    assert (row["escrowed_budget"], row["contractor_id"]) == (BID, contractor.agent_id)
    assert await balance(pool, creator) == START_BALANCE - BID
    assert await ledger(pool, contract_id, BID_REFUND_TX) == 1


async def test_concurrent_assigns_of_different_bids_refund_once(client, pool, agents):
    """Eight bids of eight amounts accepted at once: one wins, and the refund
    matches that one."""
    creator = await agents("creator", START_BALANCE)
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bids = {}
    for i in range(8):
        amount = 10 + i * 10
        bids[await place_bid(client, contract_id, await agents(f"b{i}", 0), amount)] = amount

    responses = await asyncio.gather(*[
        assign(client, contract_id, b, creator) for b in bids
    ])

    assert sorted(r.status_code for r in responses) == [200] + [409] * 7
    accepted = await pool.fetchval(
        "SELECT bid_id FROM contract_bids WHERE contract_id = $1 AND status = 'accepted'",
        UUID(contract_id))
    price = bids[str(accepted)]
    assert (await contract_row(pool, contract_id))["escrowed_budget"] == price
    assert await balance(pool, creator) == START_BALANCE - price
    assert await ledger(pool, contract_id, BID_REFUND_TX) == (1 if price < BUDGET else 0)
    assert await total_tokens(pool) == before


async def test_same_bid_accepted_twelve_times_at_once_refunds_once(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    responses = await asyncio.gather(*[
        assign(client, contract_id, bid_id, creator) for _ in range(12)
    ])

    assert sorted(r.status_code for r in responses) == [200] + [409] * 11
    assert await balance(pool, creator) == START_BALANCE - BID
    assert await ledger(pool, contract_id, BID_REFUND_TX) == 1
    assert await count(pool, "contract_assignments", contract_id) == 1
    assert await total_tokens(pool) == before


async def test_assign_racing_cancel_refunds_the_budget_exactly_once(client, pool, parties):
    """Either the contract is cancelled (whole budget back) or assigned (the
    rest back, the bid held) — never both refunds."""
    creator, contractor = parties
    before = await total_tokens(pool)
    for _ in range(5):
        contract_id = await open_contract(client, creator)
        bid_id = await place_bid(client, contract_id, contractor, BID)
        start = await balance(pool, creator)

        assigned, cancelled = await asyncio.gather(
            assign(client, contract_id, bid_id, creator),
            client.post(f"/contracts/{contract_id}/cancel", headers=creator.headers),
        )

        assert sorted([assigned.status_code, cancelled.status_code]) == [200, 409]
        row = await contract_row(pool, contract_id)
        if assigned.status_code == 200:
            assert (row["status"], row["escrowed_budget"]) == ("assigned", BID)
            assert await balance(pool, creator) == start + REMAINDER
            assert await ledger(pool, contract_id, "contract_refund") == 0
        else:
            assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
            assert await balance(pool, creator) == start + BUDGET
            assert await ledger(pool, contract_id, BID_REFUND_TX) == 0
    assert await total_tokens(pool) == before


# ── Failure: all or nothing ───────────────────────────────────────────────────

async def test_a_failed_refund_leaves_the_contract_open(client, pool, parties, monkeypatch):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)

    async def broken_ledger(*_args, **_kwargs):
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(contract_service, "_record_transaction", broken_ledger)
        with pytest.raises(RuntimeError):
            await contract_service.assign_contract(UUID(contract_id), creator.did, UUID(bid_id))

    await assert_still_open(pool, contract_id, creator, contractor)
    assert await total_tokens(pool) == before
    assert (await assign(client, contract_id, bid_id, creator)).status_code == 200   # retry works


async def test_a_failure_after_the_refund_takes_the_refund_back(
    client, pool, parties, monkeypatch,
):
    """The refund and the assignment are one transaction: if recording the
    assignment fails, the creator does not keep the refund."""
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)
    # Make the step after the refund (the assignment INSERT) fail in the database.
    await pool.execute(
        "ALTER TABLE contract_assignments ADD CONSTRAINT tmp_block "
        f"CHECK (contract_id <> '{UUID(contract_id)}'::uuid)")
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await contract_service.assign_contract(UUID(contract_id), creator.did, UUID(bid_id))
        await assert_still_open(pool, contract_id, creator, contractor)
        assert await total_tokens(pool) == before
    finally:
        await pool.execute("ALTER TABLE contract_assignments DROP CONSTRAINT tmp_block")
    assert (await assign(client, contract_id, bid_id, creator)).status_code == 200


async def test_the_refund_does_not_depend_on_what_the_creator_holds(client, pool, parties):
    """The refund comes out of escrow: an emptied wallet gets exactly the rest."""
    creator, contractor = parties
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor, BID)
    before = await total_tokens(pool)
    held = await balance(pool, creator)
    await pool.execute(
        "UPDATE wallets SET balance = 0 WHERE agent_id = $1", creator.agent_id)

    assert (await assign(client, contract_id, bid_id, creator)).status_code == 200

    assert await balance(pool, creator) == REMAINDER
    assert await total_tokens(pool) == before - held


async def test_unknown_contract_or_bid_is_404(client, parties):
    creator, _ = parties
    assert (await assign(client, str(uuid4()), str(uuid4()), creator)).status_code == 404
