"""
Integration tests: the economy counters against REAL local Postgres.
Phase C, Sprint 23, EM-1.

Other test files share the database, so each test reads the counters, makes
its own rows (bounties and payouts through the API, collectives, members,
posts and the odd ledger row by hand), reads them again and checks the
change equals the hand count. What is proven:
  • joined / trusted: an outside agent counts; a FOUNDER, a roster DID and a
    SUSPENDED agent do not; trust counts only above 0.5
  • bounties: posted counts an outsider's bounty, not a founder's; paid
    counts a bounty the ledger paid to another agent (once, however many
    winners), not one paid only to its own creator, not one unpaid
  • collectives: formed with the outside owner plus one other ACTIVE member;
    a lone owner, a PENDING asker, and a founder-owned group do not count;
    a private group counts
  • posting: a visible post in the last 30 days counts the author once; a
    hidden, auto-generated, non-PUBLIC, removed or 31-day-old post does not
  • over HTTP: 404 while off; on, the six counters with their targets

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_economy_stats_db.py -v --db
"""
from __future__ import annotations

import uuid
from uuid import UUID

import pytest

from src.services import economy_stats, outside_agents

from .support import START_BALANCE
from .test_bounty_escrow_db import POOL, evaluate, open_bounty, submit

pytestmark = pytest.mark.integration   # skipped unless --db is given

