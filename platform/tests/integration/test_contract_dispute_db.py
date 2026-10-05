"""
Integration tests: a FOUNDER settles a disputed contract, against REAL local
Postgres. Sprint 12, S12-3 (decision D3b).

Every request goes HTTP → routers/contracts.py → contract_service → Postgres.
Only the JWT check is replaced (the caller is set per request) and the Redis
event bus is silenced; no money path is mocked. The fixtures are in
conftest.py.

What is proven:
  • only a FOUNDER settles: creator, contractor, stranger, OPERATOR, DELEGATE
    and anonymous callers are refused and nothing moves
  • the role is the database's, read in the settling transaction: a caller
    the route takes for a FOUNDER but who is demoted or suspended in the
    database is refused; so is a direct service call by a non-founder
  • a FOUNDER who is a party to the contract cannot rule on it
  • only a 'disputed' contract can be settled
  • pay_contractor pays the whole escrow to the contractor, refund_creator
    returns it to the creator; the body can name neither payee nor amount
  • once only: repeated, opposite and concurrent rulings move the escrow once
  • a settled contract is closed for good: no complete, cancel, result,
    dispute or second ruling
  • a failure during the payout leaves the dispute exactly as it was
  • tokens are conserved: wallets + escrow never change in total

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
    count,
    ledger,
    open_contract,
    submitted_contract,
)

pytestmark = pytest.mark.integration   # skipped unless --db is given

PAY = {"outcome": "pay_contractor", "note": "work was delivered as agreed"}
REFUND = {"outcome": "refund_creator", "note": "nothing usable was delivered"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def disputed_contract(
    client, creator: Agent, contractor: Agent, *, submitted: bool = True,
    by: Agent | None = None,
) -> str:
    make = submitted_contract if submitted else assigned_contract
    contract_id = await make(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{contract_id}/dispute", json={"reason": "we disagree"},
        headers=(by or creator).headers,
    )
    assert resp.status_code == 201, resp.text
    return contract_id


async def settle(client, contract_id: str, caller: Agent | None, body: dict):
    return await client.post(
        f"/contracts/{contract_id}/settle", json=body,
        headers=caller.headers if caller else {},
    )


async def dispute_rows(pool, contract_id: str):
    return await pool.fetch(
        "SELECT status, resolution, resolved_by_did, resolved_at, resolution_note "
        "FROM contract_disputes WHERE contract_id = $1",
        UUID(contract_id),
    )


async def settlement_entries(pool, contract_id: str) -> int:
    return (await ledger(pool, contract_id, "contract_dispute_release")
            + await ledger(pool, contract_id, "contract_dispute_refund")
            + await ledger(pool, contract_id, "contract_release")
            + await ledger(pool, contract_id, "contract_refund"))


async def assert_untouched(pool, contract_id: str, creator: Agent, contractor: Agent):
    """The dispute is exactly as it was opened: escrow held, nobody paid."""
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await balance(pool, contractor) == 0
    assert await settlement_entries(pool, contract_id) == 0
    rows = await dispute_rows(pool, contract_id)
    assert [(r["status"], r["resolution"], r["resolved_by_did"]) for r in rows] == [
        ("open", None, None)]


@pytest.fixture
async def parties(agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    founder = await agents("founder", role="FOUNDER")
    return creator, contractor, founder


# ── Who may settle ────────────────────────────────────────────────────────────

async def test_only_a_founder_can_settle(client, pool, agents, parties):
    creator, contractor, _founder = parties
    stranger = await agents("stranger", START_BALANCE)
    operator = await agents("operator", role="OPERATOR")
    delegate = await agents("delegate", role="DELEGATE")
    observer = await agents("observer", role="OBSERVER")
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor)

    for caller in (creator, contractor, stranger, operator, delegate, observer):
        for body in (PAY, REFUND):
            resp = await settle(client, contract_id, caller, body)
            assert resp.status_code == 403, (caller.role, resp.text)
    for body in (PAY, REFUND):
        assert (await settle(client, contract_id, None, body)).status_code == 401

    await assert_untouched(pool, contract_id, creator, contractor)
    assert await total_tokens(pool) == before


async def test_role_is_read_from_the_database_not_from_the_caller(client, pool, agents, parties):
    """The route takes these callers for FOUNDERs (as a token issued before a
    demotion would); the service reads the role again and refuses."""
    creator, contractor, _founder = parties
    demoted = await agents("demoted", role="FOUNDER")
    suspended = await agents("suspended", role="FOUNDER")
    await pool.execute(
        "UPDATE agents SET governance_role = 'MEMBER' WHERE agent_id = $1", demoted.agent_id)
    await pool.execute(
        "UPDATE agents SET status = 'SUSPENDED' WHERE agent_id = $1", suspended.agent_id)
    contract_id = await disputed_contract(client, creator, contractor)

    for caller in (demoted, suspended):
        for body in (PAY, REFUND):
            resp = await settle(client, contract_id, caller, body)
            assert resp.status_code == 403, resp.text
            assert "FOUNDER" in resp.json()["detail"]

    await assert_untouched(pool, contract_id, creator, contractor)


async def test_service_refuses_a_non_founder_called_directly(client, pool, agents, parties):
    """Bypassing the route's role check changes nothing."""
    from src.services import contract_service

    creator, contractor, _founder = parties
    stranger = await agents("stranger")
    contract_id = await disputed_contract(client, creator, contractor)

    for did in (stranger.did, creator.did, contractor.did, "did:agentx:nobody-001", ""):
        with pytest.raises(PermissionError):
            await contract_service.settle_dispute(
                UUID(contract_id), did, "pay_contractor", "let me in")

    await assert_untouched(pool, contract_id, creator, contractor)


