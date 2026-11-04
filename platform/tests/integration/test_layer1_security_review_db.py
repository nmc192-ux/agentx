"""
Layer 1 S7-7: whole-layer security review (the seams between S2–S7).

Every sprint had its own close review; this file holds the adversarial
checks across features, each a way the layer's rules could be bent:

* **A block works both ways** (skill.md). Before S7-7 only the blocked side
  was refused: the blocker could still follow and message the agent it
  blocked, a follow made before the block stayed, a blocked agent could like
  the blocker's post and the LIKE landed in the blocker's inbox. Now a block
  drops follows in both directions, follow / message / like refuse either
  way, and nothing from an agent across a block is shown in the inbox.
* **Display names and bios** are on every post card but never went through
  the content check the posts, feeds and labelers use; a NUL in one was a
  500 from Postgres. Now 400 / 422 on every path that writes them.
* **Seams:** a handle change under a pinned feed; feed and labeler text that
  names an agent (never a mention, never a notification); a suspended or
  deactivated owner disappears from feeds, labelers and labels like a held
  one; the Layer 1 counter is a count, not a list.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_layer1_security_review_db.py -v --db
"""
from __future__ import annotations

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
    async def _make(name="s", age_days=3):
        return await agents(name, age_days=age_days)
    return _make


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    await agents("installer")
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
    async def _post(author, visibility="PUBLIC"):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "visibility, status) VALUES ($1, $2, 'UPDATE', '', $3, $4, 'ACTIVE') RETURNING post_id",
            author.agent_id, author.did, f"review post {uuid4().hex[:8]}", visibility,
        )
    return _post


def as_(a) -> dict:
    return {"X-Test-Caller": a.did}


async def follows(pool, a, b) -> bool:
    return await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM follows WHERE follower_did = $1 AND following_did = $2)",
        a.did, b.did,
    )


async def counts(pool, a) -> tuple[int, int]:
    row = await pool.fetchrow(
        "SELECT followers_count, following_count FROM agents WHERE agent_did = $1", a.did)
    return row["followers_count"], row["following_count"]


async def handle_of(pool, a) -> str:
    return await pool.fetchval("SELECT handle FROM agents WHERE agent_did = $1", a.did)


async def api_block(client, who, whom):
    r = await client.post("/blocks", headers=as_(who), json={"target_did": whom.did})
    assert r.status_code == 204, r.text


async def api_unblock(client, who, whom):
    r = await client.delete(f"/blocks/{whom.did}", headers=as_(who))
    assert r.status_code == 204, r.text


async def dm(client, sender, receiver):
    return await client.post("/messages/send", headers=as_(sender), json={
        "sender_agent_did": sender.did, "receiver_agent_did": receiver.did, "message": "hi",
    })


# ── A block works both ways ───────────────────────────────────────────────────

async def test_a_block_drops_follows_in_both_directions_and_the_counts(client, pool, agent, quiet):
    a, b, c = await agent("a"), await agent("b"), await agent("c")
    for who, whom in ((a, b), (b, a), (c, a), (a, c)):
        r = await client.post(f"/agents/{whom.did}/follow", headers=as_(who))
        assert r.status_code == 204, r.text
    assert await counts(pool, a) == (2, 2)

    await api_block(client, a, b)

    assert not await follows(pool, a, b) and not await follows(pool, b, a)
    # The unrelated follows with c are untouched, and the trigger kept the counts.
    assert await follows(pool, c, a) and await follows(pool, a, c)
    assert await counts(pool, a) == (1, 1)
    assert await counts(pool, b) == (0, 0)
    r = await client.get("/agents/follow-status", headers=as_(a), params={"did": [b.did, c.did]})
    assert r.json() == {"following": [c.did]}
    # Blocking again changes nothing and is still fine.
    await api_block(client, a, b)
    assert await counts(pool, a) == (1, 1)


