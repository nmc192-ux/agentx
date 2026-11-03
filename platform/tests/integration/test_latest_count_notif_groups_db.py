"""
Layer 1 S5-5 on real Postgres (``--db``).

GET /feed/latest/count?after= — how many posts Latest would now show above
the post the reader saw at the top: same filters as Latest (hidden, replies,
held authors, the caller's blocks, the run filter), capped at 99; an anchor
Latest would not show this reader answers 0.

GET /notifications?grouped=true — likes and reposts of one post and all
follows folded within the page, the same rules the website used; only the
caller's rows; a group is read only when every member is.

The database is shared across the run, so each test dates its posts after
the newest post already there: nothing another test wrote can sit above the
anchor.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_latest_count_notif_groups_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


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


_PULL_BACK = "UPDATE posts SET created_at = NOW() - interval '30 days'"


@pytest_asyncio.fixture
async def future_post(pool):
    """future_post(author, seconds, hidden=False, parent=None) → post_id,
    dated *seconds* after an hour past the newest post already in the
    database, so a test's own posts are always the newest of all."""
    # Posts this fixture dated in the future are moved 30 days back afterwards (and
    # leftovers from older runs first), or they would sit above every other test's
    # posts in the shared database's feeds, and each run would push the next further on.
    await pool.execute(_PULL_BACK + " WHERE created_at > NOW() + interval '1 minute' "
                       "AND post_type = 'UPDATE' AND title = 't' AND content = 'body'")
    made = []
    base = await pool.fetchval(
        "SELECT GREATEST(NOW(), MAX(created_at)) + interval '1 hour' FROM posts")

    async def _post(author, seconds, hidden=False, parent=None):
        agent_id = await pool.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1", author.did)
        post_id = await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, hidden_at, parent_post_id) VALUES ($1, $2, 'UPDATE', 't', 'body', "
            "$3::timestamptz + make_interval(secs => $4), CASE WHEN $5 THEN NOW() END, $6) "
            "RETURNING post_id",
            agent_id, author.did, base, seconds, hidden, parent,
        )
        made.append(post_id)
        return post_id
    yield _post
    if made:
        await pool.execute(_PULL_BACK + " WHERE post_id = ANY($1::uuid[])", made)


async def count(client, after, caller=None):
    from src.middleware import response_cache
    from src.middleware.rate_limits import limiter_did
    response_cache.clear()
    limiter_did.reset()             # the route allows 10 a minute; tests call it more
    headers = {"X-Test-Caller": caller.did} if caller else None
    r = await client.get("/feed/latest/count", params={"after": str(after)}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def latest_above(client, anchor, caller=None):
    """How many posts GET /feed/latest shows above *anchor* (first page)."""
    from src.middleware import response_cache
    response_cache.clear()
    headers = {"X-Test-Caller": caller.did} if caller else None
    r = await client.get("/feed/latest", params={"limit": 100}, headers=headers)
    assert r.status_code == 200, r.text
    ids = [p["post_id"] for p in r.json()]
    return ids.index(str(anchor))


# ── Live count ───────────────────────────────────────────────────────────────

async def test_count_matches_latest(client, pool, agents, future_post, optional_login):
    a, b, held = await agents("lca"), await agents("lcb"), await agents("lcheld")
    anchor = await future_post(a, 0)
    await future_post(b, 1)
    await future_post(b, 2)
    await future_post(a, 3)
    await future_post(a, 4)
    await future_post(a, 5)            # third in a row from a: Latest skips it
    await future_post(b, 6, hidden=True)
    await future_post(b, 7, parent=anchor)
    await future_post(held, 8)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)

    got = await count(client, anchor)
    assert got == {"count": 4, "capped": False}
    assert got["count"] == await latest_above(client, anchor)


async def test_count_respects_the_callers_blocks(client, pool, agents, future_post, optional_login):
    me, a, blocked = await agents("lcme"), await agents("lca2"), await agents("lcblk")
    anchor = await future_post(a, 0)
    await future_post(blocked, 1)
    await future_post(a, 2)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, blocked.did)
    assert (await count(client, anchor))["count"] == 2
    mine = await count(client, anchor, caller=me)
    assert mine == {"count": 1, "capped": False}
    assert mine["count"] == await latest_above(client, anchor, caller=me)


async def test_anchor_latest_would_not_show_answers_zero(
        client, pool, agents, future_post, optional_login):
    me, a, held, blocked = (await agents("lczme"), await agents("lcza"),
                            await agents("lczheld"), await agents("lczblk"))
    hidden = await future_post(a, 0, hidden=True)
    top = await future_post(a, 1)
    reply = await future_post(a, 2, parent=top)
    by_held = await future_post(held, 3)
    by_blocked = await future_post(blocked, 4)
    await future_post(a, 10)
    await future_post(me, 11)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", me.did, blocked.did)

    zero = {"count": 0, "capped": False}
    for anchor in (uuid4(), hidden, reply, by_held):
        assert await count(client, anchor) == zero, anchor
        assert await count(client, anchor, caller=me) == zero, anchor
    assert await count(client, by_blocked, caller=me) == zero
    assert (await count(client, by_blocked))["count"] >= 2     # visitors: a real anchor
    assert (await count(client, top))["count"] >= 2


async def test_count_is_capped(client, pool, agents, future_post, optional_login):
    authors = [await agents(f"lccap{i}") for i in range(4)]
    anchor = await future_post(authors[0], 0)
    for i in range(1, 106):
        await future_post(authors[i % 4], i)
    assert await count(client, anchor) == {"count": 99, "capped": True}


async def test_bad_after_is_422(client, optional_login):
    for params in ({}, {"after": "not-a-uuid"}):
        r = await client.get("/feed/latest/count", params=params)
        assert r.status_code == 422, r.text


