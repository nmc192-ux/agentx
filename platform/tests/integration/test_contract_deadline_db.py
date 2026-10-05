"""
Integration tests: contract deadlines, against REAL local Postgres.
Sprint 12, S12-4 (decision D3c).

Every request goes HTTP → routers/contracts.py → contract_service → Postgres.
Only the JWT check is replaced (the caller is set per request) and the Redis
event bus is silenced; no money path is mocked. The fixtures are in
conftest.py. Time is never mocked either: a test moves the stored deadline or
delivery time on the row and the service compares it with the database clock.

What is proven:
  • reclaim: only the creator, only an 'assigned' contract, only one that has
    a deadline, only after it has passed; once, however concurrently
  • a delivery beats the reclaim: once a result is in, late or not, the
    creator cannot take the escrow back; a reclaim racing a delivery ends in
    exactly one outcome
  • a deadline cannot be a trap: none in the past at creation, no bid and no
    assignment after it
  • automatic release: only a 'submitted' contract, only AUTO_RELEASE_DAYS
    after the delivery, to the contractor on the row, once; no route does it
  • a disputed contract is touched by neither rule
  • a failure during either payout changes nothing; tokens are conserved

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.services import contract_service
from src.services.auto_release import AUTO_RELEASE_DAYS
from src.services.contract_service import ContractConflictError

from .support import START_BALANCE, Agent, balance, total_tokens
from .test_contract_escrow_db import BUDGET, contract_row, ledger, place_bid

pytestmark = pytest.mark.integration   # skipped unless --db is given

REFUND_TX = "contract_deadline_refund"
RELEASE_TX = "contract_auto_release"
_PAYOUT_TYPES = (
    REFUND_TX, RELEASE_TX, "contract_release", "contract_refund",
    "contract_dispute_release", "contract_dispute_refund",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _in(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


async def open_contract(client, creator: Agent, *, deadline: str | None = "default") -> str:
    body = {"title": "deadline test", "description": "integration", "budget": BUDGET}
    if deadline == "default":
        deadline = _in(days=1)
    if deadline is not None:
        body["deadline"] = deadline
    resp = await client.post("/contracts", json=body, headers=creator.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["contract_id"]


async def assigned_contract(client, creator: Agent, contractor: Agent, **kw) -> str:
    contract_id = await open_contract(client, creator, **kw)
    bid_id = await place_bid(client, contract_id, contractor)
    resp = await client.post(
        f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=creator.headers)
    assert resp.status_code == 200, resp.text
    return contract_id


async def deliver(client, contract_id: str, contractor: Agent):
    return await client.post(
        f"/contracts/{contract_id}/result", json={"result_payload": {"done": True}},
        headers=contractor.headers,
    )


async def submitted_contract(client, creator: Agent, contractor: Agent, **kw) -> str:
    contract_id = await assigned_contract(client, creator, contractor, **kw)
    assert (await deliver(client, contract_id, contractor)).status_code == 201
    return contract_id


async def move_deadline(pool, contract_id: str, offset: str) -> None:
    """Set the deadline to the database's now + *offset* (e.g. '-1 second')."""
    await pool.execute(
        "UPDATE contracts SET deadline = CURRENT_TIMESTAMP + $2::text::interval "
        "WHERE contract_id = $1",
        UUID(contract_id), offset,
    )


async def age_delivery(pool, contract_id: str, age: str) -> None:
    """Make the delivery *age* old by the database clock (e.g. '7 days 1 minute')."""
    await pool.execute(
        "UPDATE contract_results SET submitted_at = CURRENT_TIMESTAMP - $2::text::interval "
        "WHERE contract_id = $1",
        UUID(contract_id), age,
    )


async def reclaim(client, contract_id: str, caller: Agent | None):
    return await client.post(
        f"/contracts/{contract_id}/reclaim", headers=caller.headers if caller else {})


async def payouts(pool, contract_id: str) -> int:
    return sum([await ledger(pool, contract_id, t) for t in _PAYOUT_TYPES])


async def assert_held(pool, contract_id: str, creator: Agent, contractor: Agent, status: str):
    """Nothing has moved: escrow held, nobody paid, status unchanged."""
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == (status, BUDGET)
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await balance(pool, contractor) == 0
    assert await payouts(pool, contract_id) == 0


