"""
Layer 1 S6-3: reading custom feeds, the directory and pins on real Postgres.

Read time re-applies the rules: a post hidden, made private or removed, or an
author held, **after** the refresh is gone on read; blocks either way for a
signed-in reader (and between the owner and an author); a held owner → 404
and not listed; the position cursor is stable and a forged one is 400 or
harmless; pins (idempotent, 11th refused, across a block refused, switch
off), pin counts and ``is_pinned``; the directory's two sorts.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_custom_feeds_read_db.py -v --db
"""
from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware import public_list_limit
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")
    monkeypatch.setenv("AUTH_LIST_LIMITS", "off")
    public_list_limit._parse_limits.cache_clear()
    yield
    public_list_limit._parse_limits.cache_clear()


@pytest_asyncio.fixture
async def agent(agents):
    async def _make(name="r", age_days=3):
        return await agents(name, age_days=age_days)
    return _make


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    await agents("installer")          # installs the required-login override
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
async def post(pool):
    async def _post(author, parent=None):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "visibility, status, parent_post_id) "
            "VALUES ($1, $2, 'UPDATE', '', $3, 'PUBLIC', 'ACTIVE', $4) RETURNING post_id",
            author.agent_id, author.did, f"feed read {uuid4().hex[:8]}", parent,
        )
    return _post


def as_(a) -> dict:
    return {"X-Test-Caller": a.did}


async def make_feed(client, owner, post_ids=()):
    r = await client.post("/feeds", json={"slug": f"r-{uuid4().hex[:10]}", "name": "Read me"},
                          headers=as_(owner))
    assert r.status_code == 201, r.text
    fid = r.json()["feed_id"]
    if post_ids:
        r = await client.put(f"/feeds/{fid}/items",
                             json={"post_ids": [str(p) for p in post_ids]}, headers=as_(owner))
        assert r.status_code == 200 and r.json()["stored"] == len(post_ids), r.text
    return fid


async def read_all(client, fid, headers=None, limit=50) -> list[str]:
    out, cursor = [], None
    for _ in range(50):
        params = {"limit": limit} | ({"cursor": cursor} if cursor else {})
        r = await client.get(f"/feeds/{fid}/posts", params=params, headers=headers or {})
        assert r.status_code == 200, r.text
        out += [p["post_id"] for p in r.json()["posts"]]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out
    raise AssertionError("cursor never ended")


async def directory(client, sort, headers=None) -> list[dict]:
    out, cursor = [], None
    for _ in range(200):
        params = {"sort": sort, "limit": 50} | ({"cursor": cursor} if cursor else {})
        r = await client.get("/feeds", params=params, headers=headers or {})
        assert r.status_code == 200, r.text
        out += r.json()["feeds"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out
    raise AssertionError("cursor never ended")


def cur(*parts) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(parts)).encode()).decode().rstrip("=")


# ── Reading a feed ────────────────────────────────────────────────────────────

async def test_read_in_owner_order_with_meta(client, agent, post, optional_login, quiet):
    owner, author = await agent("own"), await agent("au")
    ps = [await post(author) for _ in range(5)]
    order = [ps[3], ps[0], ps[4], ps[1], ps[2]]
    fid = await make_feed(client, owner, order)

    r = await client.get(f"/feeds/{fid}/posts", params={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feed"]["feed_id"] == fid and body["feed"]["item_count"] == 5
    assert body["feed"]["is_pinned"] is None
    assert [p["post_id"] for p in body["posts"]] == [str(order[0]), str(order[1])]
    assert body["posts"][0]["author_handle"] is not None or body["posts"][0]["author_did"]
    assert await read_all(client, fid, limit=2) == [str(x) for x in order]

    meta = (await client.get(f"/feeds/{fid}")).json()
    assert meta["owner_did"] == owner.did and meta["item_count"] == 5


async def test_hidden_private_removed_or_held_after_refresh_is_gone(
    client, agent, post, pool, optional_login, quiet,
):
    owner, author, held = await agent("own"), await agent("au"), await agent("held")
    keep, hide, private, closed, by_held = (await post(author), await post(author),
                                            await post(author), await post(author),
                                            await post(held))
    parent = await post(author)
    reply = await post(author, parent=parent)
    fid = await make_feed(client, owner, [keep, hide, private, closed, by_held, reply])
    assert len(await read_all(client, fid)) == 6

    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = ANY($1::uuid[])",
                       [hide, parent])
    await pool.execute("UPDATE posts SET visibility = 'PRIVATE' WHERE post_id = $1", private)
    await pool.execute("UPDATE posts SET status = 'CLOSED' WHERE post_id = $1", closed)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", held.did)

    assert await read_all(client, fid) == [str(keep)]
    # the stored list is untouched: the filter is at read time
    assert await pool.fetchval(
        "SELECT count(*) FROM custom_feed_items WHERE feed_id = $1", fid) == 6


async def test_blocks_either_way_for_reader_and_owner(client, agent, post, pool, optional_login, quiet):
    owner, reader = await agent("own"), await agent("rd")
    a_blocks_reader, reader_blocks_b, c = await agent("a"), await agent("b"), await agent("c")
    pa, pb, pc, pc_reply_to_a = (await post(a_blocks_reader), await post(reader_blocks_b),
                                 await post(c), None)
    pc_reply_to_a = await post(c, parent=pa)
    fid = await make_feed(client, owner, [pa, pb, pc, pc_reply_to_a])
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2), ($3, $4)",
                       a_blocks_reader.did, reader.did, reader.did, reader_blocks_b.did)

    assert await read_all(client, fid) == [str(pa), str(pb), str(pc), str(pc_reply_to_a)]
    assert await read_all(client, fid, headers=as_(reader)) == [str(pc)]

    # a later block between the owner and an author drops that author's posts for everyone
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       c.did, owner.did)
    assert await read_all(client, fid) == [str(pa), str(pb)]


