"""
Integration tests: /wallets, /stakes, /economy against REAL local Postgres
Sprint 9, S9-7a — the proof behind enabling `wallets`, `stakes`, `economy`.

Every request goes HTTP → router → service → Postgres. Only the JWT check is
replaced (the caller is set per request); no money path is mocked. The
fixtures are in conftest.py.

What is proven:
  • tokens are created by a FOUNDER only (treasury mint, wallet grant), and
    every creation is in the ledger and in token_supply.total_minted; a mint
    is always labelled 'mint', whatever reason the caller gives
  • only a FOUNDER can slash a stake; a stake is slashed once, however often
    or however concurrently it is tried
  • a stake goes back to its owner, and only to its owner, once, and not
    before its lock period ends; a release racing a slash pays one side only
  • transfers come out of the caller's own wallet, never overdraw it, never
    deadlock when two agents pay each other at the same moment, and cannot be
    sent to oneself
  • the task fee is taken from the escrow that is really there
  • nobody acts without a login
  • tokens are conserved: apart from a FOUNDER's mint or grant, the total of
    wallets + escrow + stakes never changes

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from .support import START_BALANCE, Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

STAKE = 300


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    """The app creates the treasury at startup; the test client does not run
    startup, so do the same (idempotent) call here."""
    from src.services import economy_service
    await economy_service.initialize_treasury()


# ── DB probes ─────────────────────────────────────────────────────────────────

async def treasury_balance(pool) -> int:
    return await pool.fetchval("SELECT balance FROM wallets WHERE wallet_type = 'treasury'")


async def total_minted(pool) -> int:
    return await pool.fetchval("SELECT total_minted FROM token_supply")


async def stake_row(pool, stake_id: str):
    return await pool.fetchrow(
        "SELECT agent_id, amount, released_at FROM stakes WHERE stake_id = $1", UUID(stake_id),
    )


async def ledger(pool, related_id: str, tx_type: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM transactions WHERE related_id = $1 AND type = $2",
        UUID(related_id), tx_type,
    )


async def slashes(pool, stake_id: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM stake_slashes WHERE stake_id = $1", UUID(stake_id))


# ── Flow helpers ──────────────────────────────────────────────────────────────

async def stake(client, owner: Agent, amount: int = STAKE, locked_until: datetime | None = None) -> str:
    body: dict = {"amount": amount}
    if locked_until is not None:
        body["locked_until"] = locked_until.isoformat()
    resp = await client.post("/stakes", json=body, headers=owner.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["stake_id"]


def release(client, stake_id: str, caller: Agent):
    return client.post(f"/stakes/{stake_id}/release", headers=caller.headers)


def slash(client, stake_id: str, caller: Agent):
    return client.post(
        "/economy/slash", json={"stake_id": stake_id, "reason": "test"}, headers=caller.headers,
    )


def transfer(client, sender: Agent, receiver: Agent, amount: int):
    return client.post(
        "/wallets/transfer",
        json={"to_id": str(receiver.agent_id), "amount": amount},
        headers=sender.headers,
    )


# ── Nobody acts without a login ───────────────────────────────────────────────

async def test_no_money_write_without_a_login(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    other = await agents("other", 0)
    stake_id = await stake(client, owner)
    before = await total_tokens(pool)
    minted = await total_minted(pool)

    calls = [
        ("/economy/mint", {"amount": 1000}),
        ("/economy/slash", {"stake_id": stake_id, "reason": "x"}),
        (f"/stakes/{stake_id}/release", None),
        ("/stakes", {"agent_id": str(owner.agent_id), "amount": 10}),
        ("/wallets/transfer",
         {"from_id": str(owner.agent_id), "to_id": str(other.agent_id), "amount": 10}),
        ("/wallets", {"agent_id": str(other.agent_id), "initial_balance": 1000}),
        ("/wallets/by-did", {"agent_did": other.did, "initial_balance": 1000}),
    ]
    for path, body in calls:
        resp = await client.post(path, json=body)
        assert resp.status_code == 401, (path, resp.status_code, resp.text)

    assert (await stake_row(pool, stake_id))["released_at"] is None
    assert await balance(pool, owner) == START_BALANCE - STAKE
    assert await balance(pool, other) == 0
    assert await total_tokens(pool) == before
    assert await total_minted(pool) == minted


# ── Creating tokens: FOUNDER only, always on the record ───────────────────────

async def test_member_cannot_mint(client, pool, agents):
    """The hole S9-7a found: POST /economy/mint only asked for a login."""
    member = await agents("member", 0)
    before = (await treasury_balance(pool), await total_minted(pool), await total_tokens(pool))

    resp = await client.post(
        "/economy/mint", json={"amount": 1_000_000, "reason": "genesis"}, headers=member.headers,
    )

    assert resp.status_code == 403
    assert (await treasury_balance(pool), await total_minted(pool), await total_tokens(pool)) == before


async def test_founder_mint_goes_to_the_treasury_and_is_labelled_mint(client, pool, agents):
    founder = await agents("founder", 0, role="FOUNDER")
    treasury_before, minted_before = await treasury_balance(pool), await total_minted(pool)
    total_before = await total_tokens(pool)
    ledger_before = await pool.fetchval("SELECT COUNT(*) FROM transactions")

    # The caller's reason used to become the ledger type.
    resp = await client.post(
        "/economy/mint", json={"amount": 500, "reason": "escrow_release"}, headers=founder.headers,
    )

    assert resp.status_code == 200, resp.text
    assert await treasury_balance(pool) == treasury_before + 500
    assert await total_minted(pool) == minted_before + 500
    assert await total_tokens(pool) == total_before + 500
    rows = await pool.fetch(
        "SELECT from_wallet, type, amount FROM transactions ORDER BY timestamp DESC LIMIT $1",
        await pool.fetchval("SELECT COUNT(*) FROM transactions") - ledger_before,
    )
    assert [(r["from_wallet"], r["type"], r["amount"]) for r in rows] == [(None, "mint", 500)]


async def test_member_cannot_fund_a_wallet(client, pool, agents):
    member = await agents("member", 0)
    friend = await agents("friend", 0)
    before, minted = await total_tokens(pool), await total_minted(pool)

    own = await client.post("/wallets", json={"initial_balance": 500}, headers=member.headers)
    other = await client.post(
        "/wallets/by-did", json={"agent_did": friend.did, "initial_balance": 500},
        headers=member.headers,
    )

    assert (own.status_code, other.status_code) == (403, 403)
    assert await balance(pool, member) == 0
    assert await balance(pool, friend) == 0
    assert (await total_tokens(pool), await total_minted(pool)) == (before, minted)


async def test_founder_grant_is_in_the_ledger_and_the_supply(client, pool, agents):
    founder = await agents("founder", 0, role="FOUNDER")
    member = await agents("member")          # no wallet yet
    before, minted = await total_tokens(pool), await total_minted(pool)

    resp = await client.post(
        "/wallets", json={"agent_id": str(member.agent_id), "initial_balance": 250},
        headers=founder.headers,
    )

    assert resp.status_code == 200, resp.text
    assert await balance(pool, member) == 250
    assert await total_minted(pool) == minted + 250
    assert await total_tokens(pool) == before + 250
    grants = await pool.fetch(
        "SELECT from_wallet, amount FROM transactions WHERE to_wallet = $1 AND type = 'grant'",
        UUID(resp.json()["wallet_id"]),
    )
    assert [(g["from_wallet"], g["amount"]) for g in grants] == [(None, 250)]


async def test_a_wallet_opened_at_zero_creates_nothing(client, pool, agents):
    member = await agents("member")          # no wallet yet
    before, minted = await total_tokens(pool), await total_minted(pool)
    ledger_before = await pool.fetchval("SELECT COUNT(*) FROM transactions")

    resp = await client.post("/wallets", json={}, headers=member.headers)

    assert resp.status_code == 200, resp.text
    assert await balance(pool, member) == 0
    assert (await total_tokens(pool), await total_minted(pool)) == (before, minted)
    assert await pool.fetchval("SELECT COUNT(*) FROM transactions") == ledger_before


# ── Slashing: FOUNDER only, once ──────────────────────────────────────────────

async def test_member_cannot_slash_another_agents_stake(client, pool, agents):
    """The hole S9-7a found: any logged-in agent could forfeit anyone's stake."""
    owner = await agents("owner", START_BALANCE)
    attacker = await agents("attacker", 0)
    stake_id = await stake(client, owner)
    treasury_before = await treasury_balance(pool)

    resp = await slash(client, stake_id, attacker)
    own = await slash(client, stake_id, owner)     # not even one's own

    assert (resp.status_code, own.status_code) == (403, 403)
    assert (await stake_row(pool, stake_id))["released_at"] is None
    assert await slashes(pool, stake_id) == 0
    assert await treasury_balance(pool) == treasury_before