@pytest.fixture
async def parties(agents):
    creator = await agents("creator", START_BALANCE)
    contractor = await agents("contractor", 0)
    return creator, contractor


# ── Reclaim: the happy path ───────────────────────────────────────────────────

async def test_creator_reclaims_after_a_missed_deadline(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    resp = await reclaim(client, contract_id, creator)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["escrowed_budget"]) == ("cancelled", 0)
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
    assert await balance(pool, creator) == START_BALANCE
    assert await balance(pool, contractor) == 0
    assert await ledger(pool, contract_id, REFUND_TX) == 1
    assert await payouts(pool, contract_id) == 1
    assert await total_tokens(pool) == before


# ── Reclaim: wrong caller ─────────────────────────────────────────────────────

async def test_only_the_creator_can_reclaim(client, pool, parties, agents):
    creator, contractor = parties
    stranger = await agents("stranger", START_BALANCE)
    founder = await agents("founder", role="FOUNDER")
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 day")

    for caller, code in ((contractor, 403), (stranger, 403), (founder, 403), (None, 401)):
        resp = await reclaim(client, contract_id, caller)
        assert resp.status_code == code, (caller and caller.role, resp.text)
    with pytest.raises(PermissionError):
        await contract_service.reclaim_contract(UUID(contract_id), contractor.did)

    await assert_held(pool, contract_id, creator, contractor, "assigned")
    assert await balance(pool, stranger) == START_BALANCE


async def test_reclaiming_an_unknown_contract_is_404(client, parties):
    creator, _ = parties
    assert (await reclaim(client, str(uuid4()), creator)).status_code == 404


# ── Reclaim: early call ───────────────────────────────────────────────────────

async def test_no_reclaim_before_the_deadline(client, pool, parties):
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)

    assert (await reclaim(client, contract_id, creator)).status_code == 409   # a day left
    await move_deadline(pool, contract_id, "1 minute")
    assert (await reclaim(client, contract_id, creator)).status_code == 409   # a minute left
    await assert_held(pool, contract_id, creator, contractor, "assigned")

    await move_deadline(pool, contract_id, "-1 second")
    assert (await reclaim(client, contract_id, creator)).status_code == 200


async def test_a_contract_without_a_deadline_cannot_be_reclaimed(client, pool, parties):
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor, deadline=None)
    # However old it is.
    await pool.execute(
        "UPDATE contracts SET created_at = created_at - INTERVAL '10 years' WHERE contract_id = $1",
        UUID(contract_id))

    resp = await reclaim(client, contract_id, creator)

    assert resp.status_code == 409
    assert "no deadline" in resp.json()["detail"]
    await assert_held(pool, contract_id, creator, contractor, "assigned")


async def test_the_request_cannot_supply_the_time(client, pool, parties):
    """Nothing the caller sends moves the clock or the deadline."""
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)
    past = _in(days=-30)

    resp = await client.post(
        f"/contracts/{contract_id}/reclaim?now={past}&deadline={past}",
        json={"now": past, "deadline": past, "force": True},
        headers={**creator.headers, "Date": "Thu, 01 Jan 2099 00:00:00 GMT"},
    )

    assert resp.status_code == 409
    await assert_held(pool, contract_id, creator, contractor, "assigned")


# ── Reclaim: only 'assigned' ──────────────────────────────────────────────────

