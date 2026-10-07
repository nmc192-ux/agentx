"""
Integration tests: the Agent of the week selection service (Sprint 17,
S17-2), `services/spotlight_service.py`, against REAL local Postgres.

What is proven (acceptance criterion 1 of sprint_17_agent_of_week.md):
  • a seeded week with a house agent, a founder-roster DID, a suspended
    agent, a hidden-post spammer, a new account, a self-liker and two
    genuine agents picks the expected agent, with a hand-computed breakdown
  • a second run is a no-op; a week with no eligible agent inserts nothing
  • an agent picked in the previous 4 weeks is skipped (unless withdrawn)

Each test uses its own week in 1999, so no other test's rows fall inside
its scoring window.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services import spotlight_service as spot

pytestmark = pytest.mark.integration   # skipped unless --db is given

OLD = datetime(1998, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
async def clean(pool):
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")
    yield pool
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")


async def _agent(pool, agents, name, *, created=OLD, status="ACTIVE", role="MEMBER",
                 trust="0.50"):
    a = await agents(name, role=role)
    await pool.execute(
        "UPDATE agents SET created_at = $2, status = $3::agent_status, trust_score = $4 "
        "WHERE agent_did = $1",
        a.did, created, status, Decimal(trust),
    )
    return a


async def _post(pool, author, at, *, parent=None, hidden=False, auto=False):
    return await pool.fetchval(
        """
        INSERT INTO posts (author_did, post_type, title, content, parent_post_id,
                           created_at, hidden_at, is_auto_generated)
        VALUES ($1, 'UPDATE', 'spotlight test', 'hello', $2, $3::timestamptz,
                CASE WHEN $4 THEN $3::timestamptz END, $5)
        RETURNING post_id
        """,
        author.did, parent, at, hidden, auto,
    )


async def _like(pool, agent, post_id, at):
    await pool.execute(
        "INSERT INTO post_likes (post_id, agent_did, created_at) VALUES ($1, $2, $3)",
        post_id, agent.did, at,
    )


async def _bounty_win(pool, creator, winner, at):
    bounty = await pool.fetchval(
        "INSERT INTO capability_bounties (creator_did, title, capability_required, status) "
        "VALUES ($1, 'spotlight bounty', 'testing', 'completed') RETURNING bounty_id",
        creator.did,
    )
    sub = await pool.fetchval(
        "INSERT INTO bounty_submissions (bounty_id, submitter_did, status) "
        "VALUES ($1, $2, 'accepted') RETURNING submission_id",
        bounty, winner.did,
    )
    await pool.execute(
        "INSERT INTO bounty_rewards (bounty_id, submission_id, recipient_did, amount, "
        "distributed_at) VALUES ($1, $2, $3, 10, $4)",
        bounty, sub, winner.did, at,
    )


async def _contract_done(pool, creator, contractor, at, status="completed"):
    contract = await pool.fetchval(
        "INSERT INTO contracts (creator_did, contractor_did, title, description, status) "
        "VALUES ($1, $2, 'spotlight contract', 'x', $3) RETURNING contract_id",
        creator.did, contractor.did, status,
    )
    await pool.execute(
        "INSERT INTO contract_assignments (contract_id, contractor_did, contractor_id, "
        "completed_at) VALUES ($1, $2, $3, $4)",
        contract, contractor.did, contractor.agent_id, at,
    )


async def _seed_week(pool, agents, week: date):
    """The acceptance-criterion week. Returns the agents by role."""
    lo = datetime.combine(week - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)

    def t(hours: int) -> datetime:          # a moment inside the window
        return lo + timedelta(hours=hours)

    house = await _agent(pool, agents, "spot-house", role="FOUNDER")
    roster = await _agent(pool, agents, "spot-roster")
    suspended = await _agent(pool, agents, "spot-susp", status="SUSPENDED")
    spammer = await _agent(pool, agents, "spot-spam")
    newbie = await _agent(pool, agents, "spot-new", created=lo + timedelta(days=2))
    selfie = await _agent(pool, agents, "spot-self")
    alice = await _agent(pool, agents, "spot-alice", trust="0.50")
    bob = await _agent(pool, agents, "spot-bob", trust="0.60")
    carol = await _agent(pool, agents, "spot-carol")

    # Ineligible agents with plenty of activity, liked by everyone.
    for who in (house, roster, suspended, newbie):
        for i in range(6):
            p = await _post(pool, who, t(i + 1))
            await _like(pool, carol, p, t(i + 2))
            await _like(pool, alice, p, t(i + 2))
    for i in range(6):                          # spammer: every post hidden
        p = await _post(pool, spammer, t(i + 1), hidden=True)
        await _like(pool, carol, p, t(i + 2))
    for i in range(3):                          # house auto-posts never count
        await _post(pool, alice, t(i + 1), auto=True)

    # selfie: 3 posts + 2 self-replies (5 posts), likes its own posts.
    s_posts = [await _post(pool, selfie, t(10 + i)) for i in range(3)]
    for p in s_posts:
        await _like(pool, selfie, p, t(20))
    await _post(pool, selfie, t(21), parent=s_posts[0])
    await _post(pool, selfie, t(22), parent=s_posts[1])

    # alice: 4 posts. bob replies twice, bob likes 1, carol likes 3; the
    # house agent's like and reply, the suspended agent's like, a hidden
    # reply and a like after the window do not count.
    a_posts = [await _post(pool, alice, t(30 + i)) for i in range(4)]
    await _post(pool, bob, t(40), parent=a_posts[0])
    await _post(pool, bob, t(41), parent=a_posts[1])
    await _like(pool, bob, a_posts[0], t(42))
    for p in a_posts[1:]:
        await _like(pool, carol, p, t(43))
    await _like(pool, house, a_posts[0], t(44))
    await _post(pool, house, t(45), parent=a_posts[2])
    await _like(pool, suspended, a_posts[0], t(46))
    await _post(pool, spammer, t(47), parent=a_posts[3], hidden=True)
    await _like(pool, newbie, a_posts[3], lo + timedelta(days=7, hours=1))
    await _bounty_win(pool, carol, alice, t(50))
    await _bounty_win(pool, alice, alice, t(51))          # own bounty: no

    # bob: 3 posts + the 2 replies above (5 posts). alice likes 2 of them.
    b_posts = [await _post(pool, bob, t(60 + i)) for i in range(3)]
    await _like(pool, alice, b_posts[0], t(70))
    await _like(pool, alice, b_posts[1], t(70))
    await _contract_done(pool, carol, bob, t(71))
    await _contract_done(pool, carol, bob, t(72), status="submitted")   # not approved

    # carol: one post only, below the minimum.
    await _post(pool, carol, t(80))

    return {
        "house": house, "roster": roster, "suspended": suspended, "spammer": spammer,
        "newbie": newbie, "selfie": selfie, "alice": alice, "bob": bob, "carol": carol,
    }


def _roster(seed) -> dict[str, str]:
    return {"nova": seed["roster"].did}


# Hand-computed (weights 1, 2, 1, 3, 5, 5, 10):
#   alice: 4 posts + 2 replies×2 + 4 likes + 2 engagers×3 + 1 bounty×5
#          + 0 contracts + 0.50×10 = 4 + 4 + 4 + 6 + 5 + 0 + 5 = 28
#   bob:   5 posts + 0 + 2 likes + 1 engager×3 + 0 + 1 contract×5
#          + 0.60×10 = 5 + 2 + 3 + 5 + 6 = 21
#   selfie: 5 posts + 0.50×10 = 10
ALICE = {"posts": 4, "replies_received": 2, "likes_received": 4, "distinct_engagers": 2,
         "bounties_won": 1, "contracts_completed": 0, "trust_score": 0.5}


async def test_seeded_week_picks_the_expected_agent(clean, agents):
    week = date(1999, 1, 11)
    seed = await _seed_week(clean, agents, week)

    async with clean.acquire() as conn:
        ranked = await spot.score_candidates(conn, week, roster=_roster(seed))
    assert [c["agent_did"] for c in ranked] == [
        seed["alice"].did, seed["bob"].did, seed["selfie"].did,
    ]
    assert [c["score"] for c in ranked] == [Decimal(28), Decimal(21), Decimal(10)]
    assert ranked[0]["breakdown"] == ALICE
    assert ranked[1]["breakdown"]["contracts_completed"] == 1
    assert ranked[2]["breakdown"]["likes_received"] == 0

    async with clean.acquire() as conn:
        row = await spot.pick_for_week(conn, week, roster=_roster(seed))
    assert row["agent_did"] == seed["alice"].did
    assert row["chosen_by"] == "auto" and row["score"] == Decimal(28)
    assert {k: row["breakdown"][k] for k in ALICE} == ALICE
    assert row["breakdown"]["window_start"] == "1999-01-04T00:00:00+00:00"
    assert row["breakdown"]["window_end"] == "1999-01-11T00:00:00+00:00"

    # Second run: no-op, the stored pick is unchanged.
    async with clean.acquire() as conn:
        assert await spot.pick_for_week(conn, week, roster=_roster(seed)) is None
    rows = await clean.fetch("SELECT agent_did FROM agent_spotlights WHERE week_start = $1", week)
    assert [r["agent_did"] for r in rows] == [seed["alice"].did]


async def test_week_with_no_eligible_agent_inserts_nothing(clean):
    week = date(1999, 6, 7)
    async with clean.acquire() as conn:
        assert await spot.score_candidates(conn, week, roster={}) == []
        assert await spot.pick_for_week(conn, week, roster={}) is None
    assert await clean.fetchval(
        "SELECT COUNT(*) FROM agent_spotlights WHERE week_start = $1", week) == 0


async def test_recent_pick_is_skipped_unless_withdrawn(clean, agents):
    week = date(1999, 3, 8)
    seed = await _seed_week(clean, agents, week)
    alice = seed["alice"].did
    await clean.execute(
        "INSERT INTO agent_spotlights (week_start, agent_did, chosen_by) "
        "VALUES ('1999-02-15', $1, 'auto')",
        alice,
    )
    async with clean.acquire() as conn:
        ranked = await spot.score_candidates(conn, week, roster=_roster(seed))
    assert alice not in [c["agent_did"] for c in ranked]
    assert ranked[0]["agent_did"] == seed["bob"].did

    await clean.execute(
        "UPDATE agent_spotlights SET withdrawn_at = NOW() WHERE week_start = '1999-02-15'")
    async with clean.acquire() as conn:
        ranked = await spot.score_candidates(conn, week, roster=_roster(seed))
    assert ranked[0]["agent_did"] == alice


async def test_a_withdrawn_week_is_not_picked_again(clean, agents):
    week = date(1999, 4, 12)
    seed = await _seed_week(clean, agents, week)
    await clean.execute(
        "INSERT INTO agent_spotlights (week_start, chosen_by, withdrawn_at) "
        "VALUES ($1, $2, NOW())",
        week, "did:agentx:founder-001",
    )
    async with clean.acquire() as conn:
        assert await spot.pick_for_week(conn, week, roster=_roster(seed)) is None
    assert await clean.fetchval(
        "SELECT agent_did FROM agent_spotlights WHERE week_start = $1", week) is None


async def test_the_weekly_job_stores_the_pick_once(clean, agents, monkeypatch):
    """S17-3: the job with the flag on picks the seeded week; a second run is a no-op."""
    from src.config import Settings
    from src.jobs import agent_of_week as job

    week = date(1999, 3, 1)
    seed = await _seed_week(clean, agents, week)
    monkeypatch.setattr(job, "founder_roster", lambda: _roster(seed))
    on = Settings(_env_file=None, agent_of_week_enabled="true")
    wednesday = datetime(1999, 3, 3, 15, 10, tzinfo=timezone.utc)

    first = await job.run_agent_of_week(settings=on, now=wednesday)
    assert first["week_start"] == "1999-03-01"
    assert first["picked"]["agent_did"] == seed["alice"].did
    assert Decimal(first["picked"]["score"]) == 28
    second = await job.run_agent_of_week(settings=on, now=wednesday)
    assert second["picked"] is None and second["skipped"] is None
    rows = await clean.fetch("SELECT agent_did FROM agent_spotlights WHERE week_start = $1", week)
    assert [r["agent_did"] for r in rows] == [seed["alice"].did]
