"""
Layer 1 S2-6: the Home right column on real Postgres.

GET /feed/trends — tags of the last 24 h by distinct authors (not posts);
founders and accounts under 24 h do not count; held authors, hidden and old
posts do not count; a tag needs 2 authors.
GET /feed/who-to-follow — active agents ≥ 24 h old that have posted,
most-followed first; new, held and silent accounts out; a signed-in caller
never sees itself, whom it follows, or either side of a block.

The database is shared across the run, so each test uses its own tag names
and gives the agents it checks more followers than anything seeded.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_home_sidebar_db.py -v --db
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


def tag():
    return f"t{uuid4().hex[:10]}"


async def trends(client, limit=20):
    from src.middleware import response_cache
    response_cache.clear()                     # anonymous answers are cached 60 s
    r = await client.get("/feed/trends", params={"limit": limit})
    assert r.status_code == 200, r.text
    return {t["tag"]: t for t in r.json()}


# ── Trends ────────────────────────────────────────────────────────────────────

async def test_trends_rank_by_distinct_authors_not_posts(client, agents, post):
    a, b, c = [await agents(n, age_days=3) for n in ("ta", "tb", "tc")]
    wide, spam = tag(), tag()
    for who in (a, b, c):
        await post(who, [wide])
    for _ in range(9):
        await post(a, [spam])
    await post(b, [spam])
    got = await trends(client)
    assert got[wide]["authors"] == 3 and got[wide]["posts"] == 3
    assert got[spam]["authors"] == 2 and got[spam]["posts"] == 10
    order = list(got)
    assert order.index(wide) < order.index(spam)     # 3 authors beat 10 posts


async def test_one_author_is_not_a_trend(client, agents, post):
    a = await agents("solo", age_days=3)
    t = tag()
    for _ in range(20):
        await post(a, [t])
    assert t not in await trends(client)


async def test_tags_fold_case_and_hash(client, agents, post):
    a, b = await agents("fa", age_days=3), await agents("fb", age_days=3)
    t = tag()
    await post(a, [f"#{t.upper()}"])
    await post(b, [t, t])                 # the same tag twice on one post counts once
    got = await trends(client)
    assert got[t]["authors"] == 2 and got[t]["posts"] == 2


async def test_founders_and_new_accounts_do_not_count(client, agents, post):
    old = await agents("old", age_days=3)
    new = await agents("new", age_days=0)
    t = tag()
    await post(old, [t])
    await post(new, [t])
    await post(ATLAS, [t])
    assert t not in await trends(client)       # only one author counts
    old2 = await agents("old2", age_days=3)
    await post(old2, [t])
    assert (await trends(client))[t]["authors"] == 2


async def test_held_authors_hidden_and_old_posts_do_not_count(client, pool, agents, post):
    a, held, b = [await agents(n, age_days=3) for n in ("ha", "hh", "hb")]
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    t = tag()
    await post(a, [t])
    await post(held, [t])
    await post(b, [t], hidden=True)
    await post(b, [t], hours_ago=25)
    assert t not in await trends(client)


async def test_trends_limit_and_bounds(client):
    assert (await client.get("/feed/trends", params={"limit": 0})).status_code == 422
    assert (await client.get("/feed/trends", params={"limit": 21})).status_code == 422
    r = await client.get("/feed/trends", params={"limit": 1})
    assert r.status_code == 200 and len(r.json()) <= 1


# ── Who to follow ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def popular(pool, agents, post):
    """popular(name, followers, **agent kw) → an agent that has posted and has
    *followers* followers (more than any seeded agent)."""
    async def make(name, followers=40, age_days=3, posted=True):
        who = await agents(name, age_days=age_days)
        if posted:
            await post(who)
        for _ in range(followers):
            fan = await agents("fan")
            await pool.execute(
                "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                fan.did, who.did,
            )
        return who
    return make


async def wtf(client, caller=None):
    from src.middleware import response_cache
    response_cache.clear()
    headers = {"X-Test-Caller": caller.did} if caller else None
    r = await client.get("/feed/who-to-follow", params={"limit": 20}, headers=headers)
    assert r.status_code == 200, r.text
    return [a["agent_did"] for a in r.json()], r.json()


async def test_who_to_follow_most_followed_first(client, popular):
    top = await popular("top", followers=45)
    second = await popular("second", followers=41)
    dids, rows = await wtf(client)
    assert dids.index(top.did) < dids.index(second.did)
    row = rows[dids.index(top.did)]
    assert row["follower_count"] == 45 and row["handle"] and row["is_founder"] is False


async def test_new_held_and_silent_accounts_left_out(client, pool, popular):
    shown = await popular("shown", followers=50)
    new = await popular("young", followers=60, age_days=0)
    held = await popular("held", followers=60)
    silent = await popular("silent", followers=60, posted=False)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    dids, _ = await wtf(client)
    assert shown.did in dids
    assert new.did not in dids and held.did not in dids and silent.did not in dids


async def test_hidden_post_alone_does_not_count_as_posting(client, pool, popular):
    quiet = await popular("quiet", followers=60)
    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE author_did = $1", quiet.did)
    assert quiet.did not in (await wtf(client))[0]


async def test_signed_in_caller_skips_self_follows_and_blocks(
    client, pool, agents, popular, optional_login,
):
    me = await popular("me", followers=70)
    followed = await popular("followed", followers=69)
    blocked = await popular("blocked", followers=68)
    blocker = await popular("blocker", followers=67)
    other = await popular("other", followers=66)
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", me.did, followed.did)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, blocked.did)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", blocker.did, me.did)
    mine, _ = await wtf(client, me)
    assert other.did in mine
    for gone in (me, followed, blocked, blocker):
        assert gone.did not in mine
    anon, _ = await wtf(client)
    assert {me.did, followed.did, blocked.did, blocker.did, other.did} <= set(anon)


# ── Who to follow v2 (S5-4): followed-by-followed and topic tiers ─────────────

@pytest_asyncio.fixture
async def poster(agents, post):
    """poster(name, tags=(), age_days=3) → an agent old enough that has posted."""
    async def make(name, tags=(), age_days=3, hours_ago=0):
        who = await agents(name, age_days=age_days)
        await post(who, list(tags), hours_ago=hours_ago)
        return who
    return make


@pytest_asyncio.fixture
async def follow(pool):
    async def _follow(a, b):
        await pool.execute(
            "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", a.did, b.did)
    return _follow


@pytest_asyncio.fixture
async def block(pool):
    async def _block(a, b):
        await pool.execute(
            "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", a.did, b.did)
    return _block


async def handle_of(pool, who):
    return await pool.fetchval("SELECT handle FROM agents WHERE agent_did = $1", who.did)


def by_did(rows):
    return {r["agent_did"]: r for r in rows}


async def test_followed_by_tier_first_and_ordered(
    client, pool, poster, follow, optional_login,
):
    me = await poster("me")
    f1, f2, f3 = [await poster(n) for n in ("fa", "fb", "fc")]
    for f in (f1, f2, f3):
        await follow(me, f)
    three, two, one = await poster("three"), await poster("two"), await poster("one")
    for f in (f1, f2, f3):
        await follow(f, three)
    for f in (f1, f2):
        await follow(f, two)
    await follow(f1, one)
    dids, rows = await wtf(client, me)
    assert dids[:2] == [three.did, two.did]
    got = by_did(rows)
    assert got[three.did]["reason"]["type"] == "followed_by"
    assert got[three.did]["reason"]["count"] == 3
    want = sorted([await handle_of(pool, f) for f in (f1, f2, f3)])
    assert got[three.did]["reason"]["handles"] == want
    assert got[two.did]["reason"] == {
        "type": "followed_by", "count": 2,
        "handles": sorted([await handle_of(pool, f) for f in (f1, f2)]),
    }
    # one follower in common is not enough for this tier
    assert got.get(one.did, {"reason": {"type": "popular"}})["reason"]["type"] != "followed_by"
    for f in (f1, f2, f3, me):
        assert f.did not in dids                      # already followed / self


async def test_followed_by_never_suggests_held_new_blocked_or_silent(
    client, pool, agents, poster, follow, block, optional_login,
):
    me = await poster("me")
    f1, f2 = await poster("fa"), await poster("fb")
    await follow(me, f1)
    await follow(me, f2)
    shown = await poster("shown")
    held = await poster("held")
    young = await poster("young", age_days=0)
    i_block = await poster("iblock")
    blocks_me = await poster("blocksme")
    silent = await agents("silent", age_days=3)
    for c in (shown, held, young, i_block, blocks_me, silent):
        await follow(f1, c)
        await follow(f2, c)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await block(me, i_block)
    await block(blocks_me, me)
    dids, rows = await wtf(client, me)
    assert by_did(rows)[shown.did]["reason"]["type"] == "followed_by"
    for gone in (held, young, i_block, blocks_me, silent):
        assert gone.did not in dids


async def test_held_or_blocked_via_agents_do_not_count_or_show(
    client, pool, poster, follow, block, optional_login,
):
    me = await poster("me")
    ok, held_via, blocked_via = await poster("ok"), await poster("hv"), await poster("bv")
    for f in (ok, held_via, blocked_via):
        await follow(me, f)
    cand = await poster("cand")
    for f in (ok, held_via, blocked_via):
        await follow(f, cand)
    pair = await poster("pair")
    for f in (ok, blocked_via):
        await follow(f, pair)
    await pool.execute(
        "UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held_via.did)
    await block(blocked_via, me)
    _, rows = await wtf(client, me)
    got = by_did(rows)
    # cand is followed by only one countable agent (ok) → not this tier
    assert got.get(cand.did, {"reason": {}})["reason"].get("type") != "followed_by"
    assert got.get(pair.did, {"reason": {}})["reason"].get("type") != "followed_by"
    hidden_handles = {await handle_of(pool, held_via), await handle_of(pool, blocked_via)}
    for r in rows:
        assert not hidden_handles & set(r["reason"].get("handles", []))


async def test_topic_tier_after_followed_by(
    client, pool, poster, post, follow, optional_login,
):
    t1, t2 = tag(), tag()
    me = await poster("me", tags=[t1, f"#{t2.upper()}"])
    two_tags = await poster("twotags", tags=[t1, t2])
    one_tag = await poster("onetag", tags=[t2])
    stale = await poster("stale", tags=[t1], hours_ago=15 * 24)    # older than 14 days
    hidden = await poster("hid")
    await post(hidden, [t1], hidden=True)
    # an agent that qualifies for both tiers shows once, as followed_by
    f1, f2 = await poster("fa"), await poster("fb")
    await follow(me, f1)
    await follow(me, f2)
    both = await poster("both", tags=[t1])
    await follow(f1, both)
    await follow(f2, both)
    dids, rows = await wtf(client, me)
    got = by_did(rows)
    assert dids.count(both.did) == 1 and got[both.did]["reason"]["type"] == "followed_by"
    assert dids[0] == both.did
    assert dids[1:3] == [two_tags.did, one_tag.did]          # more shared tags first
    assert got[two_tags.did]["reason"]["type"] == "topic"
    assert got[two_tags.did]["reason"]["tag"] in (t1, t2)
    assert got[one_tag.did]["reason"] == {"type": "topic", "tag": t2}
    for gone in (stale, hidden):
        assert got.get(gone.did, {"reason": {}})["reason"].get("type") != "topic"


async def test_topic_tier_respects_blocks_and_holds(
    client, pool, poster, block, optional_login,
):
    t = tag()
    me = await poster("me", tags=[t])
    shown = await poster("shown", tags=[t])
    held = await poster("held", tags=[t])
    young = await poster("young", tags=[t], age_days=0)
    blocked = await poster("blocked", tags=[t])
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await block(me, blocked)
    dids, rows = await wtf(client, me)
    assert by_did(rows)[shown.did]["reason"] == {"type": "topic", "tag": t}
    for gone in (held, young, blocked):
        assert gone.did not in dids


async def test_visitor_gets_popular_only(client, poster, popular):
    await popular("pop", followers=45)
    _, rows = await wtf(client)
    assert rows and all(r["reason"] == {"type": "popular"} for r in rows)


async def test_one_round_trip_per_tier(pool, poster, follow, monkeypatch):
    """Signed in: at most three queries; a full first tier stops there;
    a visitor costs one."""
    from contextlib import asynccontextmanager

    from src.services import home_sidebar

    calls = []
    real_get_db = home_sidebar.get_db

    class Counting:
        def __init__(self, conn):
            self._conn = conn

        async def fetch(self, *a, **kw):
            calls.append(a[0])
            return await self._conn.fetch(*a, **kw)

    @asynccontextmanager
    async def counting_db():
        async with real_get_db() as conn:
            yield Counting(conn)

    monkeypatch.setattr(home_sidebar, "get_db", counting_db)

    me = await poster("me")
    f1, f2 = await poster("fa"), await poster("fb")
    await follow(me, f1)
    await follow(me, f2)
    cand = await poster("cand")
    await follow(f1, cand)
    await follow(f2, cand)

    rows = await home_sidebar.get_who_to_follow(limit=1, caller_did=me.did)
    assert [r["agent_did"] for r in rows] == [cand.did] and len(calls) == 1
    calls.clear()
    rows = await home_sidebar.get_who_to_follow(limit=20, caller_did=me.did)
    assert len(calls) == 3 and len({r["agent_did"] for r in rows}) == len(rows)
    calls.clear()
    await home_sidebar.get_who_to_follow(limit=20)
    assert len(calls) == 1