async def test_reclaim_is_only_for_an_assigned_contract(client, pool, parties):
    """Past deadline or not: open (cancel instead), submitted, disputed,
    completed and cancelled contracts are refused and nothing moves."""
    creator, contractor = parties

    open_id = await open_contract(client, creator)
    submitted_id = await submitted_contract(client, creator, contractor)
    disputed_id = await assigned_contract(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{disputed_id}/dispute", json={"reason": "late"},
        headers=contractor.headers)
    assert resp.status_code == 201
    completed_id = await submitted_contract(client, creator, contractor)
    assert (await client.post(
        f"/contracts/{completed_id}/complete", headers=creator.headers)).status_code == 200
    cancelled_id = await open_contract(client, creator)
    assert (await client.post(
        f"/contracts/{cancelled_id}/cancel", headers=creator.headers)).status_code == 200

    expected = {open_id: "open", submitted_id: "submitted", disputed_id: "disputed",
                completed_id: "completed", cancelled_id: "cancelled"}
    wallets = (await balance(pool, creator), await balance(pool, contractor))
    for contract_id, status in expected.items():
        await move_deadline(pool, contract_id, "-1 day")
        resp = await reclaim(client, contract_id, creator)
        assert resp.status_code == 409, (status, resp.text)
        assert (await contract_row(pool, contract_id))["status"] == status
        assert await ledger(pool, contract_id, REFUND_TX) == 0
    assert (await balance(pool, creator), await balance(pool, contractor)) == wallets


async def test_a_late_delivery_still_beats_the_reclaim(client, pool, parties):
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 hour")

    assert (await deliver(client, contract_id, contractor)).status_code == 201
    assert (await reclaim(client, contract_id, creator)).status_code == 409
    await assert_held(pool, contract_id, creator, contractor, "submitted")

    # The creator's choices are now to complete or to dispute.
    assert (await client.post(
        f"/contracts/{contract_id}/complete", headers=creator.headers)).status_code == 200
    assert await balance(pool, contractor) == BUDGET


async def test_a_contractor_can_dispute_to_block_a_reclaim(client, pool, parties):
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 hour")

    resp = await client.post(
        f"/contracts/{contract_id}/dispute", json={"reason": "the brief changed"},
        headers=contractor.headers)
    assert resp.status_code == 201

    assert (await reclaim(client, contract_id, creator)).status_code == 409
    await assert_held(pool, contract_id, creator, contractor, "disputed")


# ── Reclaim: double and concurrent calls ──────────────────────────────────────

async def test_a_second_reclaim_moves_nothing(client, pool, parties):
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    assert (await reclaim(client, contract_id, creator)).status_code == 200
    assert (await reclaim(client, contract_id, creator)).status_code == 409

    assert await balance(pool, creator) == START_BALANCE
    assert await payouts(pool, contract_id) == 1
    # A reclaimed contract is closed for good.
    assert (await deliver(client, contract_id, contractor)).status_code == 409
    for action in ("complete", "cancel"):
        assert (await client.post(
            f"/contracts/{contract_id}/{action}", headers=creator.headers)).status_code == 409
    resp = await client.post(
        f"/contracts/{contract_id}/dispute", json={"reason": "x"}, headers=contractor.headers)
    assert resp.status_code == 409
    assert await balance(pool, creator) == START_BALANCE