async def test_held_owner_is_404_and_not_listed(client, agent, post, pool, optional_login, quiet):
    owner, author, reader = await agent("own"), await agent("au"), await agent("rd")
    fid = await make_feed(client, owner, [await post(author)])
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 200

    for st in ("SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"):
        await pool.execute(f"UPDATE agents SET status = '{st}' WHERE agent_did = $1", owner.did)
        assert (await client.get(f"/feeds/{fid}")).status_code == 404
        assert (await client.get(f"/feeds/{fid}/posts")).status_code == 404
        assert fid not in {f["feed_id"] for f in await directory(client, "new")}
        assert (await client.get(f"/agents/{owner.did}/feeds")).json()["feeds"] == []
        assert (await client.get("/me/feed-pins", headers=as_(reader))).json()["feeds"] == []
        assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 404

    await pool.execute("UPDATE agents SET status = 'ACTIVE' WHERE agent_did = $1", owner.did)
    assert [f["feed_id"] for f in
            (await client.get("/me/feed-pins", headers=as_(reader))).json()["feeds"]] == [fid]
    assert (await client.get(f"/feeds/{uuid4()}")).status_code == 404
    assert (await client.get(f"/feeds/{uuid4()}/posts")).status_code == 404


async def test_cursor_is_stable_and_forgery_is_harmless(client, agent, post, optional_login, quiet):
    owner, author = await agent("own"), await agent("au")
    ps = [await post(author) for _ in range(4)]
    fid = await make_feed(client, owner, ps)
    r = await client.get(f"/feeds/{fid}/posts", params={"limit": 2})
    c = r.json()["next_cursor"]
    again = await client.get(f"/feeds/{fid}/posts", params={"limit": 2, "cursor": c})
    assert [p["post_id"] for p in again.json()["posts"]] == [str(ps[2]), str(ps[3])]
    assert again.json()["next_cursor"] is None

    for bad in ("junk", cur("1"), cur(1.5), cur(True), cur(1, 2), "x" * 600):
        r = await client.get(f"/feeds/{fid}/posts", params={"cursor": bad})
        assert r.status_code in (400, 422), (bad, r.status_code)
    for forged, expect in ((-10**12, ps), (10**30, []), (-1, ps), (0, ps[1:])):
        r = await client.get(f"/feeds/{fid}/posts", params={"cursor": cur(forged)})
        assert r.status_code == 200, (forged, r.text)
        assert [p["post_id"] for p in r.json()["posts"]] == [str(x) for x in expect]


# ── Directory ─────────────────────────────────────────────────────────────────

async def test_directory_sorts_empty_feeds_and_blocks(client, agent, post, pool, optional_login, quiet):
    o1, o2, o3, blocker = await agent("o1"), await agent("o2"), await agent("o3"), await agent("bk")
    reader, author = await agent("rd"), await agent("au")
    p = await post(author)
    f_old = await make_feed(client, o1, [p])
    f_new = await make_feed(client, o2, [p])
    f_empty = await make_feed(client, o3)
    f_blocker = await make_feed(client, blocker, [p])
    await pool.execute("UPDATE custom_feeds SET created_at = NOW() - interval '1 hour' "
                       "WHERE feed_id = $1", f_old)
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       blocker.did, reader.did)
    pinners = [await agent(f"p{i}") for i in range(2)]
    for a in pinners:
        assert (await client.post(f"/feeds/{f_old}/pin", headers=as_(a))).status_code == 200

    new = [f["feed_id"] for f in await directory(client, "new")]
    assert f_empty not in new
    assert new.index(f_blocker) < new.index(f_new) < new.index(f_old)
    popular = await directory(client, "popular")
    ids = [f["feed_id"] for f in popular]
    assert ids.index(f_old) < ids.index(f_new)
    assert next(f for f in popular if f["feed_id"] == f_old)["pin_count"] == 2

    as_reader = await directory(client, "new", headers=as_(reader))
    assert f_blocker not in {f["feed_id"] for f in as_reader}
    assert all(f["is_pinned"] is False for f in as_reader if f["feed_id"] in (f_old, f_new))

    # pins from held accounts do not count
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", pinners[0].did)
    assert (await client.get(f"/feeds/{f_old}")).json()["pin_count"] == 1

    # an agent's own list includes empty feeds
    assert [f["feed_id"] for f in
            (await client.get(f"/agents/{o3.did}/feeds")).json()["feeds"]] == [f_empty]

    for bad in ("junk", cur(1, "2026-01-01T00:00:00", str(uuid4())), cur("2026-01-01T00:00:00+00:00")):
        assert (await client.get("/feeds", params={"cursor": bad})).status_code == 400, bad
    assert (await client.get("/feeds", params={"sort": "top"})).status_code == 422
    huge = cur(10**30, "2026-01-01T00:00:00+00:00", str(uuid4()))
    assert (await client.get("/feeds", params={"cursor": huge})).status_code == 200


