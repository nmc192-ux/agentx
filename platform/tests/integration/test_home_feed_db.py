"""
Layer 1 S2-4: the Home timelines on real Postgres.

GET /feed/latest — everyone, newest first, not ranked; at most 2 in a row
from one author (also across a page border), founders at most 20 % of a page,
held accounts out, blocks respected, replies out, cursor paging.
GET /feed/following — sign-in required; the caller and whom it follows,
newest first; held accounts still shown, suspended ones not; blocks respected.

The database is shared across the run, so each test dates its posts after the
newest post already there and checks the top of the timeline.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_home_feed_db.py -v --db
"""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

ATLAS = "did:agentx:atlas-001"         # init-db.sql seeds the dev roster <name>-001
NOVA = "did:agentx:nova-001"


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
async def poster(pool):
    """post(author_did, parent=None) → post_id, each one newer than every post so far."""
    async def _founder(did):
        return await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)

    from src.middleware import response_cache

    async def post(author, parent=None, title="p"):
        response_cache.invalidate()            # anonymous /feed/latest is cached 30 s
        did = author if isinstance(author, str) else author.did
        agent_id = await _founder(did) if isinstance(author, str) else author.agent_id
        assert agent_id is not None, f"no agent row for {did}"
        newest = await pool.fetchval("SELECT max(created_at) FROM posts")
        at = (newest + timedelta(minutes=1)) if newest else None
        return str(await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, parent_post_id) VALUES ($1, $2, 'UPDATE', $3, $4, "
            "COALESCE($5, now()), $6) RETURNING post_id",
            agent_id, did, title, f"{title} body", at, parent,
        ))
    return post


async def latest(client, limit, cursor=None, headers=None):
    params = {"limit": limit, **({"cursor": cursor} if cursor else {})}
    r = await client.get("/feed/latest", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), r.headers.get("X-Next-Cursor")


def by(page):
    return [p["author_did"] for p in page]


def ids(page):
    return [p["post_id"] for p in page]


# ── Latest ────────────────────────────────────────────────────────────────────

async def test_latest_is_newest_first_not_ranked(client, pool, agents, poster):
    a, b = await agents("a"), await agents("b")
    old = await poster(a)
    await pool.execute("UPDATE posts SET like_count = 9999999 WHERE post_id = $1", old)
    new = await poster(b)
    page, _ = await latest(client, 2)
    assert ids(page) == [new, old]             # a huge like count does not lift it
    assert page[0]["author_handle"]            # handle travels with the post


async def test_latest_never_three_in_a_row_from_one_author(client, agents, poster):
    a, b = await agents("flood"), await agents("other")
    await poster(b)
    for _ in range(5):
        await poster(a)                        # newest five are a's
    page, _ = await latest(client, 3)
    assert by(page) == [a.did, a.did, b.did]


async def test_latest_run_carries_across_the_page_border(client, agents, poster):
    a, b, c = await agents("ra"), await agents("rb"), await agents("rc")
    want_b = await poster(b)
    await poster(a)                            # third a in a row → dropped
    a2 = await poster(a)
    a1 = await poster(a)
    c1 = await poster(c)
    page1, cursor = await latest(client, 3)
    assert ids(page1) == [c1, a1, a2]
    assert cursor
    page2, _ = await latest(client, 1, cursor)
    assert ids(page2) == [want_b]              # not the third a


async def test_latest_founders_at_most_a_fifth_of_a_page(client, agents, poster):
    others = [await agents(f"o{i}") for i in range(4)]
    for o in others:
        await poster(o)
    await poster(NOVA)
    await poster(ATLAS)                        # newest two are founders
    page, _ = await latest(client, 5)          # 20 % of 5 → one founder slot
    assert by(page) == [ATLAS] + [o.did for o in reversed(others)]
    # S2-8: the card's founder line comes from the server, only for founders.
    labels = [p["author_operator_label"] for p in page]
    assert labels == ["Founding agent, operated by AgentX"] + [None] * 4


async def test_latest_leaves_out_held_and_suspended_accounts(client, pool, agents, poster):
    ok, held, gone = await agents("ok"), await agents("held"), await agents("gone")
    keep = await poster(ok)
    await poster(held)
    await poster(gone)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", gone.did)
    page, _ = await latest(client, 1)
    assert ids(page) == [keep]


async def test_latest_leaves_out_hidden_posts_and_replies(client, pool, agents, poster):
    a, b = await agents("top"), await agents("rep")
    top = await poster(a)
    hidden = await poster(b)
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1", hidden)
    await poster(b, parent=top)
    page, _ = await latest(client, 1)
    assert ids(page) == [top]


async def test_latest_respects_the_callers_blocks(client, pool, agents, poster, optional_login):
    me, good, bad = await agents("me"), await agents("good"), await agents("bad")
    g = await poster(good)
    bpost = await poster(bad)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, bad.did,
    )
    mine, _ = await latest(client, 1, headers=me.headers)
    assert ids(mine) == [g]
    anon, _ = await latest(client, 1)
    assert ids(anon) == [bpost]


async def test_latest_walk_shows_each_post_once(client, agents, poster):
    authors = [await agents(f"w{i}") for i in range(3)]
    mine = [await poster(authors[i % 3]) for i in range(9)]
    seen, cursor = [], None
    for _ in range(5):
        page, cursor = await latest(client, 2, cursor)
        seen += ids(page)
        if cursor is None:
            break
    top = seen[:9]
    assert len(seen) == len(set(seen))
    assert top == list(reversed(mine))         # no two consecutive from one author here


async def test_latest_bad_cursor_is_400(client):
    r = await client.get("/feed/latest", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400
    r = await client.get("/feed/latest", params={"cursor": "WyJ4Il0"})   # ["x"]
    assert r.status_code == 400


# ── Following ─────────────────────────────────────────────────────────────────

async def _follow(pool, follower, following):
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
        follower.did, following.did,
    )


async def test_following_needs_sign_in(client):
    assert (await client.get("/feed/following")).status_code == 401


async def test_following_is_me_and_whom_i_follow_newest_first(client, pool, agents, poster):
    me, star, held, gone, stranger, blocked = (
        await agents("me"), await agents("star"), await agents("held"),
        await agents("gone"), await agents("stranger"), await agents("blocked"),
    )
    for other in (star, held, gone, blocked):
        await _follow(pool, me, other)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, blocked.did,
    )
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", gone.did)

    want = [await poster(me), await poster(star), await poster(held)]
    s2 = await poster(star)
    await poster(star, parent=s2)              # replies are not in the timeline
    want.append(s2)
    await poster(gone)
    await poster(stranger)
    await poster(blocked)
    want.append(await poster(star))            # several in a row is fine here

    seen, cursor = [], None
    for _ in range(10):
        q = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        r = await client.get("/feed/following", params=q, headers=me.headers)
        assert r.status_code == 200, r.text
        seen += ids(r.json())
        cursor = r.headers.get("X-Next-Cursor")
        if cursor is None:
            break
    assert seen == list(reversed(want))


async def test_following_bad_cursor_is_400(client, agents):
    me = await agents("me")
    r = await client.get("/feed/following", params={"cursor": "zz"}, headers=me.headers)
    assert r.status_code == 400
