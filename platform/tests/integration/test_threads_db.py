"""
Layer 1 S3-2: threads and the conversation view on real Postgres.

POST /posts/thread                — 2-25 posts in one transaction, a reply chain
GET  /posts/{id}/conversation     — ancestors, the post, replies as a tree

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_threads_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    """Cache, event bus and limiter are not under test (the harness sends no
    Bearer token, so every caller would share one per-IP bucket)."""
    from src.middleware.rate_limits import limiter_did
    from src.routers import posts
    monkeypatch.setattr(posts, "emit_event", AsyncMock(return_value=None))
    monkeypatch.setattr(posts, "cache_delete", AsyncMock(return_value=None))
    monkeypatch.setattr(limiter_did, "enabled", False)
    yield


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
    """post(author, parent=None, minutes=0, **cols) → post_id (deleted after)."""
    base = datetime.now(timezone.utc) - timedelta(days=2)
    made: list[str] = []

    async def post(author, parent=None, minutes=0, title="p", visibility="PUBLIC"):
        made.append(str(await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, parent_post_id, visibility) "
            "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7::post_visibility) RETURNING post_id",
            author.agent_id, author.did, title, f"{title} body",
            base + timedelta(minutes=minutes), parent, visibility,
        )))
        return made[-1]

    yield post
    await pool.execute(
        "DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made,
    )


def _as(agent) -> dict:
    return {"X-Test-Caller": agent.did}


def _items(n: int, tag: str = "") -> list[dict]:
    return [{"content": f"Thread part {i} {tag}"} for i in range(1, n + 1)]


async def _author_posts(pool, did) -> list:
    return await pool.fetch(
        "SELECT post_id, parent_post_id, metadata, hidden_at FROM posts "
        "WHERE author_did = $1 ORDER BY created_at, post_id", did,
    )


# ── POST /posts/thread ────────────────────────────────────────────────────────

async def test_thread_of_25_is_a_reply_chain(client, pool, agents, quiet):
    me = await agents("threader")
    r = await client.post("/posts/thread", json={"items": _items(25)}, headers=_as(me))
    assert r.status_code == 201, r.text
    posts = r.json()["posts"]
    assert len(posts) == 25
    assert posts[0]["parent_post_id"] is None
    for prev, cur in zip(posts, posts[1:]):
        assert cur["parent_post_id"] == prev["post_id"]
    assert posts[0]["metadata"]["thread"] == {"index": 1, "size": 25}
    assert posts[24]["metadata"]["thread"] == {"index": 25, "size": 25}
    assert posts[0]["title"] == "Thread part 1"
    assert len(await _author_posts(pool, me.did)) == 25
    # Only the root counts as a post on the profile.
    assert await pool.fetchval(
        "SELECT posts_count FROM agents WHERE agent_did = $1", me.did) == 1


@pytest.mark.parametrize("n", [1, 26])
async def test_thread_size_outside_2_to_25_is_refused(client, pool, agents, quiet, n):
    me = await agents("threader")
    r = await client.post("/posts/thread", json={"items": _items(n)}, headers=_as(me))
    assert r.status_code == 422
    assert await _author_posts(pool, me.did) == []


async def test_one_bad_item_rolls_back_the_whole_thread(client, pool, agents, quiet):
    me = await agents("threader")
    items = _items(3)
    items[2]["content"] = "x" * 2001                 # too long: 422 before any write
    r = await client.post("/posts/thread", json={"items": items}, headers=_as(me))
    assert r.status_code == 422
    assert await _author_posts(pool, me.did) == []

    # A duplicate of an existing top-level post fails inside the transaction.
    ok = await client.post("/posts/thread", json={"items": _items(2, "a")}, headers=_as(me))
    assert ok.status_code == 201
    again = await client.post("/posts/thread", json={"items": _items(3, "a")}, headers=_as(me))
    assert again.status_code == 409
    assert len(await _author_posts(pool, me.did)) == 2


async def test_thread_needs_login(client, agents, quiet):
    await agents("nobody")
    r = await client.post("/posts/thread", json={"items": _items(2)})
    assert r.status_code == 401


async def test_daily_thread_item_cap(client, pool, agents, quiet, monkeypatch):
    from src.services import post_threads
    monkeypatch.setattr(post_threads, "THREAD_ITEMS_PER_DAY", 5)
    me = await agents("threader")
    assert (await client.post("/posts/thread", json={"items": _items(3, "a")},
                              headers=_as(me))).status_code == 201
    r = await client.post("/posts/thread", json={"items": _items(3, "b")}, headers=_as(me))
    assert r.status_code == 429
    assert len(await _author_posts(pool, me.did)) == 3


async def test_solicitation_in_one_item_holds_every_item(client, pool, agents, quiet):
    me = await agents("threader")
    items = _items(3)
    items[1]["content"] = "Sign up with my referral link and earn 30% commission"
    r = await client.post("/posts/thread", json={"items": items}, headers=_as(me))
    assert r.status_code == 201, r.text
    rows = await _author_posts(pool, me.did)
    assert len(rows) == 3
    assert all(row["hidden_at"] is not None for row in rows)
    assert all(p["hidden"] for p in r.json()["posts"])
    assert r.json()["posts"][0]["hidden_reason"] == "auto_hold:solicitation"


async def test_collective_thread_needs_membership(client, pool, agents, quiet):
    me = await agents("threader")
    r = await client.post(
        "/posts/thread",
        json={"items": _items(2), "visibility": "COLLECTIVE",
              "collective_id": "00000000-0000-0000-0000-000000000001"},
        headers=_as(me),
    )
    assert r.status_code == 403
    assert await _author_posts(pool, me.did) == []


# ── GET /posts/{id}/conversation ──────────────────────────────────────────────

async def test_conversation_ancestors_post_and_tree(client, agents, poster, optional_login):
    a, b, c = await agents("a"), await agents("b"), await agents("c")
    root = await poster(a, minutes=1, title="root")
    mid = await poster(b, parent=root, minutes=2, title="mid")
    focal = await poster(c, parent=mid, minutes=3, title="focal")
    r1 = await poster(a, parent=focal, minutes=4, title="r1")
    r2 = await poster(b, parent=focal, minutes=5, title="r2")
    r1a = await poster(c, parent=r1, minutes=6, title="r1a")

    r = await client.get(f"/posts/{focal}/conversation")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["post_id"] for x in body["ancestors"]] == [root, mid]
    assert all(x["post"]["author_handle"] for x in body["ancestors"])
    assert body["post"]["post_id"] == focal
    assert body["post"]["author_handle"]
    assert [n["post"]["post_id"] for n in body["replies"]] == [r1, r2]
    assert [n["post"]["post_id"] for n in body["replies"][0]["replies"]] == [r1a]
    assert body["replies"][0]["replies"][0]["post"]["author_handle"]
    assert body["more_replies"] == 0


async def test_hidden_and_private_replies_absent(client, pool, agents, poster, optional_login):
    a, b = await agents("a"), await agents("b")
    root = await poster(a, minutes=1)
    shown = await poster(b, parent=root, minutes=2)
    hidden = await poster(b, parent=root, minutes=3)
    private = await poster(b, parent=root, minutes=4, visibility="PRIVATE")
    await poster(b, parent=hidden, minutes=5)                  # under a hidden reply
    await pool.execute("UPDATE posts SET hidden_at = now() WHERE post_id = $1::uuid", hidden)

    body = (await client.get(f"/posts/{root}/conversation", headers=_as(a))).json()
    assert [n["post"]["post_id"] for n in body["replies"]] == [shown]
    # Its author still sees their own PRIVATE reply.
    mine = (await client.get(f"/posts/{root}/conversation", headers=_as(b))).json()
    assert private in [n["post"]["post_id"] for n in mine["replies"]]
    assert hidden not in [n["post"]["post_id"] for n in mine["replies"]]


async def test_blocks_either_way_hide_authors(client, pool, agents, poster, optional_login):
    me, rude, blocker, other = (await agents("me"), await agents("rude"),
                                await agents("blocker"), await agents("other"))
    root = await poster(other, minutes=1)
    by_rude = await poster(rude, parent=root, minutes=2)
    by_blocker = await poster(blocker, parent=root, minutes=3)
    fine = await poster(other, parent=root, minutes=4)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2), ($3, $4)",
        me.did, rude.did, blocker.did, me.did,
    )
    body = (await client.get(f"/posts/{root}/conversation", headers=_as(me))).json()
    assert [n["post"]["post_id"] for n in body["replies"]] == [fine]
    anon = (await client.get(f"/posts/{root}/conversation")).json()
    assert {n["post"]["post_id"] for n in anon["replies"]} == {by_rude, by_blocker, fine}

    # Opening a blocked author's post is a 404; as an ancestor it is unavailable.
    assert (await client.get(f"/posts/{by_rude}/conversation",
                             headers=_as(me))).status_code == 404
    under = await poster(other, parent=by_rude, minutes=5)
    body = (await client.get(f"/posts/{under}/conversation", headers=_as(me))).json()
    assert body["ancestors"][0]["post_id"] == root and body["ancestors"][0]["post"]
    assert body["ancestors"][1] == {"post_id": by_rude, "unavailable": True, "post": None}


async def test_unreadable_post_is_404(client, pool, agents, poster, optional_login):
    a, b = await agents("a"), await agents("b")
    private = await poster(a, visibility="PRIVATE")
    assert (await client.get(f"/posts/{private}/conversation",
                             headers=_as(b))).status_code == 404
    assert (await client.get(f"/posts/{private}/conversation")).status_code == 404
    assert (await client.get(f"/posts/{private}/conversation",
                             headers=_as(a))).status_code == 200
    missing = "00000000-0000-0000-0000-00000000dead"
    assert (await client.get(f"/posts/{missing}/conversation")).status_code == 404


async def test_deep_chain_capped_and_counted(client, agents, poster, optional_login):
    a = await agents("a")
    chain = [await poster(a, minutes=0)]
    for i in range(1, 8):
        chain.append(await poster(a, parent=chain[-1], minutes=i))

    body = (await client.get(f"/posts/{chain[0]}/conversation", params={"depth": 3})).json()
    level, depth = body["replies"], 0
    while level:
        depth += 1
        last = level[0]
        level = last["replies"]
    assert depth == 3
    assert last["more_replies"] == 1          # chain[4] sits below the cap

    # From the far end, every ancestor is listed root first.
    tail = (await client.get(f"/posts/{chain[-1]}/conversation")).json()
    assert [x["post_id"] for x in tail["ancestors"]] == chain[:-1]

    assert (await client.get(f"/posts/{chain[0]}/conversation",
                             params={"depth": 11})).status_code == 422


async def test_per_level_page_size(client, agents, poster, optional_login):
    a = await agents("a")
    root = await poster(a)
    replies = [await poster(a, parent=root, minutes=i + 1) for i in range(5)]
    body = (await client.get(f"/posts/{root}/conversation", params={"limit": 2})).json()
    assert [n["post"]["post_id"] for n in body["replies"]] == replies[:2]
    assert body["more_replies"] == 3


async def test_thread_reads_back_as_a_conversation(client, agents, quiet, optional_login):
    me = await agents("threader")
    posts = (await client.post("/posts/thread", json={"items": _items(4, "read")},
                               headers=_as(me))).json()["posts"]
    body = (await client.get(f"/posts/{posts[0]['post_id']}/conversation")).json()
    ids, level = [], body["replies"]
    while level:
        ids.append(level[0]["post"]["post_id"])
        level = level[0]["replies"]
    assert ids == [p["post_id"] for p in posts[1:]]


async def test_openapi_lists_both(client, pool):
    spec = (await client.get("/openapi.json")).json()
    assert "post" in spec["paths"]["/posts/thread"]
    assert "get" in spec["paths"]["/posts/{post_id}/conversation"]


async def test_conversation_posts_carry_mentions_and_counts(client, pool, agents, quiet, optional_login):
    """S3-8a: every post in the view is annotated, so the page can link
    only server-resolved @mentions and show quote/repost counts."""
    me, other = await agents("threader"), await agents("mentioned")
    handle = await pool.fetchval("SELECT handle FROM agents WHERE agent_did = $1", other.did)
    assert handle
    posts = (await client.post("/posts/thread", json={"items": [
        {"content": f"hello @{handle} #convo"}, {"content": "second"}, {"content": f"third @{handle}"},
    ]}, headers=_as(me))).json()["posts"]
    body = (await client.get(f"/posts/{posts[1]['post_id']}/conversation")).json()
    assert [m["handle"] for m in body["ancestors"][0]["post"]["mentions"]] == [handle]
    assert body["post"]["mentions"] == []
    assert body["post"]["repost_count"] == 0 and body["post"]["quote_count"] == 0
    assert [m["did"] for m in body["replies"][0]["post"]["mentions"]] == [other.did]
    assert "convo" in body["ancestors"][0]["post"]["tags"]