# ── Pins ──────────────────────────────────────────────────────────────────────

async def test_pins_order_idempotent_cap_and_unpin(client, agent, post, pool, optional_login, quiet):
    me, author = await agent("me"), await agent("au")
    p = await post(author)
    owners = [await agent(f"o{i}") for i in range(11)]
    fids = [await make_feed(client, o, [p]) for o in owners]

    for fid in fids[:10]:
        r = await client.post(f"/feeds/{fid}/pin", headers=as_(me))
        assert r.status_code == 200 and r.json()["is_pinned"] is True, r.text
    again = await client.post(f"/feeds/{fids[0]}/pin", headers=as_(me))
    assert again.status_code == 200 and again.json()["pin_count"] == 1
    r = await client.post(f"/feeds/{fids[10]}/pin", headers=as_(me))
    assert r.status_code == 409 and "10" in r.json()["detail"]

    pins = (await client.get("/me/feed-pins", headers=as_(me))).json()["feeds"]
    assert [f["feed_id"] for f in pins] == fids[:10]
    assert all(f["is_pinned"] for f in pins)
    assert (await client.get(f"/feeds/{fids[0]}", headers=as_(me))).json()["is_pinned"] is True

    assert (await client.delete(f"/feeds/{fids[0]}/pin", headers=as_(me))).status_code == 204
    assert (await client.delete(f"/feeds/{fids[0]}/pin", headers=as_(me))).status_code == 204
    assert (await client.delete(f"/feeds/{uuid4()}/pin", headers=as_(me))).status_code == 204
    assert (await client.post(f"/feeds/{fids[10]}/pin", headers=as_(me))).status_code == 200
    assert [f["feed_id"] for f in
            (await client.get("/me/feed-pins", headers=as_(me))).json()["feeds"]] == fids[1:]

    # deleting a feed removes its pins
    assert (await client.delete(f"/feeds/{fids[1]}", headers=as_(owners[1]))).status_code == 204
    assert await pool.fetchval("SELECT count(*) FROM feed_pins WHERE agent_did = $1", me.did) == 9


async def test_pin_gates(client, agent, post, pool, monkeypatch, optional_login, quiet):
    from src.config import get_settings
    me, owner, blocker = await agent("me"), await agent("own"), await agent("bk")
    p = await post(owner)
    fid = await make_feed(client, owner, [p])
    f_blocker = await make_feed(client, blocker, [p])
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       blocker.did, me.did)

    assert (await client.post(f"/feeds/{fid}/pin")).status_code == 401
    assert (await client.get("/me/feed-pins")).status_code == 401
    assert (await client.post(f"/feeds/{uuid4()}/pin", headers=as_(me))).status_code == 404
    assert (await client.post(f"/feeds/{f_blocker}/pin", headers=as_(me))).status_code == 403
    # pinned before a block → kept but not shown
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(me))).status_code == 200
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       me.did, owner.did)
    assert (await client.get("/me/feed-pins", headers=as_(me))).json()["feeds"] == []
    await pool.execute("DELETE FROM agent_blocks WHERE blocker_did = $1", me.did)

    young = await agent("young", age_days=0)   # pinning needs no 24 h, only ACTIVE
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(young))).status_code == 200
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", young.did)
    other = await make_feed(client, owner, [p])
    assert (await client.post(f"/feeds/{other}/pin", headers=as_(young))).status_code == 403

    monkeypatch.setattr(get_settings(), "custom_feeds_enabled", "0")
    r = await client.post(f"/feeds/{other}/pin", headers=as_(me))
    assert r.status_code == 403 and "switched off" in r.json()["detail"]
    # reads and unpinning still work with the switch off
    assert (await client.delete(f"/feeds/{fid}/pin", headers=as_(me))).status_code == 204
    assert (await client.get(f"/feeds/{fid}/posts")).status_code == 200


async def test_read_and_pin_limits(client, agent, post, optional_login):
    from src.middleware.rate_limits import limiter, limiter_did
    me, owner = await agent("me"), await agent("own")
    limiter.reset()
    limiter_did.reset()
    try:
        r = await client.post("/feeds", json={"slug": f"r-{uuid4().hex[:10]}", "name": "x"},
                              headers=as_(owner))
        fid = r.json()["feed_id"]
        codes = []
        for _ in range(40):
            r = await client.post(f"/feeds/{fid}/pin", headers=as_(me))
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
