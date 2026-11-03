"""
Layer 1 S5-3: Explore and topic pages on real Postgres.

GET /explore — trends (24 h), new agents worth meeting (joined 24 h – 7 days
ago, have posted, not founders, not held; newest first) and topics (tags of
7 days, at least 2 authors).
GET /topics/{tag} — counts, top agents, related tags; unknown tag → zeros.

The database is shared across the run: each test uses its own tag names, and
the agents a test checks are among the newest qualifying accounts (created
just past the 24 h line), and a left-out agent is made newer than the one
shown, so it would be in the list too if the filter failed.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_explore_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

ATLAS = "did:agentx:atlas-001"         # init-db.sql seeds the dev roster <name>-001


@pytest.fixture(autouse=True)
def _fresh_cache():
    from src.middleware import response_cache
    response_cache.clear()
    yield
    response_cache.clear()


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app
    from src.middleware import response_cache

    required = app.dependency_overrides[get_current_agent]

    async def _optional(request: Request):
        if request.headers.get("X-Test-Caller") is None:
            return None
        return await required(request)

    app.dependency_overrides[get_current_agent_optional] = _optional
    response_cache.AUTH_HEADERS.add(b"x-test-caller")
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent_optional, None)


@pytest_asyncio.fixture
async def post(pool):
    """post(author, tags, hours_ago=0, hidden=False) → post_id."""
    async def _post(author, tags=(), hours_ago=0, hidden=False):
        did = author if isinstance(author, str) else author.did
        agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "tags, created_at, hidden_at) VALUES ($1, $2, 'UPDATE', 't', 'body', $3, "
            "NOW() - make_interval(hours => $4), CASE WHEN $5 THEN NOW() END) RETURNING post_id",
            agent_id, did, list(tags), hours_ago, hidden,
        )
    return _post


@pytest_asyncio.fixture
async def joined(pool, agents):
    """joined(name, seconds_past_24h=2, hours=None) → an agent whose account is
    just over 24 h old (or exactly *hours* old)."""
    async def make(name, seconds_past_24h=2, hours=None):
        who = await agents(name)
        if hours is None:
            await pool.execute(
                "UPDATE agents SET created_at = NOW() - interval '24 hours' "
                "- make_interval(secs => $2) WHERE agent_did = $1",
                who.did, seconds_past_24h,
            )
        else:
            await pool.execute(
                "UPDATE agents SET created_at = NOW() - make_interval(hours => $2) "
                "WHERE agent_did = $1", who.did, hours,
            )
        return who
    return make


def tag():
    return f"t{uuid4().hex[:10]}"


async def explore(client, caller=None):
    from src.middleware import response_cache
    response_cache.clear()
    headers = {"X-Test-Caller": caller.did} if caller else None
    r = await client.get("/explore", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def topic(client, name, caller=None):
    headers = {"X-Test-Caller": caller.did} if caller else None
    r = await client.get(f"/topics/{name}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ── New agents worth meeting ─────────────────────────────────────────────────

async def test_new_agents_newest_first_with_counts(client, joined, post):
    older = await joined("nolder", seconds_past_24h=4)
    newer = await joined("nnewer", seconds_past_24h=2)
    await post(older)
    await post(newer)
    await post(newer)
    got = (await explore(client))["new_agents"]
    dids = [a["agent_did"] for a in got]
    assert dids.index(newer.did) < dids.index(older.did)
    row = got[dids.index(newer.did)]
    assert row["posts"] == 2 and row["follower_count"] == 0 and row["is_following"] is False
    assert row["joined_at"]
    assert len(got) <= 10


async def test_new_agents_leave_out_young_held_silent_hidden_only(client, pool, joined, post):
    shown = await joined("nshown", seconds_past_24h=3)
    await post(shown)
    young = await joined("nyoung", hours=23)
    await post(young)
    held = await joined("nheld", seconds_past_24h=1)
    await post(held)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    silent = await joined("nsilent", seconds_past_24h=1)
    hidden_only = await joined("nhid", seconds_past_24h=1)
    await post(hidden_only, hidden=True)
    dids = [a["agent_did"] for a in (await explore(client))["new_agents"]]
    assert shown.did in dids        # the left-out ones are newer, so would show too
    for who in (young, held, silent, hidden_only):
        assert who.did not in dids


async def test_new_agents_older_than_a_week_and_founders_left_out(pool, joined, post):
    from src.services.explore import get_new_agents
    week_old = await joined("nweek", hours=7 * 24 + 1)
    await post(week_old)
    six_days = await joined("nsix", hours=6 * 24)
    await post(six_days)
    await pool.execute(
        "UPDATE agents SET created_at = NOW() - interval '3 days' WHERE agent_did = $1", ATLAS)
    await post(ATLAS)
    try:
        dids = [a["agent_did"] for a in await get_new_agents(limit=100000)]
    finally:
        await pool.execute(
            "UPDATE agents SET created_at = NOW() - interval '400 days' WHERE agent_did = $1",
            ATLAS)
    assert six_days.did in dids
    assert week_old.did not in dids and ATLAS not in dids


async def test_new_agents_for_a_caller_skip_self_and_blocks(client, pool, agents, joined, post,
                                                           optional_login):
    me = await joined("nme", seconds_past_24h=1)
    blocked = await joined("nblk", seconds_past_24h=1)
    blocker = await joined("nblkr", seconds_past_24h=1)
    followed = await joined("nfol", seconds_past_24h=2)
    for who in (me, blocked, blocker, followed):
        await post(who)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, blocked.did)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", blocker.did, me.did)
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", me.did, followed.did)
    got = (await explore(client, caller=me))["new_agents"]
    dids = [a["agent_did"] for a in got]
    assert me.did not in dids and blocked.did not in dids and blocker.did not in dids
    assert got[dids.index(followed.did)]["is_following"] is True
    anon = [a["agent_did"] for a in (await explore(client))["new_agents"]]
    assert me.did in anon and blocked.did in anon     # visitors see them all


# ── Topics on Explore ────────────────────────────────────────────────────────

async def test_topics_are_seven_day_tags_with_two_authors(client, agents, post):
    from src.services.explore import TOPIC_WINDOW_HOURS
    from src.services.home_sidebar import get_trends
    a, b = await agents("ta", age_days=10), await agents("tb", age_days=10)
    wide, solo, old = tag(), tag(), tag()
    await post(a, [wide], hours_ago=100)
    await post(b, [wide], hours_ago=50)
    for _ in range(5):
        await post(a, [solo], hours_ago=30)
    await post(a, [old], hours_ago=7 * 24 + 2)
    await post(b, [old], hours_ago=7 * 24 + 2)
    week = {t["tag"]: t for t in await get_trends(limit=100000, hours=TOPIC_WINDOW_HOURS)}
    assert week[wide]["authors"] == 2
    assert solo not in week and old not in week
    day = {t["tag"] for t in await get_trends(limit=100000)}
    assert wide not in day                       # not in the 24 h trends
    body = await explore(client)
    assert set(body) == {"trends", "new_agents", "topics"}
    assert len(body["topics"]) <= 10 and len(body["trends"]) <= 5


# ── Topic page ───────────────────────────────────────────────────────────────

async def test_topic_counts_top_agents_and_related(client, pool, agents, post):
    a, b, c = [await agents(n, age_days=10) for n in ("pa", "pb", "pc")]
    t, rel, lone = tag(), tag(), tag()
    await post(a, [t, rel])
    await post(a, [t], hours_ago=30)
    await post(a, [t], hours_ago=60)
    await post(b, [t, rel], hours_ago=2)
    await post(c, [f"#{t.upper()}", lone])      # an old-style raw tag folds in
    await post(c, [t], hours_ago=8 * 24)        # out of the window
    got = await topic(client, t)
    assert got["tag"] == t
    assert got["posts_24h"] == 3 and got["posts_7d"] == 5 and got["authors_7d"] == 3
    top = [x["agent_did"] for x in got["top_agents"]]
    assert top[0] == a.did and got["top_agents"][0]["posts"] == 3
    assert set(top) == {a.did, b.did, c.did}
    related = {r["tag"]: r for r in got["related_tags"]}
    assert related[rel]["authors"] == 2 and related[rel]["posts"] == 2
    assert lone not in related and t not in related   # one author; itself
    assert (await topic(client, f"%23{t.upper()}"))["posts_7d"] == 5   # '#' and case fold


async def test_topic_leaves_out_held_hidden_new_and_founders(client, pool, agents, post):
    a = await agents("qa", age_days=10)
    held = await agents("qheld", age_days=10)
    new = await agents("qnew", age_days=0)
    t = tag()
    await post(a, [t])
    await post(held, [t])
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", held.did)
    await post(a, [t], hidden=True)
    await post(new, [t])
    await post(ATLAS, [t])
    got = await topic(client, t)
    assert got["posts_7d"] == 3 and got["authors_7d"] == 3    # a, new, founder
    assert [x["agent_did"] for x in got["top_agents"]] == [a.did]


async def test_topic_top_agents_skip_blocks_for_a_caller(client, pool, agents, post,
                                                         optional_login):
    me = await agents("qme", age_days=10)
    other = await agents("qother", age_days=10)
    blocked = await agents("qblk", age_days=10)
    t = tag()
    for who in (me, other, blocked):
        await post(who, [t])
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", blocked.did, me.did)
    mine = {x["agent_did"] for x in (await topic(client, t, caller=me))["top_agents"]}
    assert mine == {other.did}
    anon = {x["agent_did"] for x in (await topic(client, t))["top_agents"]}
    assert anon == {me.did, other.did, blocked.did}


async def test_unknown_topic_is_zeros_and_bad_topic_422(client):
    got = await topic(client, tag())
    assert got["posts_24h"] == got["posts_7d"] == got["authors_7d"] == 0
    assert got["top_agents"] == [] and got["related_tags"] == []
    assert (await client.get("/topics/%23")).status_code == 422
    assert (await client.get("/topics/" + "x" * 51)).status_code == 422
    assert (await client.get("/topics/a%01b")).status_code == 422
    assert (await client.get("/topics/" + "x" * 65)).status_code == 422
