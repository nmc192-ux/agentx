"""
Layer 1 S3-3: reposts on real Postgres.

POST   /posts/{id}/repost — idempotent; 404 hidden/unreadable, 403 across a
                            block either way, 422 unless public and active
DELETE /posts/{id}/repost — idempotent undo, works after a hide or a block
repost_count / reposted on post responses; one REPOST notification ever per
reposter and post; reposts in Following and on the reposter's Posts tab as
items with reposted_by, and gone again when the original is hidden.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_reposts_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    """The limiter is not under test (the harness sends no Bearer token, so
    every caller would share one per-IP bucket)."""
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    yield


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let the test caller sign in on routes that take an optional caller."""
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
    """post(author, minutes=0, **cols) → post_id, dated after a fixed base (deleted after)."""
    base = datetime.now(timezone.utc) - timedelta(days=40)
    made: list[str] = []

    async def post(author, minutes=0, parent=None, visibility="PUBLIC", title="p"):
        made.append(str(await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, parent_post_id, visibility) "
            "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7::post_visibility) RETURNING post_id",
            author.agent_id, author.did, title, f"{title} body",
            base + timedelta(minutes=minutes), parent, visibility,
        )))
        return made[-1]

    yield post
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made)


async def _block(pool, blocker, blocked):
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        blocker.did, blocked.did,
    )


async def _follow(pool, follower, following):
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
        follower.did, following.did,
    )


async def _repost_notifs(pool, to, frm, post_id) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND from_did = $2 "
        "AND notif_type = 'REPOST' AND ref_post_id = $3::uuid",
        to.did, frm.did, post_id,
    )


async def _set_repost_time(pool, agent, post_id, minutes):
    base = datetime.now(timezone.utc) - timedelta(days=40)
    await pool.execute(
        "UPDATE reposts SET created_at = $3 WHERE agent_did = $1 AND post_id = $2::uuid",
        agent.did, post_id, base + timedelta(minutes=minutes),
    )


# ── POST / DELETE ─────────────────────────────────────────────────────────────

async def test_repost_twice_is_one_row_and_one_notification(
    client, pool, agents, poster, quiet, optional_login,
):
    author, me = await agents("author"), await agents("reposter")
    pid = await poster(author)
    for _ in range(2):
        r = await client.post(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"post_id": pid, "reposted": True, "repost_count": 1}
    assert await _repost_notifs(pool, author, me, pid) == 1

    r = await client.get(f"/posts/{pid}", headers=me.headers)
    assert r.json()["repost_count"] == 1 and r.json()["reposted"] is True
    r = await client.get(f"/posts/{pid}", headers=author.headers)
    assert r.json()["repost_count"] == 1 and r.json()["reposted"] is False


async def test_undo_then_repost_again_does_not_notify_twice(client, pool, agents, poster, quiet):
    author, me = await agents("author"), await agents("reposter")
    pid = await poster(author)
    await client.post(f"/posts/{pid}/repost", headers=me.headers)
    for _ in range(2):
        r = await client.delete(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"post_id": pid, "reposted": False, "repost_count": 0}
    await client.post(f"/posts/{pid}/repost", headers=me.headers)
    assert await _repost_notifs(pool, author, me, pid) == 1


async def test_own_post_may_be_reposted_without_a_notification(client, pool, agents, poster, quiet):
    me = await agents("self")
    pid = await poster(me)
    r = await client.post(f"/posts/{pid}/repost", headers=me.headers)
    assert r.status_code == 200 and r.json()["repost_count"] == 1
    assert await _repost_notifs(pool, me, me, pid) == 0


async def test_sign_in_required(client, agents, poster):
    author = await agents("author")
    pid = await poster(author)
    assert (await client.post(f"/posts/{pid}/repost")).status_code == 401
    assert (await client.delete(f"/posts/{pid}/repost")).status_code == 401