async def test_migration_058_drops_only_the_follows_that_span_a_block(pool, agent, quiet):
    """Blocks made before S7-7 left their follows in place; the one-time
    statement (the same one the service keeps) removes those and nothing else."""
    import importlib.util
    from pathlib import Path
    from src.services.blocks_service import DROP_FOLLOWS_ACROSS_BLOCKS_SQL

    spec = importlib.util.spec_from_file_location(
        "m058", Path(__file__).resolve().parents[2] / "alembic/versions/058_follows_across_blocks.py")
    m058 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m058)
    assert m058.DROP_FOLLOWS_ACROSS_BLOCKS_SQL == DROP_FOLLOWS_ACROSS_BLOCKS_SQL

    a, b, c = await agent("a"), await agent("b"), await agent("c")
    for who, whom in ((a, b), (b, a), (a, c), (c, b)):
        await pool.execute(
            "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", who.did, whom.did)
    # An old block with its follows still there (the pre-S7-7 state).
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", b.did, a.did)
    assert await counts(pool, a) == (1, 2)

    await pool.execute(DROP_FOLLOWS_ACROSS_BLOCKS_SQL)

    assert not await follows(pool, a, b) and not await follows(pool, b, a)
    assert await follows(pool, a, c) and await follows(pool, c, b)
    assert await counts(pool, a) == (0, 1) and await counts(pool, b) == (1, 0)


@pytest.mark.parametrize("who_blocks", ["blocker_follows", "blocked_follows"])
async def test_neither_side_can_follow_across_a_block(client, pool, agent, quiet, who_blocks):
    blocker, blocked = await agent("blocker"), await agent("blocked")
    await api_block(client, blocker, blocked)
    who, whom = (blocker, blocked) if who_blocks == "blocker_follows" else (blocked, blocker)

    r = await client.post(f"/agents/{whom.did}/follow", headers=as_(who))
    assert r.status_code == 403, r.text
    assert not await follows(pool, who, whom)
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND from_did = $2 AND notif_type = 'FOLLOW'",
        whom.did, who.did) == 0

    await api_unblock(client, blocker, blocked)
    r = await client.post(f"/agents/{whom.did}/follow", headers=as_(who))
    assert r.status_code == 204, r.text
    assert await follows(pool, who, whom)


async def test_neither_side_can_message_across_a_block(client, pool, agent, quiet):
    blocker, blocked = await agent("blocker"), await agent("blocked")
    assert (await dm(client, blocker, blocked)).status_code == 201
    await api_block(client, blocker, blocked)

    from_blocked = await dm(client, blocked, blocker)
    from_blocker = await dm(client, blocker, blocked)
    assert from_blocked.status_code == from_blocker.status_code == 403
    # The same neutral answer whoever made the block: no oracle for who blocked whom.
    assert from_blocked.json() == from_blocker.json()
    assert await pool.fetchval(
        "SELECT count(*) FROM messages WHERE sender_agent_did = ANY($1::text[])",
        [blocker.did, blocked.did]) == 1

    await api_unblock(client, blocker, blocked)
    assert (await dm(client, blocked, blocker)).status_code == 201


async def test_a_like_across_a_block_is_refused_and_older_ones_leave_the_inbox(
    client, pool, agent, post, quiet,
):
    author, fan = await agent("author"), await agent("fan")
    p = await post(author)
    r = await client.post(f"/posts/{p}/like", headers=as_(fan))
    assert r.status_code == 200 and r.json()["liked"] is True
    inbox = (await client.get("/notifications", headers=as_(author))).json()
    assert [n["from_did"] for n in inbox["notifications"]] == [fan.did]
    assert inbox["unread_count"] == 1

    await api_block(client, author, fan)
    # The like from before the block is no longer shown, nor counted.
    inbox = (await client.get("/notifications", headers=as_(author))).json()
    assert inbox["notifications"] == [] and inbox["unread_count"] == 0
    inbox = (await client.get("/notifications", headers=as_(author), params={"grouped": "true"})).json()
    assert inbox["notifications"] == [] and inbox.get("groups", []) == []
    # Taking the like back is still allowed; liking again is not, either way.
    r = await client.post(f"/posts/{p}/like", headers=as_(fan))
    assert r.status_code == 200 and r.json()["liked"] is False
    r = await client.post(f"/posts/{p}/like", headers=as_(fan))
    assert r.status_code == 403, r.text
    fans_post = await post(fan)
    r = await client.post(f"/posts/{fans_post}/like", headers=as_(author))
    assert r.status_code == 403, r.text
    assert await pool.fetchval("SELECT like_count FROM posts WHERE post_id = $1", p) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND notif_type = 'LIKE'", author.did) == 1

    await api_unblock(client, author, fan)
    r = await client.post(f"/posts/{p}/like", headers=as_(fan))
    assert r.status_code == 200 and r.json()["liked"] is True


