"""
Adversarial integration tests: gaming the Agent of the week score (Sprint 17,
S17-10 sprint-close security review), against REAL local Postgres.

Three cheap attacks an outside operator could run against the scoring query in
`services/spotlight_service.py`, and the rule that stops each:

  • a ring of brand-new sock-puppet accounts liking and replying to the
    attacker's posts — engagement counts only from accounts at least
    MIN_ACCOUNT_AGE old at the end of the window (the same age floor a
    candidate needs);
  • one account replying to the same post over and over — replies count once
    per (replier, post);
  • posting in bulk — at most MAX_SCORED_POSTS posts count towards the score
    (eligibility still needs MIN_POSTS real posts).

In each test a genuine agent ("alice") with modest real engagement must beat
the attacker ("mallory"). Weeks are in 1997 so no other test's rows fall
inside these scoring windows.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_spotlight_adversarial_db.py -v --db
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services import spotlight_service as spot

pytestmark = pytest.mark.integration   # skipped unless --db is given

OLD = datetime(1996, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
async def clean(pool):
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")
    yield pool
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")


async def _agent(pool, agents, name, *, created=OLD, trust="0.50"):
    a = await agents(name)
    await pool.execute(
        "UPDATE agents SET created_at = $2, trust_score = $3 WHERE agent_did = $1",
        a.did, created, Decimal(trust),
    )
    return a


async def _post(pool, author, at, *, parent=None):
    return await pool.fetchval(
        """
        INSERT INTO posts (author_did, post_type, title, content, parent_post_id, created_at)
        VALUES ($1, 'UPDATE', 'adversarial test', 'hello', $2, $3::timestamptz)
        RETURNING post_id
        """,
        author.did, parent, at,
    )


async def _like(pool, agent, post_id, at):
    await pool.execute(
        "INSERT INTO post_likes (post_id, agent_did, created_at) VALUES ($1, $2, $3)",
        post_id, agent.did, at,
    )


async def _genuine_alice(pool, agents, t):
    """4 posts; bob replies to 2 and likes 1, carol likes 3.
    4 + 2×2 + 4 + 2×3 + 0 + 0 + 0.5×10 = 23."""
    alice = await _agent(pool, agents, "adv-alice")
    bob = await _agent(pool, agents, "adv-bob")
    carol = await _agent(pool, agents, "adv-carol")
    posts = [await _post(pool, alice, t(1 + i)) for i in range(4)]
    await _post(pool, bob, t(10), parent=posts[0])
    await _post(pool, bob, t(11), parent=posts[1])
    await _like(pool, bob, posts[0], t(12))
    for p in posts[1:]:
        await _like(pool, carol, p, t(13))
    return alice


def _window(week: date):
    lo, hi = spot.scoring_window(week)
    return lo, hi, (lambda hours: lo + timedelta(hours=hours))


async def _ranked(pool, week):
    async with pool.acquire() as conn:
        return await spot.score_candidates(conn, week, roster={})


def _by_did(ranked, did):
    return next(c for c in ranked if c["agent_did"] == did)


async def test_new_sock_puppets_do_not_count_as_engagers(clean, agents):
    """Nine accounts made the day before the window closes like and reply to
    every one of mallory's posts. None of it counts. One puppet old enough
    to be a candidate itself does count — the rule is the age floor, nothing
    cleverer — and mallory still loses to alice."""
    week = date(1997, 3, 10)
    lo, hi, t = _window(week)
    alice = await _genuine_alice(clean, agents, t)

    mallory = await _agent(clean, agents, "adv-mallory")
    m_posts = [await _post(clean, mallory, t(20 + i)) for i in range(3)]
    fresh = [await _agent(clean, agents, f"adv-puppet{i}", created=hi - timedelta(days=1))
             for i in range(9)]
    veteran = await _agent(clean, agents, "adv-veteran")
    for puppet in fresh + [veteran]:
        for p in m_posts:
            await _like(clean, puppet, p, t(30))
            await _post(clean, puppet, t(31), parent=p)

    ranked = await _ranked(clean, week)
    m = _by_did(ranked, mallory.did)
    assert m["breakdown"]["distinct_engagers"] == 1, m["breakdown"]
    assert m["breakdown"]["likes_received"] == 3
    assert m["breakdown"]["replies_received"] == 3
    assert m["score"] == Decimal(3 + 3 * 2 + 3 + 1 * 3 + 5)        # 20
    assert _by_did(ranked, alice.did)["score"] == Decimal(23)
    assert ranked[0]["agent_did"] == alice.did
    # The fresh puppets are not candidates either (under the age floor).
    assert not {p.did for p in fresh} & {c["agent_did"] for c in ranked}


async def test_repeated_replies_from_one_account_count_once_per_post(clean, agents):
    """One old account replies 20 times to each of mallory's 3 posts (60
    replies, 120 points under a naive count). They count as 3."""
    week = date(1997, 4, 7)
    lo, hi, t = _window(week)
    alice = await _genuine_alice(clean, agents, t)

    mallory = await _agent(clean, agents, "adv-mallory2")
    shill = await _agent(clean, agents, "adv-shill")
    m_posts = [await _post(clean, mallory, t(20 + i)) for i in range(3)]
    for p in m_posts:
        for k in range(20):
            await _post(clean, shill, t(40) + timedelta(minutes=k), parent=p)

    ranked = await _ranked(clean, week)
    m = _by_did(ranked, mallory.did)
    assert m["breakdown"]["replies_received"] == 3, m["breakdown"]
    assert m["breakdown"]["distinct_engagers"] == 1
    assert m["score"] == Decimal(3 + 3 * 2 + 0 + 3 + 5)            # 17
    assert ranked[0]["agent_did"] == alice.did
    # The shill's 60 replies are its own posts: scored, but capped.
    assert _by_did(ranked, shill.did)["breakdown"]["posts"] == spot.MAX_SCORED_POSTS


async def test_bulk_posting_is_capped(clean, agents):
    """60 posts with no engagement at all must not beat a genuine agent."""
    week = date(1997, 5, 5)
    lo, hi, t = _window(week)
    alice = await _genuine_alice(clean, agents, t)

    mallory = await _agent(clean, agents, "adv-mallory3")
    for i in range(60):
        await _post(clean, mallory, t(20) + timedelta(minutes=i))

    ranked = await _ranked(clean, week)
    m = _by_did(ranked, mallory.did)
    assert m["breakdown"]["posts"] == spot.MAX_SCORED_POSTS
    assert m["score"] == Decimal(spot.MAX_SCORED_POSTS + 5)
    assert ranked[0]["agent_did"] == alice.did
    assert spot.MIN_POSTS <= spot.MAX_SCORED_POSTS


async def test_eligibility_minimum_is_the_raw_post_count(clean, agents):
    """The cap is for scoring only: two posts is still too few to be eligible,
    three is enough, and the breakdown never reports more than the cap."""
    week = date(1997, 6, 2)
    lo, hi, t = _window(week)
    two = await _agent(clean, agents, "adv-two")
    three = await _agent(clean, agents, "adv-three")
    for i in range(2):
        await _post(clean, two, t(1 + i))
    for i in range(3):
        await _post(clean, three, t(1 + i))

    ranked = await _ranked(clean, week)
    dids = [c["agent_did"] for c in ranked]
    assert two.did not in dids and three.did in dids
    assert _by_did(ranked, three.did)["breakdown"]["posts"] == 3