async def test_concurrent_reclaims_refund_once(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    responses = await asyncio.gather(*[reclaim(client, contract_id, creator) for _ in range(12)])

    assert sorted(r.status_code for r in responses) == [200] + [409] * 11
    assert await balance(pool, creator) == START_BALANCE
    assert await ledger(pool, contract_id, REFUND_TX) == 1
    assert await total_tokens(pool) == before


async def test_reclaim_racing_a_delivery_ends_in_exactly_one_outcome(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)

    for _ in range(6):
        contract_id = await assigned_contract(client, creator, contractor)
        await move_deadline(pool, contract_id, "-1 second")
        start = await balance(pool, creator)

        r_reclaim, r_deliver = await asyncio.gather(
            reclaim(client, contract_id, creator), deliver(client, contract_id, contractor))

        row = await contract_row(pool, contract_id)
        if r_reclaim.status_code == 200:
            assert r_deliver.status_code == 409
            assert (row["status"], row["escrowed_budget"]) == ("cancelled", 0)
            assert await balance(pool, creator) == start + BUDGET
            assert await ledger(pool, contract_id, REFUND_TX) == 1
        else:
            assert (r_reclaim.status_code, r_deliver.status_code) == (409, 201)
            assert (row["status"], row["escrowed_budget"]) == ("submitted", BUDGET)
            assert await balance(pool, creator) == start
            assert await payouts(pool, contract_id) == 0
        assert await balance(pool, contractor) == 0
    assert await total_tokens(pool) == before


async def test_a_failed_refund_leaves_the_contract_as_it_was(client, pool, parties, monkeypatch):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    async def broken_ledger(*_args, **_kwargs):
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(contract_service, "_record_transaction", broken_ledger)
        with pytest.raises(RuntimeError):
            await contract_service.reclaim_contract(UUID(contract_id), creator.did)

    await assert_held(pool, contract_id, creator, contractor, "assigned")
    assert await total_tokens(pool) == before
    assert (await reclaim(client, contract_id, creator)).status_code == 200   # …and can be retried


# ── A deadline cannot be a trap ───────────────────────────────────────────────

async def test_a_contract_cannot_be_created_with_a_past_deadline(client, pool, parties):
    creator, _ = parties
    contracts_before = await pool.fetchval("SELECT COUNT(*) FROM contracts")

    for deadline in (_in(seconds=-5), _in(days=-400),
                     # no zone means UTC: this is an hour ago, wherever the server runs
                     (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()):
        resp = await client.post(
            "/contracts",
            json={"title": "trap", "description": "x", "budget": BUDGET, "deadline": deadline},
            headers=creator.headers,
        )
        assert resp.status_code == 400, resp.text

    assert await pool.fetchval("SELECT COUNT(*) FROM contracts") == contracts_before
    assert await balance(pool, creator) == START_BALANCE


async def test_a_deadline_with_no_zone_is_read_as_utc(client, pool, parties):
    creator, _ = parties
    naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None, microsecond=0)

    contract_id = await open_contract(client, creator, deadline=naive.isoformat())

    stored = await pool.fetchval(
        "SELECT deadline FROM contracts WHERE contract_id = $1", UUID(contract_id))
    assert stored == naive.replace(tzinfo=timezone.utc)


async def test_no_bid_and_no_assignment_after_the_deadline(client, pool, parties, agents):
    """Otherwise a creator could hire someone and reclaim in the same minute."""
    creator, contractor = parties
    late_bidder = await agents("late", 0)
    contract_id = await open_contract(client, creator)
    bid_id = await place_bid(client, contract_id, contractor)
    await move_deadline(pool, contract_id, "-1 second")

    resp = await client.post(
        f"/contracts/{contract_id}/bid", json={"bid_amount": 10}, headers=late_bidder.headers)
    assert resp.status_code == 409
    resp = await client.post(
        f"/contracts/{contract_id}/assign", json={"bid_id": bid_id}, headers=creator.headers)
    assert resp.status_code == 409
    assert (await reclaim(client, contract_id, creator)).status_code == 409   # still 'open'
    row = await contract_row(pool, contract_id)
    assert (row["status"], row["contractor_id"], row["escrowed_budget"]) == ("open", None, BUDGET)

    # The creator gets the budget back the ordinary way.
    assert (await client.post(
        f"/contracts/{contract_id}/cancel", headers=creator.headers)).status_code == 200
    assert await balance(pool, creator) == START_BALANCE


# ── Automatic release to the contractor ───────────────────────────────────────

async def test_automatic_release_only_after_the_period_and_only_once(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)
    cid = UUID(contract_id)

    with pytest.raises(ContractConflictError):                      # just delivered
        await contract_service.release_overdue_contract(cid)
    await age_delivery(pool, contract_id, f"{AUTO_RELEASE_DAYS} days -1 minute")
    with pytest.raises(ContractConflictError):                      # one minute early
        await contract_service.release_overdue_contract(cid)
    await assert_held(pool, contract_id, creator, contractor, "submitted")

    await age_delivery(pool, contract_id, f"{AUTO_RELEASE_DAYS} days 1 minute")
    assert await contract_service.release_overdue_contract(cid) == BUDGET

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
    assert await balance(pool, contractor) == BUDGET
    assert await balance(pool, creator) == START_BALANCE - BUDGET
    assert await ledger(pool, contract_id, RELEASE_TX) == 1

    with pytest.raises(ContractConflictError):                      # second call
        await contract_service.release_overdue_contract(cid)
    assert (await client.post(                                       # creator, afterwards
        f"/contracts/{contract_id}/complete", headers=creator.headers)).status_code == 409
    assert await balance(pool, contractor) == BUDGET
    assert await payouts(pool, contract_id) == 1
    assert await total_tokens(pool) == before


async def test_the_contract_deadline_does_not_shorten_the_creators_time(client, pool, parties):
    """The 7 days run from the delivery, not from the contract's deadline."""
    creator, contractor = parties
    contract_id = await submitted_contract(client, creator, contractor)
    await move_deadline(pool, contract_id, "-30 days")
    await pool.execute(
        "UPDATE contracts SET created_at = created_at - INTERVAL '60 days' WHERE contract_id = $1",
        UUID(contract_id))
    await pool.execute(
        "UPDATE contract_assignments SET assigned_at = assigned_at - INTERVAL '60 days', "
        "completed_at = completed_at - INTERVAL '60 days' WHERE contract_id = $1",
        UUID(contract_id))

    with pytest.raises(ContractConflictError):
        await contract_service.release_overdue_contract(UUID(contract_id))
    await assert_held(pool, contract_id, creator, contractor, "submitted")


async def test_concurrent_automatic_releases_pay_once(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)
    await age_delivery(pool, contract_id, f"{AUTO_RELEASE_DAYS + 1} days")

    results = await asyncio.gather(
        *[contract_service.release_overdue_contract(UUID(contract_id)) for _ in range(12)],
        return_exceptions=True,
    )

    assert [r for r in results if not isinstance(r, Exception)] == [BUDGET]
    assert all(isinstance(r, ContractConflictError) for r in results if isinstance(r, Exception))
    assert await balance(pool, contractor) == BUDGET
    assert await ledger(pool, contract_id, RELEASE_TX) == 1
    assert await total_tokens(pool) == before


async def test_automatic_release_racing_the_creator_pays_once(client, pool, parties):
    """Release vs. the creator completing, and release vs. the creator disputing."""
    creator, contractor = parties
    before = await total_tokens(pool)
    paid = 0

    for action, body in (("complete", None), ("dispute", {"reason": "not what I asked for"})):
        for _ in range(4):
            contract_id = await submitted_contract(client, creator, contractor)
            await age_delivery(pool, contract_id, f"{AUTO_RELEASE_DAYS + 1} days")

            released, resp = await asyncio.gather(
                contract_service.release_overdue_contract(UUID(contract_id)),
                client.post(f"/contracts/{contract_id}/{action}", json=body,
                            headers=creator.headers),
                return_exceptions=True,
            )

            row = await contract_row(pool, contract_id)
            auto = await ledger(pool, contract_id, RELEASE_TX)
            if action == "dispute" and resp.status_code == 201:
                # The dispute landed first: the escrow waits for a FOUNDER.
                assert isinstance(released, ContractConflictError)
                assert (row["status"], row["escrowed_budget"]) == ("disputed", BUDGET)
                assert await payouts(pool, contract_id) == 0
            else:
                assert (row["status"], row["escrowed_budget"]) == ("completed", 0)
                assert await payouts(pool, contract_id) == 1
                assert (released == BUDGET) == (auto == 1)
                assert (resp.status_code == 200) == (auto == 0)
                paid += BUDGET
            assert await balance(pool, contractor) == paid
    assert await total_tokens(pool) == before


async def test_automatic_release_refuses_every_contract_not_awaiting_the_creator(
        client, pool, parties):
    """Even with an old delivery forced onto the row, only 'submitted' pays."""
    creator, contractor = parties

    open_id = await open_contract(client, creator)
    assigned_id = await assigned_contract(client, creator, contractor)
    disputed_id = await submitted_contract(client, creator, contractor)
    resp = await client.post(
        f"/contracts/{disputed_id}/dispute", json={"reason": "bad work"}, headers=creator.headers)
    assert resp.status_code == 201
    cancelled_id = await open_contract(client, creator)
    assert (await client.post(
        f"/contracts/{cancelled_id}/cancel", headers=creator.headers)).status_code == 200
    reclaimed_id = await assigned_contract(client, creator, contractor)
    await move_deadline(pool, reclaimed_id, "-1 second")
    assert (await reclaim(client, reclaimed_id, creator)).status_code == 200

    expected = {open_id: "open", assigned_id: "assigned", disputed_id: "disputed",
                cancelled_id: "cancelled", reclaimed_id: "cancelled"}
    wallets = (await balance(pool, creator), await balance(pool, contractor))
    for contract_id, status in expected.items():
        # Force an old delivery onto contracts that never had one.
        await pool.execute(
            """
            INSERT INTO contract_results (contract_id, contractor_did, contractor_id, submitted_at)
            SELECT $1, $2, $3, CURRENT_TIMESTAMP - INTERVAL '30 days'
            WHERE NOT EXISTS (SELECT 1 FROM contract_results WHERE contract_id = $1)
            """,
            UUID(contract_id), contractor.did, contractor.agent_id)
        await age_delivery(pool, contract_id, "30 days")
        with pytest.raises(ContractConflictError):
            await contract_service.release_overdue_contract(UUID(contract_id))
        assert (await contract_row(pool, contract_id))["status"] == status
        assert await ledger(pool, contract_id, RELEASE_TX) == 0
    assert (await balance(pool, creator), await balance(pool, contractor)) == wallets

    with pytest.raises(ValueError, match="not found"):
        await contract_service.release_overdue_contract(uuid4())


async def test_submitted_without_a_result_on_record_pays_nothing(client, pool, parties):
    """Fail closed: a row forced to 'submitted' with no delivery is never due."""
    creator, contractor = parties
    contract_id = await assigned_contract(client, creator, contractor)
    await pool.execute(
        "UPDATE contracts SET status = 'submitted', created_at = created_at - INTERVAL '1 year' "
        "WHERE contract_id = $1", UUID(contract_id))

    with pytest.raises(ContractConflictError):
        await contract_service.release_overdue_contract(UUID(contract_id))

    await assert_held(pool, contract_id, creator, contractor, "submitted")


async def test_a_vanished_contractor_is_not_replaced_by_a_guess(client, pool, parties):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)
    await age_delivery(pool, contract_id, "30 days")
    # What ON DELETE SET NULL leaves behind, without deleting the agent.
    await pool.execute(
        "UPDATE contracts SET contractor_id = NULL WHERE contract_id = $1", UUID(contract_id))

    with pytest.raises(ContractConflictError, match="no contractor"):
        await contract_service.release_overdue_contract(UUID(contract_id))

    row = await contract_row(pool, contract_id)
    assert (row["status"], row["escrowed_budget"]) == ("submitted", BUDGET)
    assert await payouts(pool, contract_id) == 0
    assert await total_tokens(pool) == before


