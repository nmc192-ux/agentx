"""
Integration tests: Phase C security review (EM-5a) — post visibility, against
REAL local Postgres.

What is proven (HTTP → router → Postgres, schema from init-db.sql + alembic head):
  • a COLLECTIVE post is 404 to an anonymous caller, an outsider and a PENDING
    asker; its author, an ACTIVE member and a moderator read it; a PUBLIC post
    is open to all
  • creating it writes no POST_CREATED event (the public activity feeds print
    event titles); a PUBLIC post still does
  • an outsider cannot reply to it (404, nothing stored) and cannot post a
    COLLECTIVE reply into the group from a public thread (403, nothing stored);
    a member can; the reply list shows each caller only what they may read
  • an outsider cannot like, interact with or flag it (404, no row); a member can
  • /posts/similar refuses it as a reference post for an outsider
  • the event readers' filter skips an event about it, keeps one about a public
    post, and is not broken by a payload whose post_id is not a UUID
  • a community member cannot share it into a community; a public post shares;
    the community feed shows open posts only even if a link row exists

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_post_visibility_review_db.py -v --db
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from .test_collective_membership_db import make_collective

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """Limiter off (every caller shares one per-IP bucket here), feed cache and
    the websocket broadcast silenced. ``emit_event`` stays real: the events
    table is part of what is proven."""
    from src.middleware.rate_limits import limiter_did
    from src.routers import posts
    monkeypatch.setattr(posts, "cache_delete", AsyncMock(return_value=None))
    monkeypatch.setattr(posts.connection_manager, "broadcast_global", AsyncMock(return_value=0))
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest_asyncio.fixture(autouse=True)
async def optional_caller(agents):
    """The conftest stands in for get_current_agent only; the reads use the
    optional login, so map it onto the same stand-in (no header → anonymous)."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    async def _optional(request: Request):
        try:
            return await app.dependency_overrides[get_current_agent](request)
        except HTTPException:
            return None

    app.dependency_overrides[get_current_agent_optional] = _optional
    yield
    app.dependency_overrides.pop(get_current_agent_optional, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def add_member(pool, col, agent, status="ACTIVE", role="MEMBER"):
    await pool.execute(
        "INSERT INTO collective_members (collective_id, agent_did, role, status)"
        " VALUES ($1, $2, $3, $4)", col, agent.did, role, status,
    )


def body(title: str, visibility: str = "PUBLIC", collective_id=None) -> dict:
    b = {"post_type": "UPDATE", "title": title,
         "content": f"{title} — {uuid.uuid4().hex[:8]}",
         "metadata": {"progress_percent": 0}, "visibility": visibility}
    if collective_id is not None:
        b["collective_id"] = str(collective_id)
    return b


async def create(client, agent, **kw) -> uuid.UUID:
    resp = await client.post("/posts", json=body(**kw), headers=agent.headers)
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["post_id"])


async def events_about(pool, post_id) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM events WHERE payload->>'post_id' = $1", str(post_id))


class World:
    pass


@pytest_asyncio.fixture
async def world(pool, agents, client):
    w = World()
    w.owner = await agents("owner")
    w.member = await agents("member")
    w.pending = await agents("pending")
    w.outsider = await agents("outsider")
    w.moderator = await agents("mod", role="FOUNDER")
    w.col = await make_collective(pool, w.owner)
    await add_member(pool, w.col, w.member)
    await add_member(pool, w.col, w.pending, status="PENDING")
    w.col_post = await create(client, w.owner, title="Group plan",
                              visibility="COLLECTIVE", collective_id=w.col)
    w.pub_post = await create(client, w.owner, title="Hello world")
    return w


# ── Reads ─────────────────────────────────────────────────────────────────────

async def test_collective_post_is_read_by_members_author_and_moderators_only(client, world):
    w = world
    for who in (None, w.outsider, w.pending):
        headers = who.headers if who is not None else {}
        resp = await client.get(f"/posts/{w.col_post}", headers=headers)
        assert resp.status_code == 404, (who and who.did, resp.text)
        assert "Group plan" not in resp.text
    for who in (w.member, w.owner, w.moderator):
        resp = await client.get(f"/posts/{w.col_post}", headers=who.headers)
        assert resp.status_code == 200, (who.did, resp.text)
        assert resp.json()["title"] == "Group plan"
    assert (await client.get(f"/posts/{w.pub_post}")).status_code == 200


async def test_a_collective_post_is_not_announced(pool, world):
    assert await events_about(pool, world.col_post) == 0
    assert await events_about(pool, world.pub_post) == 1


# ── Replies ───────────────────────────────────────────────────────────────────

async def replies_stored(pool, parent) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM posts WHERE parent_post_id = $1", parent)


