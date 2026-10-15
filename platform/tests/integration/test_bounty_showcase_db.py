"""
Integration tests: the bounty showcase against REAL local Postgres.
Phase C, Sprint 21, BT-4.

What is proven (real bounties, contracts and ledger rows made through the API
and the auto-release rule; only the list sizes widened, because other test
files share the database):
  • open bounties: only status 'open' with the deadline not passed, with the
    right submission count; a paid, refunded or past-deadline bounty is not
    listed
  • recently paid: a manual and an automatic payout, each with the amount the
    ledger paid the winner; a refund is not a payout; a payout older than 30
    days is not listed
  • top earners: each agent's total equals its bounty + contract payouts in
    the ledger over 30 days; a payment to a bounty's own creator and an agent
    that is not ACTIVE are left out
  • over HTTP: 404 while off; with it on, no wallet id or submission content
    anywhere in the answer

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_bounty_showcase_db.py -v --db
"""
from __future__ import annotations

from uuid import UUID

import pytest

from src.services.markets import showcase_service

from .support import START_BALANCE, Agent
from .test_bounty_deadline_db import JUST_DUE, move_deadline, release
from .test_bounty_escrow_db import POOL, evaluate, open_bounty, submit
from .test_contract_deadline_db import BUDGET, submitted_contract

pytestmark = pytest.mark.integration   # skipped unless --db is given

URL = "/markets/bounties/showcase"
_EARNING_TYPES = list(showcase_service.BOUNTY_PAYOUT_TYPES) + list(
    showcase_service.CONTRACT_PAYOUT_TYPES)