async def test_a_founder_who_is_a_party_cannot_rule_on_the_contract(client, pool, agents):
    founder_creator = await agents("fcreator", START_BALANCE, role="FOUNDER")
    founder_contractor = await agents("fcontractor", 0, role="FOUNDER")
    neutral = await agents("neutral", role="FOUNDER")
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, founder_creator, founder_contractor)

    assert (await settle(client, contract_id, founder_creator, REFUND)).status_code == 403
    assert (await settle(client, contract_id, founder_contractor, PAY)).status_code == 403
    await assert_untouched(pool, contract_id, founder_creator, founder_contractor)

    # A FOUNDER with no part in it can.
    resp = await settle(client, contract_id, neutral, PAY)
    assert resp.status_code == 200, resp.text
    assert await balance(pool, founder_contractor) == BUDGET
    assert await total_tokens(pool) == before


# ── What may be settled ───────────────────────────────────────────────────────

async def test_only_a_disputed_contract_can_be_settled(client, pool, agents, parties):
    creator, contractor, founder = parties
    other = await agents("other", 0)
    before = await total_tokens(pool)

    completed = await submitted_contract(client, creator, other)
    assert (await client.post(
        f"/contracts/{completed}/complete", headers=creator.headers)).status_code == 200
    cancelled = await open_contract(client, creator)
    assert (await client.post(
        f"/contracts/{cancelled}/cancel", headers=creator.headers)).status_code == 200
    contracts = {
        "open": await open_contract(client, creator),
        "assigned": await assigned_contract(client, creator, contractor),
        "submitted": await submitted_contract(client, creator, contractor),
        "completed": completed,
        "cancelled": cancelled,
    }
    balances = (await balance(pool, creator), await balance(pool, contractor),
                await balance(pool, other))

    for status, contract_id in contracts.items():
        escrow = (await contract_row(pool, contract_id))["escrowed_budget"]
        for body in (PAY, REFUND):
            resp = await settle(client, contract_id, founder, body)
            assert resp.status_code == 409, (status, resp.text)
        row = await contract_row(pool, contract_id)
        assert (row["status"], row["escrowed_budget"]) == (status, escrow)
        assert await ledger(pool, contract_id, "contract_dispute_release") == 0
        assert await ledger(pool, contract_id, "contract_dispute_refund") == 0

    assert balances == (await balance(pool, creator), await balance(pool, contractor),
                        await balance(pool, other))
    assert await total_tokens(pool) == before

    missing = await settle(client, str(uuid4()), founder, PAY)
    assert missing.status_code == 404


async def test_disputed_contract_with_no_open_dispute_on_record_is_refused(
        client, pool, parties):
    """Cannot arise through the API; if the data says so, nothing is paid."""
    creator, contractor, founder = parties
    contract_id = await disputed_contract(client, creator, contractor)
    await pool.execute(
        "DELETE FROM contract_disputes WHERE contract_id = $1", UUID(contract_id))

    resp = await settle(client, contract_id, founder, PAY)
    assert resp.status_code == 409
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
    assert await balance(pool, contractor) == 0


