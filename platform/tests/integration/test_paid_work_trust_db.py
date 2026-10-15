"""
Integration tests: trust from paid work, against REAL local Postgres.
Phase C, Sprint 21, BT-3.

A bounty won, a contract completed and a work deadline missed each write one
trust event through ``reputation.record_event``, whose rules are unchanged:
dedupe key per occurrence, an established counterparty for a positive event,
the pair and daily caps. The ledger decides whether anything happened: a
reporter called for a bounty that was refunded, a contract that was not paid
or a task that was not reclaimed writes nothing.

What is proven (HTTP → router → service → Postgres, nothing in the trust or
money path mocked):
  • a bounty paid by the creator, or by the deadline rule, gives the winner
    one 'bounty_won'; manual and automatic payouts racing write one event;
    a bounty refunded to its creator writes none
  • a contract approved, or auto-released, gives the contractor one
    'contract_completed'; the two racing write one; a reclaim writes none
  • a task or contract reclaimed after the work deadline gives the worker
    one 'deadline_missed' (−0.05), and the creator nothing
  • a creator account under a day old gives no positive credit
  • the daily cap still holds across task, bounty and contract credit
  • recalculate_agent_trust applies the new types to the score
  • calling a reporter again, or with no evidence in the ledger, writes nothing

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_paid_work_trust_db.py -v --db
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio

from src.services import contract_service, reputation
from src.services.auto_release import AUTO_RELEASE_DAYS

from .support import START_BALANCE, Agent
from .test_bounty_deadline_db import JUST_DUE, move_deadline as move_bounty_deadline, release
from .test_bounty_escrow_db import evaluate, open_bounty, submit
from .test_contract_deadline_db import (
    age_delivery, assigned_contract, move_deadline as move_contract_deadline, reclaim,
    submitted_contract,
)
from .test_task_escrow_db import assigned_task
from .test_task_reclaim_db import WORK_DAYS, taken_ago

pytestmark = pytest.mark.integration   # skipped unless --db is given

OLD = 30   # days: an account old enough to count as a counterparty


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest.fixture(autouse=True)
def reclaim_on(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "task_work_days", WORK_DAYS)


# ── Probes ────────────────────────────────────────────────────────────────────

async def events(pool, agent: Agent, event_type: str | None = None) -> list:
    return await pool.fetch(
        "SELECT event_type, event_weight, dedupe_key, counterparty_did FROM trust_events "
        "WHERE agent_id = $1 AND ($2::text IS NULL OR event_type = $2)",
        agent.agent_id, event_type,
    )


async def score(pool, agent: Agent) -> float:
    return float(await pool.fetchval(
        "SELECT trust_score FROM agents WHERE agent_id = $1", agent.agent_id))


async def scored_bounty(client, creator: Agent, winner: Agent) -> str:
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, winner)
    await evaluate(client, bounty_id, submission_id, creator, 0.9)
    return bounty_id


async def distribute(client, bounty_id: str, creator: Agent):
    return await client.post(f"/markets/bounties/{bounty_id}/distribute", headers=creator.headers)


# ── Bounties ──────────────────────────────────────────────────────────────────

async def test_a_paid_bounty_gives_the_winner_one_event(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    winner = await agents("winner", 0, age_days=OLD)
    bounty_id = await scored_bounty(client, creator, winner)

    assert (await distribute(client, bounty_id, creator)).status_code == 200

    rows = await events(pool, winner)
    assert [(r["event_type"], float(r["event_weight"]), r["dedupe_key"], r["counterparty_did"])
            for r in rows] == [("bounty_won", 0.05, f"bounty_won:{bounty_id}", creator.did)]
    assert await events(pool, creator) == []
    # Reporting it again (any path) is a no-op.
    assert await reputation.record_bounty_won(bounty_id) == reputation.DUPLICATE
    assert len(await events(pool, winner)) == 1


async def test_an_automatic_payout_counts_and_a_refund_does_not(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    winner = await agents("winner", 0, age_days=OLD)
    loser = await agents("loser", 0, age_days=OLD)

    paid = await scored_bounty(client, creator, winner)
    await move_bounty_deadline(pool, paid, JUST_DUE)
    assert (await release(paid))[0] == "rewarded"
    assert [r["event_type"] for r in await events(pool, winner)] == ["bounty_won"]

    refunded = await open_bounty(client, creator)
    await submit(client, refunded, loser)            # never scored
    await move_bounty_deadline(pool, refunded, JUST_DUE)
    assert (await release(refunded))[0] == "refunded"
    assert await reputation.record_bounty_won(refunded) == "not_rewarded"
    assert await events(pool, loser) == []
    assert await events(pool, creator) == []


async def test_manual_and_automatic_payouts_racing_write_one_event(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    for i in range(4):
        winner = await agents(f"winner{i}", 0, age_days=OLD)
        bounty_id = await scored_bounty(client, creator, winner)
        await move_bounty_deadline(pool, bounty_id, JUST_DUE)

        await asyncio.gather(
            release(bounty_id), distribute(client, bounty_id, creator),
            reputation.record_bounty_won(bounty_id),
            return_exceptions=True,
        )
        # Whichever path paid, and however the reports interleaved: one event.
        await reputation.record_bounty_won(bounty_id, source="late")
        assert [r["event_type"] for r in await events(pool, winner)] == ["bounty_won"]


async def test_a_bounty_from_a_just_created_account_gives_no_credit(client, pool, agents):
    creator = await agents("creator", START_BALANCE)          # under a day old
    winner = await agents("winner", 0, age_days=OLD)
    bounty_id = await scored_bounty(client, creator, winner)
    assert (await distribute(client, bounty_id, creator)).status_code == 200
    assert await reputation.record_bounty_won(bounty_id) == \
        reputation.COUNTERPARTY_NOT_ESTABLISHED
    assert await events(pool, winner) == []


async def test_an_open_bounty_gives_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    winner = await agents("winner", 0, age_days=OLD)
    bounty_id = await scored_bounty(client, creator, winner)
    assert await reputation.record_bounty_won(bounty_id) == "not_rewarded"
    assert await events(pool, winner) == []


# ── Contracts ─────────────────────────────────────────────────────────────────

async def test_an_approved_contract_gives_the_contractor_one_event(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    contractor = await agents("contractor", 0, age_days=OLD)
    contract_id = await submitted_contract(client, creator, contractor)

    resp = await client.post(f"/contracts/{contract_id}/complete", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    rows = await events(pool, contractor)
    assert [(r["event_type"], float(r["event_weight"]), r["dedupe_key"]) for r in rows] == [
        ("contract_completed", 0.05, f"contract_completed:{contract_id}")]
    assert await events(pool, creator) == []


async def test_an_auto_released_contract_counts_once_even_racing_approval(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    for i in range(4):
        contractor = await agents(f"contractor{i}", 0, age_days=OLD)
        contract_id = await submitted_contract(client, creator, contractor)
        await age_delivery(pool, contract_id, f"{AUTO_RELEASE_DAYS + 1} days")

        await asyncio.gather(
            contract_service.release_overdue_contract(UUID(contract_id)),
            client.post(f"/contracts/{contract_id}/complete", headers=creator.headers),
            return_exceptions=True,
        )
        await reputation.record_contract_completed(contract_id, source="late")
        assert [r["event_type"] for r in await events(pool, contractor)] == ["contract_completed"]


async def test_an_unpaid_contract_gives_nothing(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    contractor = await agents("contractor", 0, age_days=OLD)
    contract_id = await submitted_contract(client, creator, contractor)
    assert await reputation.record_contract_completed(contract_id) == "not_completed"
    assert await events(pool, contractor) == []


# ── Missed deadlines ──────────────────────────────────────────────────────────

async def test_a_reclaimed_contract_costs_the_contractor_and_pays_no_credit(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    contractor = await agents("contractor", 0, age_days=OLD)
    contract_id = await assigned_contract(client, creator, contractor)
    await move_contract_deadline(pool, contract_id, "-1 second")

    assert (await reclaim(client, contract_id, creator)).status_code == 200

    rows = await events(pool, contractor)
    assert [(r["event_type"], float(r["event_weight"]), r["dedupe_key"]) for r in rows] == [
        ("deadline_missed", -0.05, f"deadline_missed:contract:{contract_id}")]
    assert await reputation.record_contract_completed(contract_id) == "not_completed"
    assert await reputation.record_deadline_missed("contract", contract_id) == \
        reputation.DUPLICATE
    assert await events(pool, creator) == []


async def test_a_reclaimed_task_costs_the_worker_once(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    worker = await agents("worker", 0, age_days=OLD)
    task_id = await assigned_task(client, creator, worker, 100)
    await taken_ago(pool, task_id, f"{WORK_DAYS} days 1 minute")

    results = await asyncio.gather(*[
        client.post(f"/tasks/{task_id}/reclaim", headers=creator.headers) for _ in range(5)])
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]

    rows = await events(pool, worker)
    assert [(r["event_type"], r["dedupe_key"]) for r in rows] == [
        ("deadline_missed", f"deadline_missed:task:{task_id}")]
    assert await events(pool, creator) == []


async def test_no_deadline_missed_without_a_reclaim_in_the_ledger(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    worker = await agents("worker", 0, age_days=OLD)
    task_id = await assigned_task(client, creator, worker, 100)
    await taken_ago(pool, task_id, f"{WORK_DAYS} days 1 minute")     # overdue, not reclaimed
    contract_id = await assigned_contract(client, creator, worker)
    await move_contract_deadline(pool, contract_id, "-1 second")

    assert await reputation.record_deadline_missed("task", task_id) == "not_reclaimed"
    assert await reputation.record_deadline_missed("contract", contract_id) == "not_reclaimed"
    # A cancelled open contract was refunded, but not for a missed deadline.
    open_id = (await client.post(
        "/contracts", json={"title": "t", "description": "d", "budget": 10},
        headers=creator.headers)).json()["contract_id"]
    assert (await client.post(f"/contracts/{open_id}/cancel", headers=creator.headers)) \
        .status_code == 200
    assert await reputation.record_deadline_missed("contract", open_id) in (
        "not_reclaimed", "unknown_item")
    assert await events(pool, worker) == []


# ── Caps and replay ───────────────────────────────────────────────────────────

async def test_the_daily_cap_holds_across_bounties_and_contracts(client, pool, agents):
    worker = await agents("worker", 0, age_days=OLD)
    for i in range(3):
        creator = await agents(f"creator{i}", START_BALANCE, age_days=OLD)
        bounty_id = await scored_bounty(client, creator, worker)
        assert (await distribute(client, bounty_id, creator)).status_code == 200
        contract_id = await submitted_contract(client, creator, worker)
        assert (await client.post(f"/contracts/{contract_id}/complete",
                                  headers=creator.headers)).status_code == 200

    gained = sum(float(r["event_weight"]) for r in await events(pool, worker))
    assert gained == pytest.approx(reputation.MAX_DAILY_GAIN)


async def test_the_pair_cap_holds_per_type(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    worker = await agents("worker", 0, age_days=OLD)
    for _ in range(2):
        bounty_id = await scored_bounty(client, creator, worker)
        assert (await distribute(client, bounty_id, creator)).status_code == 200
    assert len(await events(pool, worker, "bounty_won")) == reputation.PAIR_DAILY_LIMIT


async def test_replay_applies_the_new_types(client, pool, agents):
    creator = await agents("creator", START_BALANCE, age_days=OLD)
    winner = await agents("winner", 0, age_days=OLD)
    late = await agents("late", 0, age_days=OLD)
    before_winner, before_late = await score(pool, winner), await score(pool, late)

    bounty_id = await scored_bounty(client, creator, winner)
    assert (await distribute(client, bounty_id, creator)).status_code == 200
    contract_id = await assigned_contract(client, creator, late)
    await move_contract_deadline(pool, contract_id, "-1 second")
    assert (await reclaim(client, contract_id, creator)).status_code == 200

    await reputation.recalculate_agent_trust()
    assert await score(pool, winner) == pytest.approx(round(before_winner + 0.05, 2))
    assert await score(pool, late) == pytest.approx(round(before_late - 0.05, 2))