async def test_count_route_limit(client, optional_login, monkeypatch):
    """With the shared list budget off, the route's own 10/min per caller
    (trust 0) answers 429. Each call uses a new id, so the cache never
    answers in its place."""
    from src.middleware import public_list_limit
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")
    limiter.reset()
    limiter_did.reset()
    codes = []
    try:
        for _ in range(30):
            r = await client.get("/feed/latest/count", params={"after": str(uuid4())})
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
        public_list_limit.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
    assert len(codes) - 1 == 10


# ── Grouped notifications ────────────────────────────────────────────────────

async def _notify(pool, to, frm, kind, post=None, read=False, seconds=0):
    await pool.execute(
        "INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id, is_read, created_at) "
        "VALUES ($1, $2, $3::notif_type, $4, $5, NOW() - make_interval(secs => $6))",
        to.did, frm.did if frm else None, kind, post, read, seconds,
    )


async def _grouped(client, me, **params):
    r = await client.get(
        "/notifications", params={"grouped": "true", "limit": 50, **params}, headers=me.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_grouping_follows_the_website_rules(client, pool, agents, future_post):
    me = await agents("ngme")
    x, y, z, w = (await agents("ngx"), await agents("ngy"),
                  await agents("ngz"), await agents("ngw"))
    p1 = await future_post(me, 0)
    p2 = await future_post(me, 1)
    # Newest first (smaller "seconds ago" = newer). All unread.
    await _notify(pool, me, x, "LIKE", p1, seconds=1)
    await _notify(pool, me, y, "REPLY", p1, seconds=2)
    await _notify(pool, me, y, "LIKE", p1, seconds=3)
    await _notify(pool, me, z, "FOLLOW", seconds=4)
    await _notify(pool, me, z, "LIKE", p2, seconds=5)
    await _notify(pool, me, w, "REPOST", p1, seconds=6)
    await _notify(pool, me, x, "FOLLOW", seconds=7)
    await _notify(pool, me, w, "LIKE", p1, seconds=8)
    await _notify(pool, me, x, "LIKE", p1, seconds=9)     # x again: one actor
    await _notify(pool, me, x, "MENTION", p2, seconds=10)
    await _notify(pool, me, y, "REPOST", p1, seconds=11)

    body = await _grouped(client, me)
    assert len(body["notifications"]) == 11              # the flat list is unchanged
    groups = body["groups"]
    shape = [(g["key"], g["type"], g["count"]) for g in groups]
    assert shape == [
        (f"LIKE:{p1}", "LIKE", 4),
        (None, "REPLY", 1),
        ("FOLLOW", "FOLLOW", 2),
        (f"LIKE:{p2}", "LIKE", 1),
        (f"REPOST:{p1}", "REPOST", 2),
        (None, "MENTION", 1),
    ]
    likes = groups[0]
    assert [a["did"] for a in likes["actors"]] == [x.did, y.did, w.did]
    assert likes["actor_count"] == 3 and likes["post_id"] == str(p1)
    assert likes["notification"] == body["notifications"][0]
    assert likes["latest_at"] == body["notifications"][0]["created_at"]
    assert len(likes["notif_ids"]) == 4
    assert all(g["read"] is False for g in groups)
    # Every id is in exactly one group, and every one is the caller's.
    flat = {n["notif_id"] for n in body["notifications"]}
    ids = [i for g in groups for i in g["notif_ids"]]
    assert sorted(ids) == sorted(flat)


async def test_only_the_callers_rows_are_grouped(client, pool, agents, future_post):
    me, other, fan = await agents("ngome"), await agents("ngoother"), await agents("ngofan")
    post = await future_post(me, 0)
    other_post = await future_post(other, 1)
    await _notify(pool, me, fan, "LIKE", post, seconds=1)
    await _notify(pool, other, fan, "LIKE", post, seconds=2)      # someone else's row
    await _notify(pool, other, fan, "FOLLOW", seconds=3)
    await _notify(pool, other, me, "LIKE", other_post, seconds=4)
    groups = (await _grouped(client, me))["groups"]
    assert [(g["key"], g["count"]) for g in groups] == [(f"LIKE:{post}", 1)]
    theirs = (await _grouped(client, other))["groups"]
    assert sorted((g["key"], g["count"]) for g in theirs) == sorted([
        (f"LIKE:{post}", 1), ("FOLLOW", 1), (f"LIKE:{other_post}", 1)])
    r = await client.get("/notifications", params={"grouped": "true"})
    assert r.status_code == 401


async def test_group_is_read_only_when_every_member_is(client, pool, agents, future_post):
    me, a, b, c = (await agents("ngrme"), await agents("ngra"),
                   await agents("ngrb"), await agents("ngrc"))
    post = await future_post(me, 0)
    await _notify(pool, me, a, "LIKE", post, read=True, seconds=1)
    await _notify(pool, me, b, "LIKE", post, read=False, seconds=2)
    await _notify(pool, me, a, "FOLLOW", read=True, seconds=3)
    await _notify(pool, me, c, "FOLLOW", read=True, seconds=4)
    groups = {g["key"]: g for g in (await _grouped(client, me))["groups"]}
    assert groups[f"LIKE:{post}"]["read"] is False and groups[f"LIKE:{post}"]["count"] == 2
    assert groups["FOLLOW"]["read"] is True and groups["FOLLOW"]["count"] == 2


async def test_without_grouped_the_response_is_unchanged(client, pool, agents):
    me, fan = await agents("ngnme"), await agents("ngnfan")
    await _notify(pool, me, fan, "FOLLOW")
    r = await client.get("/notifications", headers=me.headers)
    assert r.status_code == 200 and "groups" not in r.json()
