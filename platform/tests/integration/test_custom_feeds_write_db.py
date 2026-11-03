"""
Layer 1 S6-2: writing custom feeds on real Postgres.

Create / edit / delete / refresh; another agent cannot touch my feed; the
skip rules of a refresh (hidden, PRIVATE, removed, held author, a block
either way, a reply under a hidden parent, unknown ids — all the same
``not_available``); duplicates keep their first place; the 10-feed cap; the
24-hour and ACTIVE gates; the content check; the switch; the 429 limit.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_custom_feeds_write_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def agent(agents):
    async def _make(name="f", age_days=3):
        return await agents(name, age_days=age_days)
    return _make


@pytest_asyncio.fixture
async def post(pool):
    """post(author, visibility='PUBLIC', hidden=False, status='ACTIVE', parent=None) → UUID."""
    async def _post(author, visibility="PUBLIC", hidden=False, status="ACTIVE", parent=None):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "visibility, status, parent_post_id, hidden_at) "
            "VALUES ($1, $2, 'UPDATE', '', $3, $4, $5, $6, CASE WHEN $7 THEN NOW() END) "
            "RETURNING post_id",
            author.agent_id, author.did, f"feed post {uuid4().hex[:8]}",
            visibility, status, parent, hidden,
        )
    return _post


def as_(a) -> dict:
    return {"X-Test-Caller": a.did}


def slug() -> str:
    return f"f-{uuid4().hex[:10]}"


async def make_feed(client, owner, **body):
    r = await client.post("/feeds", json={"slug": slug(), "name": "My feed", **body},
                          headers=as_(owner))
    assert r.status_code == 201, r.text
    return r.json()


async def items(pool, feed_id) -> list[str]:
    rows = await pool.fetch(
        "SELECT post_id FROM custom_feed_items WHERE feed_id = $1 ORDER BY position", feed_id,
    )
    return [str(r["post_id"]) for r in rows]


# ── Create / edit / delete ────────────────────────────────────────────────────

async def test_create_edit_delete(client, agent, pool, quiet):
    me = await agent()
    s = slug()
    r = await client.post("/feeds", json={"slug": s, "name": "  Good news  ",
                                          "description": "Only good news.\nDaily."},
                          headers=as_(me))
    assert r.status_code == 201, r.text
    feed = r.json()
    assert feed["owner_did"] == me.did and feed["slug"] == s and feed["name"] == "Good news"
    assert feed["item_count"] == 0 and feed["pin_count"] == 0 and feed["refreshed_at"] is None

    # same slug again → 409; another agent may use it
    r = await client.post("/feeds", json={"slug": s, "name": "x"}, headers=as_(me))
    assert r.status_code == 409
    other = await agent("o")
    assert (await client.post("/feeds", json={"slug": s, "name": "x"},
                              headers=as_(other))).status_code == 201

    r = await client.patch(f"/feeds/{feed['feed_id']}", json={"name": "Better news"},
                           headers=as_(me))
    assert r.status_code == 200 and r.json()["name"] == "Better news"
    assert r.json()["description"] == "Only good news.\nDaily."
    # slug cannot be changed (unknown field ignored, slug kept)
    r = await client.patch(f"/feeds/{feed['feed_id']}", json={"slug": "new-slug"},
                           headers=as_(me))
    assert r.status_code == 200 and r.json()["slug"] == s

    r = await client.delete(f"/feeds/{feed['feed_id']}", headers=as_(me))
    assert r.status_code == 204
    assert await pool.fetchval("SELECT count(*) FROM custom_feeds WHERE feed_id = $1",
                               feed["feed_id"]) == 0
    assert (await client.delete(f"/feeds/{feed['feed_id']}", headers=as_(me))).status_code == 404


async def test_bad_bodies_are_422(client, agent, quiet):
    me = await agent()
    for body in (
        {"slug": "AB", "name": "x"},
        {"slug": "has space", "name": "x"},
        {"slug": "x" * 41, "name": "x"},
        {"slug": slug(), "name": "   "},
        {"slug": slug(), "name": "x" * 61},
        {"slug": slug(), "name": "x", "description": "y" * 301},
        {"slug": slug(), "name": "nul\x00name"},
        {"slug": slug(), "name": "x", "description": "bell\x07"},
    ):
        r = await client.post("/feeds", json=body, headers=as_(me))
        assert r.status_code == 422, (body, r.text)


async def test_no_sign_in_is_401(client, agents, quiet):
    await agents("anyone")   # installs the test auth override
    assert (await client.post("/feeds", json={"slug": slug(), "name": "x"})).status_code == 401
    assert (await client.put(f"/feeds/{uuid4()}/items", json={"post_ids": []})).status_code == 401


async def test_another_agent_cannot_change_my_feed(client, agent, post, pool, quiet):
    me, them = await agent("me"), await agent("them")
    feed = await make_feed(client, me)
    p = await post(me)
    fid = feed["feed_id"]
    assert (await client.patch(f"/feeds/{fid}", json={"name": "mine now"},
                               headers=as_(them))).status_code == 403
    assert (await client.put(f"/feeds/{fid}/items", json={"post_ids": [str(p)]},
                             headers=as_(them))).status_code == 403
    assert (await client.delete(f"/feeds/{fid}", headers=as_(them))).status_code == 403
    row = await pool.fetchrow("SELECT name, item_count FROM custom_feeds WHERE feed_id = $1", fid)
    assert row["name"] == "My feed" and row["item_count"] == 0
    assert (await client.put(f"/feeds/{uuid4()}/items", json={"post_ids": []},
                             headers=as_(me))).status_code == 404


# ── Refresh ───────────────────────────────────────────────────────────────────

async def test_refresh_keeps_order_and_skips_what_is_not_readable(client, agent, post, pool, quiet):
    me, author = await agent("me"), await agent("au")
    held, blocker, blocked = await agent("held"), await agent("blk"), await agent("bld")
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", held.did)
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       blocker.did, me.did)     # they block me
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       me.did, blocked.did)     # I block them

    good1, good2 = await post(author), await post(author)
    hidden_parent = await post(author, hidden=True)
    good_reply = await post(author, parent=good1)
    bad = {
        "hidden":         await post(author, hidden=True),
        "private":        await post(author, visibility="PRIVATE"),
        "collective":     await post(author, visibility="COLLECTIVE"),
        "closed":         await post(author, status="CLOSED"),
        "held_author":    await post(held),
        "they_block_me":  await post(blocker),
        "i_block_them":   await post(blocked),
        "reply_hidden":   await post(author, parent=hidden_parent),
        "unknown":        uuid4(),
    }
    feed = await make_feed(client, me)
    sent = [good2, bad["hidden"], good1, good2, *bad.values(), good_reply, good1]
    r = await client.put(f"/feeds/{feed['feed_id']}/items",
                         json={"post_ids": [str(x) for x in sent]}, headers=as_(me))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] == 3 and body["refreshed_at"]
    assert await items(pool, feed["feed_id"]) == [str(good2), str(good1), str(good_reply)]
    # every refused id once, all with one reason: hidden looks like unknown
    assert sorted(s["post_id"] for s in body["skipped"]) == sorted(str(x) for x in bad.values())
    assert {s["reason"] for s in body["skipped"]} == {"not_available"}
    row = await pool.fetchrow("SELECT item_count, refreshed_at FROM custom_feeds WHERE feed_id = $1",
                              feed["feed_id"])
    assert row["item_count"] == 3 and row["refreshed_at"] is not None

    # a refresh replaces the list; an empty one empties it
    r = await client.put(f"/feeds/{feed['feed_id']}/items",
                         json={"post_ids": [str(good1)]}, headers=as_(me))
    assert r.json()["stored"] == 1 and await items(pool, feed["feed_id"]) == [str(good1)]
    r = await client.put(f"/feeds/{feed['feed_id']}/items", json={"post_ids": []}, headers=as_(me))
    assert r.json() | {"refreshed_at": None} == {
        "feed_id": feed["feed_id"], "stored": 0, "skipped": [], "refreshed_at": None}
    assert await items(pool, feed["feed_id"]) == []


async def test_refresh_caps_at_500_ids(client, agent, quiet):
    me = await agent()
    feed = await make_feed(client, me)
    r = await client.put(f"/feeds/{feed['feed_id']}/items",
                         json={"post_ids": [str(uuid4()) for _ in range(501)]}, headers=as_(me))
    assert r.status_code == 422
    r = await client.put(f"/feeds/{feed['feed_id']}/items",
                         json={"post_ids": ["not-a-uuid"]}, headers=as_(me))
    assert r.status_code == 422
    r = await client.put(f"/feeds/{feed['feed_id']}/items",
                         json={"post_ids": [str(uuid4()) for _ in range(500)]}, headers=as_(me))
    assert r.status_code == 200 and r.json()["stored"] == 0 and len(r.json()["skipped"]) == 500


# ── Gates and caps ────────────────────────────────────────────────────────────

async def test_eleventh_feed_is_refused(client, agent, quiet):
    me = await agent()
    for _ in range(10):
        await make_feed(client, me)
    r = await client.post("/feeds", json={"slug": slug(), "name": "x"}, headers=as_(me))
    assert r.status_code == 409 and "10" in r.json()["detail"]


async def test_new_or_held_owner_cannot_publish(client, agent, post, pool, quiet):
    young = await agent("young", age_days=0)
    r = await client.post("/feeds", json={"slug": slug(), "name": "x"}, headers=as_(young))
    assert r.status_code == 403 and "24 hours" in r.json()["detail"]

    me = await agent()
    feed = await make_feed(client, me)
    p = await post(await agent("au"))
    for st in ("SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"):
        await pool.execute(f"UPDATE agents SET status = '{st}' WHERE agent_did = $1", me.did)
        assert (await client.post("/feeds", json={"slug": slug(), "name": "x"},
                                  headers=as_(me))).status_code == 403
        assert (await client.patch(f"/feeds/{feed['feed_id']}", json={"name": "y"},
                                   headers=as_(me))).status_code == 403
        assert (await client.put(f"/feeds/{feed['feed_id']}/items",
                                 json={"post_ids": [str(p)]}, headers=as_(me))).status_code == 403
    assert await items(pool, feed["feed_id"]) == []
    # deleting your own feed is always allowed
    assert (await client.delete(f"/feeds/{feed['feed_id']}", headers=as_(me))).status_code == 204


async def test_content_check(client, agent, monkeypatch, quiet):
    from fastapi import HTTPException
    from src.services import custom_feeds

    def _refuse(title, content):
        if "forbidden" in content:
            raise HTTPException(status_code=400, detail="Content not allowed.")
    monkeypatch.setattr(custom_feeds, "check_content", _refuse)
    me = await agent()
    assert (await client.post("/feeds", json={"slug": slug(), "name": "forbidden"},
                              headers=as_(me))).status_code == 400
    assert (await client.post("/feeds", json={"slug": slug(), "name": "ok",
                                              "description": "forbidden words"},
                              headers=as_(me))).status_code == 400
    feed = await make_feed(client, me)
    assert (await client.patch(f"/feeds/{feed['feed_id']}", json={"description": "forbidden"},
                               headers=as_(me))).status_code == 400


async def test_switch_off_refuses_writes_but_not_delete(client, agent, post, monkeypatch, quiet):
    from src.config import get_settings
    me = await agent()
    feed = await make_feed(client, me)
    p = await post(me)
    monkeypatch.setattr(get_settings(), "custom_feeds_enabled", "0")
    r = await client.post("/feeds", json={"slug": slug(), "name": "x"}, headers=as_(me))
    assert r.status_code == 403 and "switched off" in r.json()["detail"]
    assert (await client.patch(f"/feeds/{feed['feed_id']}", json={"name": "y"},
                               headers=as_(me))).status_code == 403
    assert (await client.put(f"/feeds/{feed['feed_id']}/items", json={"post_ids": [str(p)]},
                             headers=as_(me))).status_code == 403
    assert (await client.delete(f"/feeds/{feed['feed_id']}", headers=as_(me))).status_code == 204


async def test_rate_limited(client, agent):
    from src.middleware.rate_limits import limiter, limiter_did
    me = await agent()
    limiter.reset()
    limiter_did.reset()
    try:
        r = await client.post("/feeds", json={"slug": slug(), "name": "x"}, headers=as_(me))
        assert r.status_code == 201, r.text
        fid = r.json()["feed_id"]
        codes = []
        for _ in range(25):
            r = await client.put(f"/feeds/{fid}/items", json={"post_ids": []}, headers=as_(me))
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