async def test_a_failed_release_leaves_the_contract_as_it_was(client, pool, parties, monkeypatch):
    creator, contractor = parties
    before = await total_tokens(pool)
    contract_id = await submitted_contract(client, creator, contractor)
    await age_delivery(pool, contract_id, "8 days")

    async def broken_ledger(*_args, **_kwargs):
        raise RuntimeError("ledger down")

    with monkeypatch.context() as patch:
        patch.setattr(contract_service, "_record_transaction", broken_ledger)
        with pytest.raises(RuntimeError):
            await contract_service.release_overdue_contract(UUID(contract_id))

    await assert_held(pool, contract_id, creator, contractor, "submitted")
    assert await total_tokens(pool) == before
    assert await contract_service.release_overdue_contract(UUID(contract_id)) == BUDGET


async def test_no_route_releases_an_unanswered_delivery(client, pool, parties, agents):
    """The automatic release is the job's alone: no caller can trigger it, and
    the contractor cannot pay themselves through any contract route."""
    creator, contractor = parties
    stranger = await agents("stranger", 0)
    contract_id = await submitted_contract(client, creator, contractor)
    await age_delivery(pool, contract_id, "30 days")
    await move_deadline(pool, contract_id, "-30 days")

    for caller in (contractor, stranger):
        for action in ("complete", "cancel", "reclaim", "release", "auto-release", "settle"):
            resp = await client.post(
                f"/contracts/{contract_id}/{action}",
                json={"outcome": "pay_contractor", "note": "pay me"},
                headers=caller.headers,
            )
            assert resp.status_code in (403, 404, 405), (action, resp.status_code)

    await assert_held(pool, contract_id, creator, contractor, "submitted")