async def test_founder_slash_moves_the_stake_to_the_treasury(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    founder = await agents("founder", 0, role="FOUNDER")
    stake_id = await stake(client, owner)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    resp = await slash(client, stake_id, founder)

    assert resp.status_code == 200, resp.text
    assert (await stake_row(pool, stake_id))["released_at"] is not None
    assert await treasury_balance(pool) == treasury_before + STAKE
    assert await balance(pool, owner) == START_BALANCE - STAKE
    assert await slashes(pool, stake_id) == 1
    assert await ledger(pool, stake_id, "slash") == 1
    assert await total_tokens(pool) == before

    again = await slash(client, stake_id, founder)
    assert again.status_code == 409
    assert await treasury_balance(pool) == treasury_before + STAKE


async def test_concurrent_slashes_credit_the_treasury_once(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    founder = await agents("founder", 0, role="FOUNDER")
    stake_id = await stake(client, owner)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    responses = await asyncio.gather(*[slash(client, stake_id, founder) for _ in range(12)])

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 11, codes
    assert await treasury_balance(pool) == treasury_before + STAKE
    assert await slashes(pool, stake_id) == 1
    assert await ledger(pool, stake_id, "slash") == 1
    assert await total_tokens(pool) == before


async def test_slash_of_an_unknown_stake_is_404(client, pool, agents):
    founder = await agents("founder", 0, role="FOUNDER")
    resp = await slash(client, str(uuid4()), founder)
    assert resp.status_code == 404


# ── Releasing a stake: its owner only, once, after the lock ───────────────────

async def test_owner_gets_the_stake_back(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    stake_id = await stake(client, owner)
    before = await total_tokens(pool)
    assert await balance(pool, owner) == START_BALANCE - STAKE

    resp = await release(client, stake_id, owner)

    assert resp.status_code == 200, resp.text
    assert resp.json()["balance"] == START_BALANCE
    assert await balance(pool, owner) == START_BALANCE
    assert (await stake_row(pool, stake_id))["released_at"] is not None
    assert await ledger(pool, stake_id, "unstake") == 1
    assert await total_tokens(pool) == before

    again = await release(client, stake_id, owner)
    assert again.status_code == 409
    assert await balance(pool, owner) == START_BALANCE


async def test_nobody_else_can_release_a_stake(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    other = await agents("other", 0)
    founder = await agents("founder", 0, role="FOUNDER")
    stake_id = await stake(client, owner)

    for caller in (other, founder):
        resp = await release(client, stake_id, caller)
        assert resp.status_code == 403, (caller.role, resp.text)

    assert (await stake_row(pool, stake_id))["released_at"] is None
    assert await balance(pool, owner) == START_BALANCE - STAKE
    assert await balance(pool, other) == 0
    assert await balance(pool, founder) == 0


async def test_a_locked_stake_cannot_be_released_early(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    now = datetime.now(timezone.utc)
    locked = await stake(client, owner, 100, locked_until=now + timedelta(days=30))
    expired = await stake(client, owner, 100, locked_until=now - timedelta(seconds=5))

    early = await release(client, locked, owner)
    late = await release(client, expired, owner)

    assert early.status_code == 409
    assert (await stake_row(pool, locked))["released_at"] is None
    assert late.status_code == 200, late.text
    assert await balance(pool, owner) == START_BALANCE - 100


async def test_concurrent_releases_pay_once(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    stake_id = await stake(client, owner)
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[release(client, stake_id, owner) for _ in range(12)])

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 11, codes
    assert await balance(pool, owner) == START_BALANCE
    assert await ledger(pool, stake_id, "unstake") == 1
    assert await total_tokens(pool) == before


async def test_release_racing_slash_pays_one_side_only(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    founder = await agents("founder", 0, role="FOUNDER")
    stake_id = await stake(client, owner)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    calls = []
    for _ in range(6):
        calls += [release(client, stake_id, owner), slash(client, stake_id, founder)]
    responses = await asyncio.gather(*calls)

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 11, codes
    to_owner = await balance(pool, owner) - (START_BALANCE - STAKE)
    to_treasury = await treasury_balance(pool) - treasury_before
    assert sorted([to_owner, to_treasury]) == [0, STAKE]
    assert await ledger(pool, stake_id, "unstake") + await ledger(pool, stake_id, "slash") == 1
    assert await total_tokens(pool) == before


async def test_release_of_an_unknown_stake_is_404(client, pool, agents):
    owner = await agents("owner", 0)
    resp = await release(client, str(uuid4()), owner)
    assert resp.status_code == 404


# ── Staking and transfers: the caller's own wallet, never overdrawn ───────────

async def test_cannot_stake_or_transfer_from_another_agents_wallet(client, pool, agents):
    victim = await agents("victim", START_BALANCE)
    attacker = await agents("attacker", 0)
    stakes_before = await pool.fetchval("SELECT COUNT(*) FROM stakes")

    staked = await client.post(
        "/stakes", json={"agent_id": str(victim.agent_id), "amount": 100}, headers=attacker.headers,
    )
    moved = await client.post(
        "/wallets/transfer",
        json={"from_id": str(victim.agent_id), "to_id": str(attacker.agent_id), "amount": 100},
        headers=attacker.headers,
    )

    assert (staked.status_code, moved.status_code) == (403, 403)
    assert await balance(pool, victim) == START_BALANCE
    assert await balance(pool, attacker) == 0
    assert await pool.fetchval("SELECT COUNT(*) FROM stakes") == stakes_before


async def test_concurrent_stakes_cannot_overdraw_the_wallet(client, pool, agents):
    owner = await agents("owner", 250)
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[
        client.post("/stakes", json={"amount": 100}, headers=owner.headers) for _ in range(10)
    ])

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 2 + [400] * 8, codes
    assert await balance(pool, owner) == 50
    assert await total_tokens(pool) == before


async def test_concurrent_transfers_cannot_overdraw_the_wallet(client, pool, agents):
    sender = await agents("sender", 100)
    receiver = await agents("receiver", 0)
    before = await total_tokens(pool)

    responses = await asyncio.gather(*[transfer(client, sender, receiver, 10) for _ in range(20)])

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] * 10 + [400] * 10, codes
    assert await balance(pool, sender) == 0
    assert await balance(pool, receiver) == 100
    assert await total_tokens(pool) == before


async def test_two_agents_paying_each_other_at_once_do_not_deadlock(client, pool, agents):
    """A→B and B→A each used to lock their own wallet, then wait for the
    other's: Postgres broke the deadlock by failing one request."""
    a = await agents("a", START_BALANCE)
    b = await agents("b", START_BALANCE)
    before = await total_tokens(pool)

    calls = []
    for _ in range(15):
        calls += [transfer(client, a, b, 7), transfer(client, b, a, 3)]
    responses = await asyncio.gather(*calls)

    codes = {r.status_code for r in responses}
    assert codes == {200}, sorted(r.status_code for r in responses)
    assert await balance(pool, a) == START_BALANCE - 15 * 7 + 15 * 3
    assert await balance(pool, b) == START_BALANCE + 15 * 7 - 15 * 3
    assert await total_tokens(pool) == before


async def test_cannot_transfer_to_oneself(client, pool, agents):
    owner = await agents("owner", START_BALANCE)
    ledger_before = await pool.fetchval("SELECT COUNT(*) FROM transactions")

    resp = await transfer(client, owner, owner, 10)

    assert resp.status_code == 400
    assert await balance(pool, owner) == START_BALANCE
    assert await pool.fetchval("SELECT COUNT(*) FROM transactions") == ledger_before


async def test_transfer_to_an_agent_without_a_wallet_moves_nothing(client, pool, agents):
    sender = await agents("sender", START_BALANCE)
    walletless = await agents("walletless")
    before = await total_tokens(pool)

    resp = await transfer(client, sender, walletless, 10)

    assert resp.status_code == 400
    assert await balance(pool, sender) == START_BALANCE
    assert await total_tokens(pool) == before


# ── Task fee: taken from the escrow that is really there ──────────────────────

async def test_task_fee_goes_to_the_treasury_out_of_the_reward(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    resp = await client.post(
        "/tasks", json={"task_type": "fee.test", "reward": 1000}, headers=creator.headers,
    )
    assert resp.status_code == 201, resp.text

    row = await pool.fetchrow(
        "SELECT escrowed_reward, task_fee FROM tasks WHERE task_id = $1",
        UUID(resp.json()["task_id"]),
    )
    assert (row["escrowed_reward"], row["task_fee"]) == (975, 25)     # 2.5 %
    assert await treasury_balance(pool) == treasury_before + 25
    assert await balance(pool, creator) == START_BALANCE - 1000
    assert await total_tokens(pool) == before


async def test_no_fee_once_the_escrow_has_been_paid_out(client, pool, agents):
    """The fee is collected in a second step after the escrow. If the reward
    was paid out in between, the old code still credited the treasury —
    tokens from nothing."""
    from src.services import economy_service, token_service

    creator = await agents("creator", START_BALANCE)
    executor = await agents("executor", 0)
    resp = await client.post(
        "/tasks", json={"task_type": "fee.test", "reward": 1000}, headers=creator.headers,
    )
    task_id = UUID(resp.json()["task_id"])
    await token_service.release_task_escrow(task_id, executor.agent_id)
    assert await balance(pool, executor) == 975
    treasury_before, before = await treasury_balance(pool), await total_tokens(pool)

    fee = await economy_service.collect_task_fee(task_id, 1000)

    assert fee == 0
    assert await treasury_balance(pool) == treasury_before
    assert await total_tokens(pool) == before