URL = "/stats/economy"


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from unittest.mock import AsyncMock
    from src.middleware import response_cache
    monkeypatch.setattr(economy_stats.cache, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(economy_stats.cache, "cache_set", AsyncMock())
    response_cache.invalidate("")


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")


@pytest.fixture
def extra_house(monkeypatch):
    """Add DIDs to the founder roster the counters read."""
    extra: list[str] = []
    real = outside_agents.house_dids
    monkeypatch.setattr(economy_stats, "house_dids", lambda: sorted(set(real()) | set(extra)))
    return extra


async def counts() -> dict[str, int]:
    stats = await economy_stats.build_stats()
    return {k: getattr(stats, k).count for k in economy_stats.TARGETS}


async def delta(before: dict[str, int]) -> dict[str, int]:
    after = await counts()
    return {k: after[k] - before[k] for k in after}


ZERO = {k: 0 for k in economy_stats.TARGETS}


def expect(**changes) -> dict[str, int]:
    return {**ZERO, **changes}


# ── Agents ────────────────────────────────────────────────────────────────────

async def test_only_outside_agents_are_counted(pool, agents, extra_house):
    before = await counts()
    await agents("outsider")
    trusted = await agents("trusted")
    await pool.execute("UPDATE agents SET trust_score = 0.51 WHERE agent_did = $1", trusted.did)
    at_start = await agents("atstart")
    await pool.execute("UPDATE agents SET trust_score = 0.5 WHERE agent_did = $1", at_start.did)

    founder = await agents("founder", role="FOUNDER")
    roster = await agents("roster")
    extra_house.append(roster.did)
    suspended = await agents("suspended")
    for a in (founder, roster, suspended):
        await pool.execute("UPDATE agents SET trust_score = 0.9 WHERE agent_did = $1", a.did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1",
                       suspended.did)

    assert await delta(before) == expect(outside_agents_joined=3, outside_agents_trusted=1)


# ── Bounties ──────────────────────────────────────────────────────────────────

async def test_bounties_posted_and_paid_follow_the_ledger(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    winner, other = await agents("winner", 0), await agents("other", 0)
    founder = await agents("fcreator", START_BALANCE, role="FOUNDER")
    before = await counts()

    unpaid = await open_bounty(client, creator)
    await submit(client, unpaid, winner)

    paid = await open_bounty(client, creator)
    subs = [await submit(client, paid, agent) for agent in (winner, other)]
    for sub in subs:                         # two winners: still one bounty paid
        await evaluate(client, paid, sub, creator, 0.9)
    resp = await client.post(f"/markets/bounties/{paid}/distribute", headers=creator.headers)
    assert resp.status_code == 200, resp.text

    by_founder = await open_bounty(client, founder)
    sub = await submit(client, by_founder, winner)
    await evaluate(client, by_founder, sub, founder, 0.9)
    assert (await client.post(f"/markets/bounties/{by_founder}/distribute",
                              headers=founder.headers)).status_code == 200

    # Only a hand-written ledger row could pay a creator from its own bounty.
    self_paid = await open_bounty(client, creator)
    wallet = await pool.fetchval("SELECT wallet_id FROM wallets WHERE agent_id = $1",
                                 creator.agent_id)
    tx = await pool.fetchval(
        "INSERT INTO transactions (from_wallet, to_wallet, amount, type, related_id) "
        "VALUES (NULL, $1, $2, 'bounty_reward', $3) RETURNING transaction_id",
        wallet, POOL, UUID(self_paid))
    try:
        paid_rows = await pool.fetchval(
            "SELECT COUNT(DISTINCT related_id) FROM transactions "
            "WHERE related_id = $1 AND type = ANY($2::text[]) AND from_wallet IS NULL",
            UUID(paid), list(economy_stats.BOUNTY_PAYOUT_TYPES))
        assert paid_rows == 1
        assert await delta(before) == expect(bounties_posted=3, bounties_paid=1)
    finally:
        await pool.execute("DELETE FROM transactions WHERE transaction_id = $1", tx)


# ── Collectives ───────────────────────────────────────────────────────────────

async def group(pool, owner, members=(), is_public=True) -> uuid.UUID:
    """members: (agent, status) pairs besides the ACTIVE OWNER."""
    col = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO collectives (collective_id, name, description, is_public, owner_did)"
            " VALUES ($1, $2, 'a group', $3, $4)", col, f"S-{col.hex[:8]}", is_public, owner.did)
        await conn.execute(
            "INSERT INTO collective_members (collective_id, agent_did, role, status)"
            " VALUES ($1, $2, 'OWNER', 'ACTIVE')", col, owner.did)
        for agent, status in members:
            await conn.execute(
                "INSERT INTO collective_members (collective_id, agent_did, role, status)"
                " VALUES ($1, $2, 'MEMBER', $3)", col, agent.did, status)
    return col


async def test_a_collective_is_formed_with_an_outside_owner_and_another_active_member(
        pool, agents):
    owner, friend, asker = await agents("owner"), await agents("friend"), await agents("asker")
    founder = await agents("fowner", role="FOUNDER")
    before = await counts()

    await group(pool, owner, [(friend, "ACTIVE")])                     # formed
    await group(pool, owner, [(friend, "ACTIVE"), (asker, "ACTIVE")])  # formed, once
    await group(pool, owner, [(friend, "ACTIVE")], is_public=False)    # private: counted
    await group(pool, owner)                                           # lone owner
    await group(pool, owner, [(asker, "PENDING")])                     # only an asker
    await group(pool, owner, [(asker, "BANNED")])
    await group(pool, founder, [(friend, "ACTIVE")])                   # house-owned

    assert await delta(before) == expect(collectives_by_outsiders=3)


# ── Posting ───────────────────────────────────────────────────────────────────

async def post(pool, author, **cols) -> None:
    sets = {"visibility": "PUBLIC", "status": "ACTIVE", "is_auto_generated": False,
            "hidden_at": None, "age_days": 0, **cols}
    await pool.execute(
        "INSERT INTO posts (author_did, post_type, title, content, visibility, status,"
        " is_auto_generated, hidden_at, created_at)"
        " VALUES ($1, 'UPDATE', 'Update', $2, $3::post_visibility, $4, $5, $6,"
        "         NOW() - make_interval(days => $7))",
        author.did, f"post {uuid.uuid4().hex}", sets["visibility"], sets["status"],
        sets["is_auto_generated"], sets["hidden_at"], sets["age_days"])


async def test_posting_counts_authors_of_a_recent_visible_post(pool, agents):
    from datetime import datetime, timezone
    poster = await agents("poster")
    hidden, auto, private, removed, old = [await agents(n) for n in
                                           ("hidden", "auto", "private", "removed", "old")]
    founder = await agents("fposter", role="FOUNDER")
    before = await counts()

    await post(pool, poster)
    await post(pool, poster)                       # twice: still one agent
    await post(pool, hidden, hidden_at=datetime.now(timezone.utc))
    await post(pool, auto, is_auto_generated=True)
    await post(pool, private, visibility="COLLECTIVE")
    await post(pool, removed, status="CANCELLED")
    await post(pool, old, age_days=31)
    await post(pool, founder)

    assert await delta(before) == expect(outside_agents_posting=1)


# ── Over HTTP ─────────────────────────────────────────────────────────────────

async def test_http_off_then_on(client, monkeypatch):
    from src.config import get_settings
    assert (await client.get(URL)).status_code == 404
    monkeypatch.setattr(get_settings(), "economy_stats_enabled", "true")
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == set(economy_stats.TARGETS) | {"as_of"}
    assert body["bounties_paid"]["target"] == 5
    assert all(isinstance(body[k]["count"], int) and body[k]["count"] >= 0
               for k in economy_stats.TARGETS)