async def test_replies_follow_the_rule(client, pool, world):
    w = world
    # an outsider cannot reply to the group's post — and learns nothing
    resp = await client.post(f"/posts/{w.col_post}/replies", json=body("Re"),
                             headers=w.outsider.headers)
    assert resp.status_code == 404, resp.text
    assert await replies_stored(pool, w.col_post) == 0
    # a member can
    resp = await client.post(f"/posts/{w.col_post}/replies", json=body("Re member"),
                             headers=w.member.headers)
    assert resp.status_code == 201, resp.text
    assert await replies_stored(pool, w.col_post) == 1

    # an outsider cannot push a COLLECTIVE reply into the group from a public thread
    resp = await client.post(f"/posts/{w.pub_post}/replies",
                             json=body("Sneak", visibility="COLLECTIVE", collective_id=w.col),
                             headers=w.outsider.headers)
    assert resp.status_code == 403, resp.text
    assert await replies_stored(pool, w.pub_post) == 0
    # a member can
    resp = await client.post(f"/posts/{w.pub_post}/replies",
                             json=body("Members only", visibility="COLLECTIVE", collective_id=w.col),
                             headers=w.member.headers)
    assert resp.status_code == 201, resp.text
    collective_reply = resp.json()["post_id"]

    # the public thread's reply list shows that reply to members only
    anon = await client.get(f"/posts/{w.pub_post}/replies")
    assert anon.status_code == 200 and anon.json()["total"] == 0 and anon.json()["posts"] == []
    out = await client.get(f"/posts/{w.pub_post}/replies", headers=w.outsider.headers)
    assert out.json()["total"] == 0
    mem = await client.get(f"/posts/{w.pub_post}/replies", headers=w.member.headers)
    assert mem.json()["total"] == 1
    assert [p["post_id"] for p in mem.json()["posts"]] == [collective_reply]

    # the group post's thread is 404 to outsiders, open to members
    assert (await client.get(f"/posts/{w.col_post}/replies")).status_code == 404
    assert (await client.get(f"/posts/{w.col_post}/replies",
                             headers=w.outsider.headers)).status_code == 404
    thread = await client.get(f"/posts/{w.col_post}/replies", headers=w.member.headers)
    assert thread.status_code == 200 and thread.json()["total"] == 1


# ── Like, interact, flag, similar ─────────────────────────────────────────────

async def test_outsider_cannot_like_interact_or_flag(client, pool, world):
    w = world
    resp = await client.post(f"/posts/{w.col_post}/like", headers=w.outsider.headers)
    assert resp.status_code == 404, resp.text
    resp = await client.post(f"/posts/{w.col_post}/interact",
                             json={"agent_did": w.outsider.did, "interaction_type": "like"},
                             headers=w.outsider.headers)
    assert resp.status_code == 404, resp.text
    assert await pool.fetchval(
        "SELECT count(*) FROM post_likes WHERE post_id = $1", w.col_post) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE ref_post_id = $1", w.col_post) == 0

    resp = await client.post(f"/posts/{w.col_post}/flag", json={"reason": "spam"},
                             headers=w.outsider.headers)
    assert resp.status_code == 404, resp.text
    assert await pool.fetchval(
        "SELECT count(*) FROM post_flags WHERE post_id = $1", w.col_post) == 0

    # a member can do all three
    resp = await client.post(f"/posts/{w.col_post}/like", headers=w.member.headers)
    assert resp.status_code == 200 and resp.json()["liked"] is True
    resp = await client.post(f"/posts/{w.col_post}/flag", json={"reason": "spam"},
                             headers=w.member.headers)
    assert resp.status_code == 201, resp.text


async def test_similar_refuses_a_reference_post_the_caller_cannot_read(client, world):
    w = world
    resp = await client.get(f"/posts/similar?post_id={w.col_post}", headers=w.outsider.headers)
    assert resp.status_code == 404, resp.text
    assert (await client.get(f"/posts/similar?post_id={w.col_post}")).status_code == 404


# ── The public event readers ──────────────────────────────────────────────────

async def test_event_readers_skip_events_about_non_open_posts(pool, world):
    from src.services.events import EVENT_NOT_ABOUT_HIDDEN_POST
    w = world
    marker = uuid.uuid4().hex
    for post_id in (str(w.col_post), str(w.pub_post), "not-a-uuid"):
        await pool.execute(
            "INSERT INTO events (event_id, event_type, agent_did, payload)"
            " VALUES (gen_random_uuid(), 'POST_CREATED', $1, $2::jsonb)",
            w.owner.did, json.dumps({"post_id": post_id, "title": "x", "marker": marker}),
        )
    rows = await pool.fetch(
        f"SELECT payload FROM events WHERE payload->>'marker' = $1"
        f" AND {EVENT_NOT_ABOUT_HIDDEN_POST}", marker)
    seen = {(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"])["post_id"]
            for r in rows}
    assert seen == {str(w.pub_post), "not-a-uuid"}


# ── Communities ───────────────────────────────────────────────────────────────

async def test_only_open_posts_can_be_shared_into_a_community(pool, world):
    from src.services import community_service
    w = world
    cid = uuid.uuid4()
    await pool.execute(
        "INSERT INTO communities (community_id, name, slug, description, creator_did,"
        " visibility, status, member_count, metadata)"
        " VALUES ($1, $2, $3, 'c', $4, 'PUBLIC', 'ACTIVE', 1, '{}'::jsonb)",
        cid, f"C-{cid.hex[:8]}", f"c-{cid.hex[:8]}", w.member.did,
    )
    await pool.execute(
        "INSERT INTO community_members (community_id, agent_did, role) VALUES ($1, $2, 'MEMBER')",
        cid, w.member.did,
    )
    with pytest.raises(ValueError, match="Post not found"):
        await community_service.add_post_to_community(cid, w.col_post, w.member.did)
    assert await pool.fetchval(
        "SELECT count(*) FROM community_posts WHERE community_id = $1", cid) == 0

    await community_service.add_post_to_community(cid, w.pub_post, w.member.did)
    # a link row that somehow exists for a non-open post is still not shown
    await pool.execute(
        "INSERT INTO community_posts (community_post_id, community_id, post_id)"
        " VALUES (gen_random_uuid(), $1, $2)", cid, w.col_post,
    )
    feed = await community_service.get_community_feed(cid)
    assert [p.post_id for p in feed] == [w.pub_post]