async def test_missing_hidden_and_unreadable_posts_are_404(client, pool, agents, poster, quiet):
    author, me = await agents("author"), await agents("reposter")
    hidden = await poster(author)
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", hidden)
    private = await poster(author, visibility="PRIVATE")
    missing = "00000000-0000-4000-8000-000000000000"
    for pid in (hidden, private, missing):
        r = await client.post(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 404, (pid, r.text)
        r = await client.delete(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 404, (pid, r.text)
    # Not even the author may repost their own hidden post.
    r = await client.post(f"/posts/{hidden}/repost", headers=author.headers)
    assert r.status_code == 404
    assert await pool.fetchval("SELECT count(*) FROM reposts WHERE agent_did = $1", me.did) == 0


async def test_own_private_or_closed_post_is_422(client, pool, agents, poster, quiet):
    me = await agents("self")
    private = await poster(me, visibility="PRIVATE")
    closed = await poster(me)
    await pool.execute("UPDATE posts SET status = 'CLOSED' WHERE post_id = $1::uuid", closed)
    for pid in (private, closed):
        r = await client.post(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 422, r.text


@pytest.mark.parametrize("direction", ["i_blocked", "they_blocked"])
async def test_block_either_way_is_403(client, pool, agents, poster, quiet, direction):
    author, me = await agents("author"), await agents("reposter")
    pid = await poster(author)
    if direction == "i_blocked":
        await _block(pool, me, author)
    else:
        await _block(pool, author, me)
    r = await client.post(f"/posts/{pid}/repost", headers=me.headers)
    assert r.status_code == 403, r.text
    assert await _repost_notifs(pool, author, me, pid) == 0


async def test_undo_still_works_after_a_hide_or_a_block(client, pool, agents, poster, quiet):
    author, me = await agents("author"), await agents("reposter")
    a, b = await poster(author), await poster(author, minutes=1)
    await client.post(f"/posts/{a}/repost", headers=me.headers)
    await client.post(f"/posts/{b}/repost", headers=me.headers)
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", a)
    await _block(pool, author, me)
    for pid in (a, b):
        r = await client.delete(f"/posts/{pid}/repost", headers=me.headers)
        assert r.status_code == 200, r.text
    assert await pool.fetchval("SELECT count(*) FROM reposts WHERE agent_did = $1", me.did) == 0


async def test_openapi_lists_both_methods(client):
    spec = (await client.get("/openapi.json")).json()
    path = spec["paths"]["/posts/{post_id}/repost"]
    assert {"post", "delete"} <= set(path)


# ── Timelines ─────────────────────────────────────────────────────────────────

async def _following(client, me, limit=50, cursor=None):
    q = {"limit": limit, **({"cursor": cursor} if cursor else {})}
    r = await client.get("/feed/following", params=q, headers=me.headers)
    assert r.status_code == 200, r.text
    return r.json(), r.headers.get("X-Next-Cursor")


async def test_following_shows_reposts_at_repost_time(client, pool, agents, poster, quiet):
    me, friend, stranger = await agents("me"), await agents("friend"), await agents("stranger")
    await _follow(pool, me, friend)
    old = await poster(stranger, minutes=0, title="old")
    mine = await poster(friend, minutes=10, title="friend")
    await client.post(f"/posts/{old}/repost", headers=friend.headers)
    await _set_repost_time(pool, friend, old, 20)

    page, _ = await _following(client, me)
    assert [p["post_id"] for p in page[:2]] == [old, mine]
    item = page[0]
    assert item["author_did"] == stranger.did
    assert item["reposted_by"]["did"] == friend.did
    assert item["reposted_by"]["handle"] is not None
    assert item["reposted_at"] is not None
    assert item["repost_count"] == 1 and item["reposted"] is False
    assert page[1]["reposted_by"] is None


async def test_following_walk_with_reposts_shows_each_item_once(client, pool, agents, poster, quiet):
    me, f1, f2, other = (
        await agents("me"), await agents("f1"), await agents("f2"), await agents("other"),
    )
    await _follow(pool, me, f1)
    await _follow(pool, me, f2)
    want = []
    for i in range(3):
        want.append((await poster(f1, minutes=i * 10), ""))
    target = await poster(other, minutes=1)
    # Both friends repost the same post at the same moment: two items.
    for f in (f1, f2):
        await client.post(f"/posts/{target}/repost", headers=f.headers)
        await _set_repost_time(pool, f, target, 15)
    want += [(target, f1.did), (target, f2.did)]

    seen, cursor = [], None
    for _ in range(20):
        page, cursor = await _following(client, me, limit=2, cursor=cursor)
        seen += [(p["post_id"], (p["reposted_by"] or {}).get("did", "")) for p in page]
        if cursor is None:
            break
    assert sorted(seen) == sorted(want)
    assert len(seen) == len(set(seen)) == 5


async def test_following_drops_reposts_of_hidden_or_blocked_posts(client, pool, agents, poster, quiet):
    me, friend = await agents("me"), await agents("friend")
    hidden_author, blocked_author, blocks_me, held = (
        await agents("ha"), await agents("ba"), await agents("bm"), await agents("held"),
    )
    await _follow(pool, me, friend)
    pids = {}
    for name, author in (("hidden", hidden_author), ("blocked", blocked_author),
                         ("blocks_me", blocks_me), ("held", held)):
        pids[name] = await poster(author)
        r = await client.post(f"/posts/{pids[name]}/repost", headers=friend.headers)
        assert r.status_code == 200, r.text
    page, _ = await _following(client, me)
    assert {pids[n] for n in pids} <= {p["post_id"] for p in page}

    await pool.execute(
        "UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", pids["hidden"])
    await _block(pool, me, blocked_author)
    await _block(pool, blocks_me, me)
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    page, _ = await _following(client, me)
    assert not ({pids[n] for n in pids} & {p["post_id"] for p in page})


async def test_following_old_two_part_cursor_still_works(client, pool, agents, poster, quiet):
    from src.pagination import encode_cursor
    me = await agents("me")
    a = await poster(me, minutes=0)
    b = await poster(me, minutes=1)
    row = await pool.fetchrow("SELECT created_at, post_id FROM posts WHERE post_id = $1::uuid", b)
    page, _ = await _following(client, me, cursor=encode_cursor(row["created_at"], row["post_id"]))
    assert [p["post_id"] for p in page] == [a]


async def test_profile_posts_tab_shows_own_reposts(
    client, pool, agents, poster, quiet, optional_login,
):
    me, other, viewer = await agents("me"), await agents("other"), await agents("viewer")
    theirs = await poster(other, minutes=0)
    mine = await poster(me, minutes=5)
    await client.post(f"/posts/{theirs}/repost", headers=me.headers)
    await _set_repost_time(pool, me, theirs, 10)

    r = await client.get(f"/agents/{me.did}/posts", headers=viewer.headers)
    assert r.status_code == 200, r.text
    page = r.json()
    assert [p["post_id"] for p in page] == [theirs, mine]
    assert page[0]["reposted_by"]["did"] == me.did
    # A one-at-a-time walk sees both once.
    r = await client.get(f"/agents/{me.did}/posts", params={"limit": 1}, headers=viewer.headers)
    cursor = r.headers["X-Next-Cursor"]
    r = await client.get(
        f"/agents/{me.did}/posts", params={"limit": 1, "cursor": cursor}, headers=viewer.headers,
    )
    assert [p["post_id"] for p in r.json()] == [mine]

    # The viewer and the original's author blocked each other: that repost is gone.
    await _block(pool, other, viewer)
    r = await client.get(f"/agents/{me.did}/posts", headers=viewer.headers)
    assert [p["post_id"] for p in r.json()] == [mine]
    # A hidden original drops out for everyone.
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", theirs)
    r = await client.get(f"/agents/{me.did}/posts", headers=me.headers)
    assert [p["post_id"] for p in r.json()] == [mine]


async def test_latest_stays_originals_only(client, pool, agents, poster, quiet):
    from src.middleware import response_cache
    me, other = await agents("me"), await agents("other")
    pid = await poster(other)
    await client.post(f"/posts/{pid}/repost", headers=me.headers)
    response_cache.invalidate()
    r = await client.get("/feed/latest", params={"limit": 100})
    rows = [p for p in r.json() if p["post_id"] == pid]
    assert all(p["reposted_by"] is None for p in rows)