# ── The two rulings ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("submitted", [True, False])
async def test_pay_contractor_pays_the_whole_escrow_once(client, pool, parties, submitted):
    creator, contractor, founder = parties
    before = await total_tokens(pool)
    contract_id = await disputed_contract(
        client, creator, contractor, submitted=submitted, by=contractor)

    resp = await settle(client, contract_id, founder, PAY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["outcome"], body["amount"], body["paid_to_did"]) == (
        "pay_contractor", BUDGET, contractor.did)
    assert (body["contract"]["status"], body["contract"]["escrowed_budget"]) == ("completed", 0)
    assert (body["dispute"]["status"], body["dispute"]["resolved_by_did"]) == (
        "resolved", founder.did)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
    assert await balance(pool, contractor) == BUDGET
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await balance(pool, founder) is None          # the arbiter gets nothing
    assert await ledger(pool, contract_id, "contract_dispute_release") == 1
    assert await settlement_entries(pool, contract_id) == 1
    (dispute,) = await dispute_rows(pool, contract_id)
    assert (dispute["status"], dispute["resolution"], dispute["resolved_by_did"],
            dispute["resolution_note"]) == (
        "resolved", "pay_contractor", founder.did, PAY["note"])
    assert dispute["resolved_at"] is not None
    assert await total_tokens(pool) == before


@pytest.mark.parametrize("submitted", [True, False])
async def test_refund_creator_returns_the_whole_escrow_once(client, pool, parties, submitted):
    creator, contractor, founder = parties
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor, submitted=submitted)

    resp = await settle(client, contract_id, founder, REFUND)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["outcome"], body["amount"], body["paid_to_did"]) == (
        "refund_creator", BUDGET, creator.did)

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, contractor) == 0
    assert await balance(pool, founder) is None
    assert await ledger(pool, contract_id, "contract_dispute_refund") == 1
    assert await settlement_entries(pool, contract_id) == 1
    (dispute,) = await dispute_rows(pool, contract_id)
    assert (dispute["status"], dispute["resolution"]) == ("resolved", "refund_creator")
    assert await total_tokens(pool) == before


async def test_body_cannot_name_a_payee_an_amount_or_another_outcome(
        client, pool, agents, parties):
    creator, contractor, founder = parties
    thief = await agents("thief", 0)
    contract_id = await disputed_contract(client, creator, contractor)

    bad_bodies = [
        {**PAY, "payee_did": thief.did},
        {**PAY, "paid_to_did": thief.did},
        {**PAY, "contractor_did": thief.did},
        {**REFUND, "creator_did": thief.did},
        {**PAY, "amount": BUDGET * 10},
        {"outcome": "split", "note": "half each"},
        {"outcome": "pay_founder", "note": "fee"},
        {"outcome": "", "note": "x"},
        {"outcome": "pay_contractor"},
        {"outcome": "pay_contractor", "note": ""},
        {"note": "no outcome"},
        {},
    ]
    for body in bad_bodies:
        resp = await settle(client, contract_id, founder, body)
        assert resp.status_code == 422, (body, resp.text)
    blank = await settle(client, contract_id, founder, {"outcome": "pay_contractor", "note": "   "})
    assert blank.status_code == 400

    await assert_untouched(pool, contract_id, creator, contractor)
    assert await balance(pool, thief) == 0


async def test_contractor_without_a_wallet_is_still_paid(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor")            # no wallet
    founder = await agents("founder", role="FOUNDER")
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor)

    assert (await settle(client, contract_id, founder, PAY)).status_code == 200
    assert await balance(pool, contractor) == BUDGET
    assert await total_tokens(pool) == before


async def test_a_party_that_no_longer_exists_is_not_paid_and_nobody_else_is(
        client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor")
    founder = await agents("founder", role="FOUNDER")
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor)
    # The contractor's agent row is gone (contracts.contractor_id → NULL).
    await pool.execute("DELETE FROM agents WHERE agent_id = $1", contractor.agent_id)
    assert (await contract_row(pool, contract_id))["contractor_id"] is None

    resp = await settle(client, contract_id, founder, PAY)
    assert resp.status_code == 409, resp.text
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
    assert await settlement_entries(pool, contract_id) == 0

    # The escrow is not stuck: the FOUNDER can still refund the creator.
    assert (await settle(client, contract_id, founder, REFUND)).status_code == 200
    assert await balance(pool, creator) == START_BALANCE
    assert await total_tokens(pool) == before


