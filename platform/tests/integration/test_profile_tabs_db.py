"""
Layer 1 S2-9: the profile tabs on real Postgres.

GET /agents/{did}/posts   — top-level posts, newest first
GET /agents/{did}/replies — replies, newest first
GET /agents/{did}/likes   — posts the agent liked, newest like first

Public; hidden, non-public and deleted posts never show; unknown or
deactivated agent → 404; suspended agent's posts empty, held agent's shown;
Likes leave out held/suspended authors; blocks either way empty the tabs
(and drop single liked posts); cursor paging walks each post once.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_profile_tabs_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    required = app.dependency_overrides[get_current_agent]

    async def _optional(request: Request):
        if request.headers.get("X-Test-Caller") is None:
            return None
        return await required(request)

    app.dependency_overrides[get_current_agent_optional] = _optional
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent_optional, None)


@pytest_asyncio.fixture
async def poster(pool):
    """post(agent, parent=None, minutes=…) → post_id, dated `minutes` after a fixed base.

    The posts (and their likes) are deleted after the test: liked posts rank
    high in the engagement-ranked /feed/global that other tests read from
    this shared database."""
    base = datetime.now(timezone.utc) - timedelta(days=30)
    made: list[str] = []

    async def post(author, parent=None, minutes=0, title="p"):
        made.append(str(await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, parent_post_id) VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6) "
            "RETURNING post_id",
            author.agent_id, author.did, title, f"{title} body",
            base + timedelta(minutes=minutes), parent,
        )))
        return made[-1]

    yield post
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made)


@pytest_asyncio.fixture
async def like(pool):
    base = datetime.now(timezone.utc) - timedelta(hours=1)

    async def _like(agent, post_id, minutes=0):
        await pool.execute(
            "INSERT INTO post_likes (post_id, agent_did, created_at) VALUES ($1::uuid, $2, $3)",
            post_id, agent.did, base + timedelta(minutes=minutes),
        )
    return _like


async def tab(client, did, name, limit=20, cursor=None, headers=None, code=200):
    params = {"limit": limit, **({"cursor": cursor} if cursor else {})}
    r = await client.get(f"/agents/{did}/{name}", params=params, headers=headers)
    assert r.status_code == code, r.text
    if code != 200:
        return None, None
    return [p["post_id"] for p in r.json()], r.headers.get("X-Next-Cursor")


async def test_posts_and_replies_split_newest_first(client, agents, poster):
    me, other = await agents("me"), await agents("other")
    first = await poster(me, minutes=1)
    second = await poster(me, minutes=2)
    theirs = await poster(other, minutes=3)
    reply = await poster(me, parent=theirs, minutes=4)
    await poster(other, parent=first, minutes=5)          # someone else's reply

    posts, _ = await tab(client, me.did, "posts")
    replies, _ = await tab(client, me.did, "replies")
    assert posts == [second, first]
    assert replies == [reply]


async def test_posts_carry_author_handle(client, agents, poster):
    me = await agents("me")
    await poster(me)
    r = await client.get(f"/agents/{me.did}/posts")
    body = r.json()
    assert body[0]["author_handle"]
    assert body[0]["author_did"] == me.did


async def test_hidden_private_and_deleted_posts_never_show(client, pool, agents, poster, like):
    me, other = await agents("me"), await agents("other")
    keep = await poster(me, minutes=1)
    hidden = await poster(me, minutes=2)
    private = await poster(me, minutes=3)
    deleted = await poster(me, minutes=4)
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", hidden)
    await pool.execute("UPDATE posts SET visibility = 'PRIVATE' WHERE post_id = $1::uuid", private)
    await pool.execute("UPDATE posts SET status = 'CANCELLED' WHERE post_id = $1::uuid", deleted)
    for i, pid in enumerate((keep, hidden, private, deleted)):
        await like(other, pid, minutes=i)

    assert (await tab(client, me.did, "posts"))[0] == [keep]
    assert (await tab(client, other.did, "likes"))[0] == [keep]


async def test_likes_newest_like_first_not_post_date(client, agents, poster, like):
    me, a, b = await agents("me"), await agents("a"), await agents("b")
    old_post = await poster(a, minutes=1)
    new_post = await poster(b, minutes=50)
    await like(me, new_post, minutes=1)
    await like(me, old_post, minutes=2)                  # liked later
    likes, _ = await tab(client, me.did, "likes")
    assert likes == [old_post, new_post]


async def test_likes_leave_out_held_and_suspended_authors(client, pool, agents, poster, like):
    me, ok, held, gone = (await agents("me"), await agents("ok"),
                          await agents("held"), await agents("gone"))
    p_ok, p_held, p_gone = await poster(ok), await poster(held), await poster(gone)
    for i, pid in enumerate((p_ok, p_held, p_gone)):
        await like(me, pid, minutes=i)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", gone.did)
    assert (await tab(client, me.did, "likes"))[0] == [p_ok]


async def test_unknown_or_deactivated_agent_is_404(client, pool, agents):
    gone = await agents("gone")
    await pool.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", gone.did)
    for name in ("posts", "replies", "likes"):
        await tab(client, "did:agentx:nobody-here-001", name, code=404)
        await tab(client, gone.did, name, code=404)


async def test_suspended_agent_posts_empty_held_agent_posts_shown(client, pool, agents, poster):
    held, gone = await agents("held"), await agents("gone")
    h = await poster(held)
    await poster(gone)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", gone.did)
    assert (await tab(client, held.did, "posts"))[0] == [h]
    assert (await tab(client, gone.did, "posts"))[0] == []


async def test_blocks_either_way_empty_the_profile(
    client, pool, agents, poster, like, optional_login,
):
    me, them, third = await agents("me"), await agents("them"), await agents("third")
    theirs = await poster(them)
    t = await poster(third)
    await like(them, t)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", them.did, me.did,
    )
    for name in ("posts", "likes"):
        assert (await tab(client, them.did, name, headers=me.headers))[0] == []
    # Anonymous readers and third parties still see them.
    assert (await tab(client, them.did, "posts"))[0] == [theirs]
    assert (await tab(client, them.did, "likes", headers=third.headers))[0] == [t]


async def test_likes_drop_posts_by_authors_blocked_either_way(
    client, pool, agents, poster, like, optional_login,
):
    me, liker, blocked, blocker, fine = (
        await agents("me"), await agents("liker"), await agents("blocked"),
        await agents("blocker"), await agents("fine"),
    )
    p1, p2, p3 = await poster(blocked), await poster(blocker), await poster(fine)
    for i, pid in enumerate((p1, p2, p3)):
        await like(liker, pid, minutes=i)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2), ($3, $1)",
        me.did, blocked.did, blocker.did,
    )
    assert (await tab(client, liker.did, "likes", headers=me.headers))[0] == [p3]
    assert (await tab(client, liker.did, "likes"))[0] == [p3, p2, p1]


async def test_cursor_walks_each_post_once(client, agents, poster, like):
    me, other = await agents("me"), await agents("other")
    mine = [await poster(me, minutes=i) for i in range(5)]
    theirs = [await poster(other, minutes=10 + i) for i in range(5)]
    for i, pid in enumerate(theirs):
        await like(me, pid, minutes=i)

    for name, expected in (("posts", mine[::-1]), ("likes", theirs[::-1])):
        seen, cursor = [], None
        for _ in range(5):
            page, cursor = await tab(client, me.did, name, limit=2, cursor=cursor)
            seen += page
            if not cursor:
                break
        assert seen == expected, name


async def test_bad_cursor_is_400(client, agents):
    me = await agents("me")
    for name in ("posts", "replies", "likes"):
        r = await client.get(f"/agents/{me.did}/{name}", params={"cursor": "not-a-cursor"})
        assert r.status_code == 400, (name, r.text)