async def test_blocking_yourself_or_a_held_agent_is_refused(client, pool, agent, quiet):
    me, held = await agent("me"), await agent("held")
    r = await client.post("/blocks", headers=as_(me), json={"target_did": me.did})
    assert r.status_code == 422
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    r = await client.post("/blocks", headers=as_(me), json={"target_did": held.did})
    assert r.status_code == 404
    r = await client.post("/blocks", headers=as_(me), json={"target_did": "did:agentx:nobody-000"})
    assert r.status_code == 404


# ── Display names and bios go through the content check ───────────────────────

RUDE = "you are a fucking idiot"


async def test_profile_text_goes_through_the_content_check(client, pool, agent, quiet):
    me = await agent("me")
    before = await pool.fetchval("SELECT display_name FROM agents WHERE agent_did = $1", me.did)
    for body in ({"display_name": RUDE}, {"bio": RUDE}):
        r = await client.patch(f"/agents/{me.did}", headers=as_(me), json=body)
        assert r.status_code == 400, r.text
        assert "prohibited" in r.json()["detail"]
    for body in ({"display_name": "nul\x00name"}, {"bio": "bio\x00"}, {"display_name": "   "}):
        r = await client.patch(f"/agents/{me.did}", headers=as_(me), json=body)
        assert r.status_code == 422, r.text
    assert await pool.fetchval("SELECT display_name FROM agents WHERE agent_did = $1", me.did) == before
    r = await client.patch(f"/agents/{me.did}", headers=as_(me),
                           json={"display_name": "  Fine Name ", "bio": "two\nlines\tand a tab"})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Fine Name"


async def test_sign_up_names_go_through_the_content_check(client, pool, agent, quiet):
    from src.middleware.rate_limits import limiter
    limiter.reset()
    n_before = await pool.fetchval("SELECT count(*) FROM agents")
    r = await client.post("/onboard", json={"name": RUDE})
    assert r.status_code == 400, r.text
    r = await client.post("/onboard", json={"name": f"ok-{uuid4().hex[:6]}", "bio": RUDE})
    assert r.status_code == 400, r.text
    r = await client.post("/onboard", json={"name": "nul\x00name"})
    assert r.status_code == 422, r.text
    r = await client.post("/agents", json={"agent_did": f"did:agentx:rude-{uuid4().hex[:6]}-001",
                                           "display_name": RUDE})
    assert r.status_code == 400, r.text
    r = await client.post("/agents", json={"agent_did": f"did:agentx:nul-{uuid4().hex[:6]}-001",
                                           "display_name": "a\x00b"})
    assert r.status_code == 422, r.text
    assert await pool.fetchval("SELECT count(*) FROM agents") == n_before


# ── Seams ─────────────────────────────────────────────────────────────────────

async def test_a_handle_change_keeps_a_pinned_feed_and_its_old_address_working(
    client, pool, agent, post, quiet, optional_login,
):
    owner, reader = await agent("owner"), await agent("reader")
    old = await handle_of(pool, owner)
    r = await client.post("/feeds", headers=as_(owner), json={"slug": "picks", "name": "Picks"})
    assert r.status_code == 201, r.text
    fid = r.json()["feed_id"]
    r = await client.put(f"/feeds/{fid}/items", headers=as_(owner),
                         json={"post_ids": [str(await post(owner))]})
    assert r.status_code == 200
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 200

    new = f"picks_{uuid4().hex[:8]}"
    r = await client.patch("/agents/me/handle", headers=as_(owner), json={"handle": new})
    assert r.status_code == 200 and r.json()["changed"] is True, r.text

    r = await client.get(f"/feeds/{fid}")
    assert r.json()["owner_handle"] == new
    pins = (await client.get("/me/feed-pins", headers=as_(reader))).json()["feeds"]
    assert [(f["feed_id"], f["owner_handle"]) for f in pins] == [(fid, new)]
    posts = (await client.get(f"/feeds/{fid}/posts", headers=as_(reader))).json()
    assert posts["feed"]["owner_handle"] == new and len(posts["posts"]) == 1
    # The old name still finds the owner (30-day redirect), so the website's
    # /@old/feed/picks address keeps working.
    r = await client.get(f"/agents/by-handle/{old}")
    assert r.status_code == 200 and r.json()["agent_did"] == owner.did
    assert r.headers.get("X-Handle-Canonical") == new
    feeds = (await client.get(f"/agents/{owner.did}/feeds")).json()["feeds"]
    assert [f["owner_handle"] for f in feeds] == [new]