@pytest.fixture(autouse=True)
def wide_lists(monkeypatch):
    """Other test files leave bounties and payouts behind: list everything."""
    for name in ("OPEN_LIMIT", "PAID_LIMIT", "EARNERS_LIMIT"):
        monkeypatch.setattr(showcase_service, name, 100_000)


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from unittest.mock import AsyncMock
    from src.middleware import response_cache
    monkeypatch.setattr(showcase_service.cache, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(showcase_service.cache, "cache_set", AsyncMock())
    response_cache.invalidate("")


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")


def turn_on(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "economy_showcase_enabled", "true")


async def paid_bounty(client, creator: Agent, winner: Agent) -> str:
    bounty_id = await open_bounty(client, creator)
    submission_id = await submit(client, bounty_id, winner)
    await evaluate(client, bounty_id, submission_id, creator, 0.9)
    return bounty_id


async def ledger_earned(pool, agent: Agent) -> int:
    """What the ledger paid *agent* out of escrow in the last 30 days."""
    return int(await pool.fetchval(
        """
        SELECT COALESCE(SUM(tx.amount), 0) FROM transactions tx
        JOIN wallets w ON w.wallet_id = tx.to_wallet
        WHERE w.agent_id = $1 AND tx.from_wallet IS NULL AND tx.type = ANY($2::text[])
          AND tx.timestamp >= CURRENT_TIMESTAMP - interval '30 days'
        """,
        agent.agent_id, _EARNING_TYPES,
    ))


def by_bounty(rows, bounty_id: str):
    return [r for r in rows if str(r.bounty_id) == bounty_id]


# ── Open bounties ─────────────────────────────────────────────────────────────

async def test_open_bounties_are_only_those_still_taking_submissions(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    a, b = await agents("a", 0), await agents("b", 0)

    open_one = await open_bounty(client, creator)
    await submit(client, open_one, a)
    await submit(client, open_one, b)
    past = await open_bounty(client, creator)
    await move_deadline(pool, past, "-1 second")
    paid = await paid_bounty(client, creator, a)
    assert (await client.post(f"/markets/bounties/{paid}/distribute",
                              headers=creator.headers)).status_code == 200
    cancelled = await open_bounty(client, creator)
    assert (await client.post(f"/markets/bounties/{cancelled}/cancel",
                              headers=creator.headers)).status_code == 200

    show = await showcase_service.build_showcase()
    [row] = by_bounty(show.open_bounties, open_one)
    assert (row.reward_pool, row.submission_count, row.title) == (POOL, 2, "escrow test")
    for gone in (past, paid, cancelled):
        assert by_bounty(show.open_bounties, gone) == []

    expected = await pool.fetchrow(
        "SELECT COUNT(*) AS n, COALESCE(SUM(reward_pool), 0) AS total FROM capability_bounties "
        "WHERE status = 'open' AND (deadline IS NULL OR deadline > CURRENT_TIMESTAMP)")
    assert (show.open_count, show.open_pool_total) == (expected["n"], expected["total"])
    assert show.open_count == len(show.open_bounties)


# ── Recently paid ─────────────────────────────────────────────────────────────

async def test_recently_paid_lists_manual_and_automatic_payouts_only(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    w1, w2, loser = await agents("w1", 0), await agents("w2", 0), await agents("loser", 0)

    manual = await paid_bounty(client, creator, w1)
    assert (await client.post(f"/markets/bounties/{manual}/distribute",
                              headers=creator.headers)).status_code == 200
    automatic = await paid_bounty(client, creator, w2)
    await move_deadline(pool, automatic, JUST_DUE)
    assert (await release(automatic))[0] == "rewarded"
    refunded = await open_bounty(client, creator)
    await submit(client, refunded, loser)
    await move_deadline(pool, refunded, JUST_DUE)
    assert (await release(refunded))[0] == "refunded"

    show = await showcase_service.build_showcase()
    [m] = by_bounty(show.recently_paid, manual)
    [a] = by_bounty(show.recently_paid, automatic)
    assert (m.how, m.amount, m.winner_did) == ("manual", POOL, w1.did)
    assert (a.how, a.amount, a.winner_did) == ("automatic", POOL, w2.did)
    assert by_bounty(show.recently_paid, refunded) == []

    # A payout older than the window drops off.
    await pool.execute(
        "UPDATE transactions SET timestamp = CURRENT_TIMESTAMP - interval '31 days' "
        "WHERE related_id = $1 AND type = 'bounty_reward'", UUID(manual))
    show = await showcase_service.build_showcase()
    assert by_bounty(show.recently_paid, manual) == []
    assert len(by_bounty(show.recently_paid, automatic)) == 1


# ── Top earners ───────────────────────────────────────────────────────────────

async def test_top_earners_match_the_ledger(client, pool, agents):
    creator = await agents("creator", START_BALANCE * 3)
    worker = await agents("worker", 0)
    other = await agents("other", 0)

    for _ in range(2):
        bounty_id = await paid_bounty(client, creator, worker)
        assert (await client.post(f"/markets/bounties/{bounty_id}/distribute",
                                  headers=creator.headers)).status_code == 200
    contract_id = await submitted_contract(client, creator, worker)
    assert (await client.post(f"/contracts/{contract_id}/complete",
                              headers=creator.headers)).status_code == 200
    bounty_id = await paid_bounty(client, creator, other)
    assert (await client.post(f"/markets/bounties/{bounty_id}/distribute",
                              headers=creator.headers)).status_code == 200

    show = await showcase_service.build_showcase()
    earners = {e.agent_did: e for e in show.top_earners}
    w = earners[worker.did]
    assert w.earned == await ledger_earned(pool, worker) == 2 * POOL + BUDGET
    assert (w.bounty_payouts, w.contract_payouts) == (2, 1)
    assert earners[other.did].earned == await ledger_earned(pool, other) == POOL
    assert creator.did not in earners
    # Ordered by earnings.
    totals = [e.earned for e in show.top_earners]
    assert totals == sorted(totals, reverse=True)

    # Not ACTIVE: off the board (and off the paid list).
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_id = $1",
                       other.agent_id)
    show = await showcase_service.build_showcase()
    assert other.did not in {e.agent_did for e in show.top_earners}
    assert by_bounty(show.recently_paid, bounty_id) == []


async def test_a_payment_to_the_bounty_creator_is_not_earnings(client, pool, agents):
    """No API path pays a creator from their own bounty; a ledger row that did
    (written here by hand, then removed) must still not count."""
    creator = await agents("selfdealer", START_BALANCE)
    bounty_id = await open_bounty(client, creator)
    wallet_id = await pool.fetchval("SELECT wallet_id FROM wallets WHERE agent_id = $1",
                                    creator.agent_id)
    tx_id = await pool.fetchval(
        "INSERT INTO transactions (from_wallet, to_wallet, amount, type, related_id) "
        "VALUES (NULL, $1, $2, 'bounty_reward', $3) RETURNING transaction_id",
        wallet_id, POOL, UUID(bounty_id))
    try:
        show = await showcase_service.build_showcase()
        assert creator.did not in {e.agent_did for e in show.top_earners}
        assert by_bounty(show.recently_paid, bounty_id) == []
    finally:
        await pool.execute("DELETE FROM transactions WHERE transaction_id = $1", tx_id)


# ── Over HTTP ─────────────────────────────────────────────────────────────────

async def test_http_off_is_404_and_on_leaks_no_private_field(client, pool, agents, monkeypatch):
    creator = await agents("creator", START_BALANCE)
    winner = await agents("winner", 0)
    bounty_id = await paid_bounty(client, creator, winner)
    assert (await client.post(f"/markets/bounties/{bounty_id}/distribute",
                              headers=creator.headers)).status_code == 200

    assert (await client.get(URL)).status_code == 404

    turn_on(monkeypatch)
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    text = resp.text
    assert bounty_id in text and winner.did in text
    wallets = await pool.fetch("SELECT wallet_id FROM wallets WHERE agent_id = ANY($1::uuid[])",
                               [creator.agent_id, winner.agent_id])
    for w in wallets:
        assert str(w["wallet_id"]) not in text
    for secret in ('"answer"', "solution_data", "description", str(creator.agent_id),
                   str(winner.agent_id)):
        assert secret not in text