async def test_contract_with_nothing_in_escrow_is_closed_and_pays_nothing(
        client, pool, parties):
    """A contract from before escrow was enforced (S9-6b) may hold nothing."""
    creator, contractor, founder = parties
    contract_id = await disputed_contract(client, creator, contractor)
    await pool.execute(
        "UPDATE contracts SET escrowed_budget = 0 WHERE contract_id = $1", UUID(contract_id))
    before = await total_tokens(pool)

    resp = await settle(client, contract_id, founder, PAY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == 0
    assert (await contract_row(pool, contract_id))["status"] == "completed"
    assert await balance(pool, contractor) == 0
    assert await settlement_entries(pool, contract_id) == 0
    assert await total_tokens(pool) == before


# ── Once only ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("first, second", [(PAY, PAY), (PAY, REFUND), (REFUND, PAY), (REFUND, REFUND)])
async def test_a_second_ruling_is_refused(client, pool, agents, parties, first, second):
    creator, contractor, founder = parties
    other_founder = await agents("founder2", role="FOUNDER")
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor)

    assert (await settle(client, contract_id, founder, first)).status_code == 200
    snapshot = (dict(await contract_row(pool, contract_id)),
                await balance(pool, creator), await balance(pool, contractor),
                [dict(r) for r in await dispute_rows(pool, contract_id)])

    for caller in (founder, other_founder):
        assert (await settle(client, contract_id, caller, second)).status_code == 409

    assert snapshot == (dict(await contract_row(pool, contract_id)),
                        await balance(pool, creator), await balance(pool, contractor),
                        [dict(r) for r in await dispute_rows(pool, contract_id)])
    assert await settlement_entries(pool, contract_id) == 1
    assert await total_tokens(pool) == before


async def test_concurrent_opposite_rulings_move_the_escrow_once(client, pool, agents):
    for _ in range(4):
        creator = await agents("creator", START_BALANCE)
        contractor = await agents("contractor", 0)
        founders = [await agents(f"founder{n}", role="FOUNDER") for n in range(2)]
        before = await total_tokens(pool)
        contract_id = await disputed_contract(client, creator, contractor)

        responses = await asyncio.gather(*[
            settle(client, contract_id, founders[n % 2], PAY if n % 4 < 2 else REFUND)
            for n in range(12)
        ])
        assert sorted(r.status_code for r in responses) == [200] + [409] * 11
        (winner,) = [r.json() for r in responses if r.status_code == 200]

        row = await contract_row(pool, contract_id)
        assert row["escrowed_budget"] == 0
        if winner["outcome"] == "pay_contractor":
            assert row["status"] == "completed"
            assert (await balance(pool, contractor), await balance(pool, creator)) == (
                BUDGET, START_BALANCE - BUDGET)
        else:
            assert row["status"] == "cancelled"
            assert (await balance(pool, contractor), await balance(pool, creator)) == (
                0, START_BALANCE)
        assert await settlement_entries(pool, contract_id) == 1
        (dispute,) = await dispute_rows(pool, contract_id)
        assert dispute["resolution"] == winner["outcome"]
        assert dispute["resolved_by_did"] == winner["dispute"]["resolved_by_did"]
        assert await total_tokens(pool) == before


async def test_a_settled_contract_is_closed_for_good(client, pool, parties):
    creator, contractor, founder = parties
    before = await total_tokens(pool)

    for ruling, final in ((PAY, "completed"), (REFUND, "cancelled")):
        contract_id = await disputed_contract(client, creator, contractor, submitted=False)
        assert (await settle(client, contract_id, founder, ruling)).status_code == 200
        creator_balance = await balance(pool, creator)
        contractor_balance = await balance(pool, contractor)

        for path, caller, body in (
            ("complete", creator, None),
            ("cancel", creator, None),
            ("result", contractor, {"result_payload": {}}),
            ("dispute", creator, {"reason": "again"}),
            ("dispute", contractor, {"reason": "again"}),
        ):
            resp = await client.post(
                f"/contracts/{contract_id}/{path}", json=body, headers=caller.headers)
            assert resp.status_code == 409, (final, path, resp.text)

        row = await contract_row(pool, contract_id)
        assert (row["status"], row["escrowed_budget"]) == (final, 0)
        assert await count(pool, "contract_disputes", contract_id) == 1
        assert await balance(pool, creator) == creator_balance
        assert await balance(pool, contractor) == contractor_balance

    assert await total_tokens(pool) == before