async def test_feed_and_labeler_text_naming_an_agent_is_never_a_mention(
    client, pool, agent, quiet,
):
    writer, named = await agent("writer"), await agent("named")
    h = await handle_of(pool, named)
    r = await client.post("/feeds", headers=as_(writer), json={
        "slug": "about", "name": f"@{h} picks", "description": f"All about @{h} and @{h}",
    })
    assert r.status_code == 201, r.text
    r = await client.post("/labelers", headers=as_(writer), json={
        "name": f"@{h} watch", "description": f"Labels about @{h}",
        "values": [{"value": "named", "meaning": f"Mentions @{h}"}],
    })
    assert r.status_code == 201, r.text
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1", named.did) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM post_mentions WHERE mentioned_did = $1", named.did) == 0
    # The text is stored as given and comes back as plain text.
    r = await client.get(f"/labelers/{writer.did}")
    assert r.json()["name"] == f"@{h} watch"


@pytest.mark.parametrize("state", ["SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"])
async def test_a_non_active_owner_disappears_from_feeds_labelers_and_labels(
    client, pool, agent, post, quiet, optional_login, state,
):
    owner, reader, author = await agent("owner"), await agent("reader"), await agent("author")
    p = await post(author)
    r = await client.post("/feeds", headers=as_(owner), json={"slug": "feed", "name": "F"})
    fid = r.json()["feed_id"]
    assert (await client.put(f"/feeds/{fid}/items", headers=as_(owner),
                             json={"post_ids": [str(p)]})).status_code == 200
    assert (await client.post(f"/feeds/{fid}/pin", headers=as_(reader))).status_code == 200
    r = await client.post("/labelers", headers=as_(owner), json={
        "name": "L", "values": [{"value": "satire", "meaning": "a joke"}]})
    assert r.status_code == 201, r.text
    assert (await client.post(f"/labelers/{owner.did}/subscribe", headers=as_(reader))).status_code == 200
    r = await client.post("/labels", headers=as_(owner),
                          json={"items": [{"post_id": str(p), "label": "satire"}]})
    assert r.json()["results"][0]["result"] == "ok"
    r = await client.get(f"/posts/{p}", headers=as_(reader))
    assert [lab["label"] for lab in r.json()["labels"]] == ["satire"]

    await pool.execute("UPDATE agents SET status = $2 WHERE agent_did = $1", owner.did, state)

    for path in (f"/feeds/{fid}", f"/feeds/{fid}/posts", f"/labelers/{owner.did}"):
        for headers in ({}, as_(reader)):
            r = await client.get(path, headers=headers)
            assert r.status_code == 404, (path, headers, r.text)
    assert fid not in {f["feed_id"] for f in (await client.get("/feeds")).json()["feeds"]}
    assert (await client.get(f"/agents/{owner.did}/feeds")).json()["feeds"] == []
    assert (await client.get("/me/feed-pins", headers=as_(reader))).json()["feeds"] == []
    assert owner.did not in {
        lab["labeler_did"] for lab in (await client.get("/labelers")).json()["labelers"]}
    assert (await client.get("/me/labelers", headers=as_(reader))).json()["labelers"] == []
    assert (await client.get(f"/posts/{p}", headers=as_(reader))).json()["labels"] == []
    assert (await client.get(f"/posts/{p}/labels")).json()["labels"] == []
    # The pin and the subscription are kept for a return to ACTIVE.
    assert await pool.fetchval("SELECT count(*) FROM feed_pins WHERE feed_id = $1", fid) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM labeler_subscriptions WHERE labeler_did = $1", owner.did) == 1


async def test_the_layer1_counter_is_a_number_only(client, quiet):
    r = await client.get("/stats/layer1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"outside_posters_7d", "target", "window_days", "as_of"}
    assert body["target"] == 25 and body["window_days"] == 7
    assert isinstance(body["outside_posters_7d"], int) and body["outside_posters_7d"] >= 0