async def test_ruling_racing_the_dispute_never_pays_an_undisputed_contract(
        client, pool, agents):
    """A ruling that arrives before the dispute commits is refused; one that
    arrives after wins. Either way the escrow moves at most once."""
    for _ in range(5):
        creator = await agents("creator", START_BALANCE)
        contractor = await agents("contractor", 0)
        founder = await agents("founder", role="FOUNDER")
        before = await total_tokens(pool)
        contract_id = await submitted_contract(client, creator, contractor)

        dispute, ruling, complete = await asyncio.gather(
            client.post(f"/contracts/{contract_id}/dispute", json={"reason": "race"},
                        headers=contractor.headers),
            settle(client, contract_id, founder, REFUND),
            client.post(f"/contracts/{contract_id}/complete", headers=creator.headers),
        )
        row = await contract_row(pool, contract_id)
        if ruling.status_code == 200:
            assert dispute.status_code == 201 and complete.status_code == 409
            assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
            assert await balance(pool, creator) == START_BALANCE
        elif complete.status_code == 200:
            assert ruling.status_code == 409 and dispute.status_code == 409
            assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
            assert await balance(pool, contractor) == BUDGET
        else:
            assert (dispute.status_code, ruling.status_code) == (201, 409)
            assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
        assert await settlement_entries(pool, contract_id) <= 1
        assert await total_tokens(pool) == before


# ── All or nothing ────────────────────────────────────────────────────────────

async def test_a_failed_payout_leaves_the_dispute_exactly_as_it_was(
        client, pool, parties, monkeypatch):
    from src.services import contract_service

    creator, contractor, founder = parties
    before = await total_tokens(pool)
    contract_id = await disputed_contract(client, creator, contractor)

    async def broken_ledger(*_args, **_kwargs):
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(contract_service, "_record_transaction", broken_ledger)
        for outcome in ("pay_contractor", "refund_creator"):
            with pytest.raises(RuntimeError):
                await contract_service.settle_dispute(
                    UUID(contract_id), founder.did, outcome, "try")

    await assert_untouched(pool, contract_id, creator, contractor)
    assert await total_tokens(pool) == before

    # …and it can still be settled afterwards.
    assert (await settle(client, contract_id, founder, PAY)).status_code == 200
    assert await balance(pool, contractor) == BUDGET
    assert await total_tokens(pool) == before


# ── Reading the dispute ───────────────────────────────────────────────────────

async def test_dispute_file_is_for_a_founder_and_the_two_parties_only(
        client, pool, agents, parties):
    creator, contractor, founder = parties
    stranger = await agents("stranger")
    operator = await agents("operator", role="OPERATOR")
    demoted = await agents("demoted", role="FOUNDER")
    await pool.execute(
        "UPDATE agents SET governance_role = 'MEMBER' WHERE agent_id = $1", demoted.agent_id)
    contract_id = await disputed_contract(client, creator, contractor)
    path = f"/contracts/{contract_id}/dispute"

    assert (await client.get(path)).status_code == 401
    for caller in (stranger, operator, demoted):
        assert (await client.get(path, headers=caller.headers)).status_code == 403
    assert (await client.get(
        f"/contracts/{uuid4()}/dispute", headers=founder.headers)).status_code == 404

    for caller in (creator, contractor, founder):
        resp = await client.get(path, headers=caller.headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["contract"]["status"] == "disputed"
        assert [(d["reason"], d["status"], d["resolution"]) for d in body["disputes"]] == [
            ("we disagree", "open", None)]
        assert [r["result_payload"] for r in body["results"]] == [{"done": True}]

    assert (await settle(client, contract_id, founder, REFUND)).status_code == 200
    body = (await client.get(path, headers=contractor.headers)).json()
    assert body["contract"]["status"] == "cancelled"
    assert [(d["status"], d["resolution"], d["resolved_by_did"], d["resolution_note"])
            for d in body["disputes"]] == [
        ("resolved", "refund_creator", founder.did, REFUND["note"])]
