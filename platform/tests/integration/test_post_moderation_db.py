"""
Integration tests: post moderation against REAL local Postgres.
Sprint 9, S9-8c (migration 043).

What is proven:
  • flag: no login → 401; one flag per agent per post (second → 409); not
    your own post; stored under the caller's own DID; hidden / missing → 404
  • three established accounts flagging a post hide it; three accounts made
    a minute ago do not; concurrent flags hide it once
  • hide / unhide / queue: no login → 401, ordinary agent → 403, FOUNDER and
    OPERATOR allowed
  • a hidden post is absent from every public reader (lists, feeds, search,
    activity, the public event feed, replies) and refuses likes and replies;
    by id only the author and moderators get it
  • an OrchardsGuide-style post is stored but held, and never announced;
    editing a visible post into a solicitation hides it; editing never unhides
  • after a moderator clears a post the same flags cannot hide it again,
    until its text is edited

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

SOLICITATION = (
    "Join my referral scheme: earn a 30% Bitcoin commission on every purchase "
    "your followers make."
)


@pytest_asyncio.fixture
async def quiet(monkeypatch, agents):
    """Redis cache, websocket fan-out and the limiter are not under test. The
    events table is real: ``emit_event`` is wrapped, not replaced, so the
    public event feed can be checked. The optional-login dependency follows
    the same X-Test-Caller header as the required one."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app
    from src.middleware.rate_limits import limiter_did
    from src.routers import posts

    spy = AsyncMock(wraps=posts.emit_event)
    monkeypatch.setattr(posts, "emit_event", spy)
    monkeypatch.setattr(posts, "cache_delete", AsyncMock(return_value=None))
    monkeypatch.setattr(posts, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(posts, "cache_set", AsyncMock(return_value=None))
    monkeypatch.setattr(posts.connection_manager, "broadcast_global", AsyncMock(return_value=0))
    monkeypatch.setattr(limiter_did, "enabled", False)

    required = app.dependency_overrides[get_current_agent]

    async def _optional(request: Request):
        try:
            return await required(request)
        except HTTPException:
            return None

    app.dependency_overrides[get_current_agent_optional] = _optional
    try:
        yield spy
    finally:
        app.dependency_overrides.pop(get_current_agent_optional, None)


def _update(content: str, title: str = "Update", **extra) -> dict:
    return {"post_type": "UPDATE", "title": title, "content": content,
            "metadata": {"progress_percent": 0}, **extra}


async def _post(client, agent, content: str, **extra) -> dict:
    r = await client.post("/posts", json=_update(content, **extra), headers=agent.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _established(pool, agents, name: str, role: str = "MEMBER"):
    """An agent whose account is older than the flag age threshold."""
    agent = await agents(name, role=role)
    await pool.execute(
        "UPDATE agents SET created_at = NOW() - INTERVAL '3 days' WHERE agent_did = $1",
        agent.did,
    )
    return agent


async def _flag(client, agent, post_id, reason: str = "solicitation"):
    return await client.post(
        f"/posts/{post_id}/flag", json={"reason": reason}, headers=agent.headers,
    )


async def _hidden(pool, post_id) -> tuple:
    row = await pool.fetchrow(
        "SELECT hidden_at, hidden_reason, hidden_by FROM posts WHERE post_id = $1::uuid",
        str(post_id),
    )
    return row["hidden_at"] is not None, row["hidden_reason"], row["hidden_by"]


async def _log(pool, post_id) -> list[str]:
    rows = await pool.fetch(
        "SELECT action FROM post_moderation_log WHERE post_id = $1::uuid ORDER BY created_at",
        str(post_id),
    )
    return [r["action"] for r in rows]


# ── Flags ─────────────────────────────────────────────────────────────────────

async def test_flag_needs_a_login_and_counts_once_per_agent(client, pool, agents, quiet):
    author, bob = await agents("author"), await agents("bob")
    post_id = (await _post(client, author, "an ordinary post"))["post_id"]

    anonymous = await client.post(f"/posts/{post_id}/flag", json={"reason": "spam"})
    assert anonymous.status_code == 401, anonymous.text

    first = await _flag(client, bob, post_id, "spam")
    assert first.status_code == 201, first.text
    assert first.json()["reason"] == "spam"
    assert "hidden" not in first.json()          # the flagger is not told the outcome

    again = await _flag(client, bob, post_id, "abuse")
    assert again.status_code == 409, again.text

    own = await _flag(client, author, post_id)
    assert own.status_code == 400, own.text

    bad_reason = await _flag(client, bob, post_id, "i-dislike-it")
    assert bad_reason.status_code == 422, bad_reason.text

    missing = await _flag(client, bob, "00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404, missing.text

    rows = await pool.fetch(
        "SELECT flagger_did, reason FROM post_flags WHERE post_id = $1::uuid", post_id,
    )
    assert [(r["flagger_did"], r["reason"]) for r in rows] == [(bob.did, "spam")]


async def test_flag_is_stored_under_the_caller_whatever_the_body_says(client, pool, agents, quiet):
    author, mallory, victim = await agents("author"), await agents("mallory"), await agents("victim")
    post_id = (await _post(client, author, "a post"))["post_id"]

    r = await client.post(
        f"/posts/{post_id}/flag",
        json={"reason": "spam", "flagger_did": victim.did, "agent_did": victim.did},
        headers=mallory.headers,
    )
    assert r.status_code == 201, r.text
    flaggers = await pool.fetch(
        "SELECT flagger_did FROM post_flags WHERE post_id = $1::uuid", post_id,
    )
    assert [f["flagger_did"] for f in flaggers] == [mallory.did]


async def test_three_established_flaggers_hide_a_post(client, pool, agents, quiet):
    author = await agents("author")
    post_id = (await _post(client, author, "flag me"))["post_id"]
    flaggers = [await _established(pool, agents, f"flagger{i}") for i in range(3)]

    for flagger in flaggers[:2]:
        assert (await _flag(client, flagger, post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is False

    assert (await _flag(client, flaggers[2], post_id)).status_code == 201
    assert await _hidden(pool, post_id) == (True, "flags", None)
    assert await _log(pool, post_id) == ["flag_hide"]

    # Once hidden, the post cannot be flagged (or found) by anyone else.
    late = await _established(pool, agents, "late")
    assert (await _flag(client, late, post_id)).status_code == 404


async def test_brand_new_accounts_cannot_hide_a_post(client, pool, agents, quiet):
    author = await agents("author")
    post_id = (await _post(client, author, "a post some new accounts dislike"))["post_id"]

    for i in range(5):
        fresh = await agents(f"fresh{i}")            # created just now
        assert (await _flag(client, fresh, post_id)).status_code == 201

    assert (await _hidden(pool, post_id))[0] is False
    stored = await pool.fetchval(
        "SELECT count(*) FROM post_flags WHERE post_id = $1::uuid", post_id,
    )
    assert stored == 5                               # kept for the moderators

    # Suspended accounts do not count either, however old.
    for i in range(3):
        old = await _established(pool, agents, f"suspended{i}")
        await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", old.did)
        assert (await _flag(client, old, post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is False


async def test_concurrent_flags_hide_once(client, pool, agents, quiet):
    author = await agents("author")
    post_id = (await _post(client, author, "everyone flags this at once"))["post_id"]
    flaggers = [await _established(pool, agents, f"f{i}") for i in range(6)]

    answers = await asyncio.gather(*(_flag(client, f, post_id) for f in flaggers))
    codes = sorted(a.status_code for a in answers)
    # The first three are stored; the rest find the post already hidden.
    assert codes == [201, 201, 201, 404, 404, 404], codes
    assert (await _hidden(pool, post_id))[0] is True
    assert await _log(pool, post_id) == ["flag_hide"]


async def test_flags_cannot_hide_a_moderators_post(client, pool, agents, quiet):
    founder = await agents("founder", role="FOUNDER")
    post_id = (await _post(client, founder, "an announcement"))["post_id"]
    for i in range(4):
        flagger = await _established(pool, agents, f"f{i}")
        assert (await _flag(client, flagger, post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is False


# ── Hide / unhide: who may ────────────────────────────────────────────────────

async def test_only_moderators_hide_unhide_and_read_the_queue(client, pool, agents, quiet):
    author, member = await agents("author"), await agents("member")
    delegate = await agents("delegate", role="DELEGATE")
    founder = await agents("founder", role="FOUNDER")
    operator = await agents("operator", role="OPERATOR")
    post_id = (await _post(client, author, "a post"))["post_id"]
    hide = {"reason": "spam", "note": "test"}

    # No login → 401; nothing changes.
    assert (await client.post(f"/posts/{post_id}/hide", json=hide)).status_code == 401
    assert (await client.post(f"/posts/{post_id}/unhide", json={})).status_code == 401
    assert (await client.get("/posts/moderation/queue")).status_code == 401

    # Ordinary agents — the author included — → 403.
    for caller in (member, delegate, author):
        r = await client.post(f"/posts/{post_id}/hide", json=hide, headers=caller.headers)
        assert r.status_code == 403, r.text
        r = await client.post(f"/posts/{post_id}/unhide", json={}, headers=caller.headers)
        assert r.status_code == 403, r.text
        r = await client.get("/posts/moderation/queue", headers=caller.headers)
        assert r.status_code == 403, r.text
    assert (await _hidden(pool, post_id))[0] is False
    assert await _log(pool, post_id) == []

    # FOUNDER hides; a second hide is a 409.
    r = await client.post(f"/posts/{post_id}/hide", json=hide, headers=founder.headers)
    assert r.status_code == 200, r.text
    assert r.json()["hidden"] is True
    assert await _hidden(pool, post_id) == (True, "moderator:spam", founder.did)
    r = await client.post(f"/posts/{post_id}/hide", json=hide, headers=founder.headers)
    assert r.status_code == 409, r.text

    # The author cannot unhide their own post by any route.
    r = await client.post(f"/posts/{post_id}/unhide", json={}, headers=author.headers)
    assert r.status_code == 403, r.text
    r = await client.patch(f"/posts/{post_id}", json={"content": "edited"}, headers=author.headers)
    assert r.status_code == 200 and r.json()["hidden"] is True, r.text
    assert (await _hidden(pool, post_id))[0] is True

    # OPERATOR sees it in the queue and unhides it (no body needed).
    queue = await client.get("/posts/moderation/queue", headers=operator.headers)
    assert queue.status_code == 200, queue.text
    assert post_id in [p["post_id"] for p in queue.json()["posts"]]
    r = await client.post(f"/posts/{post_id}/unhide", headers=operator.headers)
    assert r.status_code == 200, r.text
    assert r.json()["hidden"] is False
    assert (await _hidden(pool, post_id))[0] is False
    assert await _log(pool, post_id) == ["hide", "unhide"]

    # Nothing left to review → 409; unknown post → 404; bad reason → 422.
    r = await client.post(f"/posts/{post_id}/unhide", headers=operator.headers)
    assert r.status_code == 409, r.text
    r = await client.post(
        "/posts/00000000-0000-0000-0000-000000000000/hide", json=hide, headers=founder.headers,
    )
    assert r.status_code == 404, r.text
    r = await client.post(
        f"/posts/{post_id}/hide", json={"reason": "because"}, headers=founder.headers,
    )
    assert r.status_code == 422, r.text


# ── A hidden post is gone from every public reader ────────────────────────────

async def _everywhere(client, pool, viewer, marker: str) -> dict[str, bool]:
    """Where a post whose text contains ``marker`` shows up."""
    from src.services import feed_service, search_service
    from src.services.activity_stream import get_activity_feed_items

    def has(payload) -> bool:
        return marker in str(payload)

    seen = {
        "GET /posts":         has((await client.get("/posts?limit=100")).json()),
        "GET /posts/global":  has((await client.get("/posts/global?limit=100")).json()),
        "GET /feed/global":   has([p.model_dump() for p in await feed_service.get_global_feed(100)]),
        "GET /feed (personal)": has(
            [p.model_dump() for p in await feed_service.generate_feed(viewer.did, limit=100)]
        ),
        "GET /feed/activity": has(await get_activity_feed_items(100)),
        "search":             has([p.model_dump() for p in await search_service.search_posts(marker)]),
        "GET /dashboard/activity": has((await client.get("/dashboard/activity")).json()),
        "GET /agents/{did}/feed": has(
            (await client.get(f"/agents/{viewer.did}/feed?limit=100&include_tasks=false",
                              headers=viewer.headers)).json()
        ),
    }
    # The live event stream runs the same query as the dashboard, by `created_at`.
    from src.services.events import EVENT_NOT_ABOUT_HIDDEN_POST
    rows = await pool.fetch(
        f"SELECT payload FROM events WHERE {EVENT_NOT_ABOUT_HIDDEN_POST} "
        "ORDER BY created_at DESC LIMIT 200"
    )
    seen["WS /events/stream"] = has([r["payload"] for r in rows])
    return seen


async def test_hidden_post_is_absent_everywhere_and_back_after_unhide(
    client, pool, agents, quiet, monkeypatch,
):
    from src.routers import agents as agents_router
    from src.services import feed_service
    for module in (agents_router, feed_service):
        monkeypatch.setattr(module, "cache_get", AsyncMock(return_value=None))
        monkeypatch.setattr(module, "cache_set", AsyncMock(return_value=None))

    author, viewer = await agents("author"), await agents("viewer")
    founder = await agents("founder", role="FOUNDER")
    marker = "zebrafinch" + author.did[-12:-4].replace("-", "")
    post = await _post(client, author, f"{marker} sighting report", title=f"{marker} news")
    post_id = post["post_id"]
    reply = await client.post(
        f"/posts/{post_id}/replies", json=_update("nice one"), headers=viewer.headers,
    )
    assert reply.status_code == 201, reply.text

    before = await _everywhere(client, pool, viewer, marker)
    assert all(before.values()), before               # visible in every reader first

    r = await client.post(
        f"/posts/{post_id}/hide", json={"reason": "solicitation"}, headers=founder.headers,
    )
    assert r.status_code == 200, r.text

    after = await _everywhere(client, pool, viewer, marker)
    assert not any(after.values()), after

    # By id: 404 for the public and other agents; the author and moderators get it.
    assert (await client.get(f"/posts/{post_id}")).status_code == 404
    assert (await client.get(f"/posts/{post_id}", headers=viewer.headers)).status_code == 404
    own = await client.get(f"/posts/{post_id}", headers=author.headers)
    assert own.status_code == 200, own.text
    assert own.json()["hidden"] is True
    assert own.json()["hidden_reason"] == "moderator:solicitation"
    assert (await client.get(f"/posts/{post_id}", headers=founder.headers)).status_code == 200

    # No replies list, no new reply, no like, no interaction, no similar-posts.
    assert (await client.get(f"/posts/{post_id}/replies")).status_code == 404
    r = await client.post(f"/posts/{post_id}/replies", json=_update("hi"), headers=viewer.headers)
    assert r.status_code == 404, r.text
    assert (await client.post(f"/posts/{post_id}/like", headers=viewer.headers)).status_code == 404
    r = await client.post(
        f"/posts/{post_id}/interact",
        json={"agent_did": viewer.did, "interaction_type": "like"},
        headers=viewer.headers,
    )
    assert r.status_code == 404, r.text
    assert (await client.get(f"/posts/similar?post_id={post_id}")).status_code == 404

    # Unhide → back in every reader.
    r = await client.post(f"/posts/{post_id}/unhide", headers=founder.headers)
    assert r.status_code == 200, r.text
    again = await _everywhere(client, pool, viewer, marker)
    assert all(again.values()), again
    assert (await client.get(f"/posts/{post_id}")).status_code == 200


async def test_hidden_reply_leaves_the_thread(client, pool, agents, quiet):
    author, replier = await agents("author"), await agents("replier")
    founder = await agents("founder", role="FOUNDER")
    post_id = (await _post(client, author, "a thread"))["post_id"]
    kept = await client.post(
        f"/posts/{post_id}/replies", json=_update("a fine reply"), headers=replier.headers,
    )
    spam = await client.post(
        f"/posts/{post_id}/replies", json=_update("a rude reply"), headers=replier.headers,
    )
    assert kept.status_code == spam.status_code == 201

    r = await client.post(
        f"/posts/{spam.json()['post_id']}/hide", json={"reason": "abuse"}, headers=founder.headers,
    )
    assert r.status_code == 200, r.text

    thread = (await client.get(f"/posts/{post_id}/replies")).json()
    assert [p["content"] for p in thread["posts"]] == ["a fine reply"]
    assert thread["total"] == 1
    assert (await client.get(f"/posts/{post_id}")).json()["reply_count"] == 1


async def test_private_post_by_id_is_for_its_author(client, pool, agents, quiet):
    author, other = await agents("author"), await agents("other")
    post = await _post(client, author, "note to self", visibility="PRIVATE")
    assert (await client.get(f"/posts/{post['post_id']}")).status_code == 404
    assert (await client.get(f"/posts/{post['post_id']}", headers=other.headers)).status_code == 404
    assert (await client.get(f"/posts/{post['post_id']}", headers=author.headers)).status_code == 200


# ── Auto-hold ─────────────────────────────────────────────────────────────────

async def test_solicitation_is_stored_but_held_and_not_announced(client, pool, agents, quiet):
    author, viewer = await agents("orchards"), await agents("viewer")

    r = await client.post("/posts", json=_update(SOLICITATION), headers=author.headers)
    assert r.status_code == 201, r.text                # held, not refused
    body = r.json()
    assert body["hidden"] is True
    assert body["hidden_reason"] == "auto_hold:solicitation"
    post_id = body["post_id"]

    assert await _hidden(pool, post_id) == (True, "auto_hold:solicitation", None)
    assert await _log(pool, post_id) == ["auto_hold"]
    quiet.assert_not_awaited()                         # no public POST_CREATED event
    from src.routers import posts
    posts.connection_manager.broadcast_global.assert_not_awaited()

    for path in ("/posts?limit=100", "/posts/global?limit=100", "/dashboard/activity"):
        assert "30% Bitcoin commission" not in (await client.get(path)).text, path
    assert (await client.get(f"/posts/{post_id}")).status_code == 404
    assert (await client.get(f"/posts/{post_id}", headers=viewer.headers)).status_code == 404
    assert (await client.get(f"/posts/{post_id}", headers=author.headers)).status_code == 200

    # A post that only mentions the same topics goes straight through.
    fine = await _post(client, author, "Bitcoin fell 3% today; the commission met.")
    assert fine["hidden"] is False
    assert quiet.await_count == 1


async def test_solicitation_is_held_on_every_way_of_posting(client, pool, agents, quiet):
    from src.database import transaction
    from src.services import onboard_service

    author, other = await agents("author"), await agents("other")

    # Title only.
    by_title = await client.post(
        "/posts", json=_update("details inside", title="Earn 20% commission"),
        headers=author.headers,
    )
    assert by_title.status_code == 201 and by_title.json()["hidden"] is True, by_title.text

    # Tags only.
    by_tag = await client.post(
        "/posts", json=_update("hello there", tags=["referral-link"]), headers=author.headers,
    )
    assert by_tag.status_code == 201 and by_tag.json()["hidden"] is True, by_tag.text

    # The legacy {agent_id, type, topic, ...} body.
    legacy = await client.post(
        "/posts",
        json={"agent_id": str(author.agent_id), "type": "note", "topic": "deal",
              "content": "Buy followers cheap, sign up with my link", "confidence": 0.9},
        headers=author.headers,
    )
    assert legacy.status_code == 201 and legacy.json()["hidden"] is True, legacy.text
    assert (await _hidden(pool, legacy.json()["post_id"]))[0] is True

    # A reply: held, and the parent's author is not notified.
    parent = await _post(client, other, "an honest question")
    reply = await client.post(
        f"/posts/{parent['post_id']}/replies",
        json=_update("Payouts in USDT every week, use my promo code"), headers=author.headers,
    )
    assert reply.status_code == 201 and reply.json()["hidden"] is True, reply.text
    notified = await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND notif_type = 'REPLY'",
        other.did,
    )
    assert notified == 0
    assert (await client.get(f"/posts/{parent['post_id']}/replies")).json()["total"] == 0

    # The first post made while signing up.
    async with transaction() as conn:
        first_post_id = await onboard_service._insert_post(
            conn, author.did, {"title": "Hello", "content": SOLICITATION, "tags": []},
        )
    assert (await _hidden(pool, first_post_id))[0] is True

    quiet.assert_awaited_once()                        # only the honest question was announced
    listed = (await client.get(f"/posts?author_did={author.did}&limit=100")).json()
    assert listed["total"] == 0 and listed["posts"] == []


async def test_editing_into_a_solicitation_hides_and_editing_never_unhides(
    client, pool, agents, quiet,
):
    author = await agents("author")
    post = await _post(client, author, "an ordinary post, for now")
    post_id = post["post_id"]
    assert post["hidden"] is False

    edited = await client.patch(
        f"/posts/{post_id}", json={"content": SOLICITATION}, headers=author.headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["hidden"] is True
    assert await _hidden(pool, post_id) == (True, "auto_hold:solicitation", None)
    assert SOLICITATION not in (await client.get("/posts?limit=100")).text

    # Editing the text back does not make it visible again: a moderator does that.
    back = await client.patch(
        f"/posts/{post_id}", json={"content": "an ordinary post again"}, headers=author.headers,
    )
    assert back.status_code == 200 and back.json()["hidden"] is True, back.text
    assert (await _hidden(pool, post_id))[0] is True
    assert await _log(pool, post_id) == ["auto_hold"]

    # An edit goes through the same language check as a new post.
    rude = await client.patch(
        f"/posts/{post_id}", json={"content": "x" * 2001}, headers=author.headers,
    )
    assert rude.status_code in (400, 422), rude.text


# ── Review ────────────────────────────────────────────────────────────────────

async def test_cleared_post_is_not_hidden_again_by_flags_until_edited(client, pool, agents, quiet):
    author = await agents("author")
    founder = await agents("founder", role="FOUNDER")
    post_id = (await _post(client, author, "a post a clique dislikes"))["post_id"]
    flaggers = [await _established(pool, agents, f"f{i}") for i in range(7)]

    for flagger in flaggers[:3]:
        assert (await _flag(client, flagger, post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is True

    queue = (await client.get("/posts/moderation/queue", headers=founder.headers)).json()
    entry = next(p for p in queue["posts"] if p["post_id"] == post_id)
    assert entry["hidden_reason"] == "flags"
    assert entry["flag_count"] == 3 and entry["flag_reasons"] == ["solicitation"]

    r = await client.post(
        f"/posts/{post_id}/unhide", json={"note": "looks fine"}, headers=founder.headers,
    )
    assert r.status_code == 200, r.text

    # A fourth flag is stored but the post stays visible.
    assert (await _flag(client, flaggers[3], post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is False

    # The author rewrites the post: the clearance was for the old text.
    r = await client.patch(f"/posts/{post_id}", json={"content": "new text"}, headers=author.headers)
    assert r.status_code == 200 and r.json()["hidden"] is False, r.text
    assert (await _flag(client, flaggers[4], post_id)).status_code == 201
    assert (await _hidden(pool, post_id))[0] is True
    assert await _log(pool, post_id) == ["flag_hide", "unhide", "flag_hide"]


async def test_queue_lists_hidden_and_flagged_posts(client, pool, agents, quiet):
    author = await agents("author")
    founder = await agents("founder", role="FOUNDER")
    held = (await client.post("/posts", json=_update(SOLICITATION), headers=author.headers)).json()
    flagged = await _post(client, author, "flagged once")
    clean = await _post(client, author, "nobody minds this one")
    flagger = await _established(pool, agents, "flagger")
    assert (await _flag(client, flagger, flagged["post_id"], "abuse")).status_code == 201

    hidden_q = (await client.get(
        "/posts/moderation/queue?state=hidden&limit=200", headers=founder.headers)).json()
    hidden_ids = [p["post_id"] for p in hidden_q["posts"]]
    assert held["post_id"] in hidden_ids
    assert flagged["post_id"] not in hidden_ids and clean["post_id"] not in hidden_ids
    assert hidden_q["total"] >= 1 and hidden_q["state"] == "hidden"

    flagged_q = (await client.get(
        "/posts/moderation/queue?state=flagged&limit=200", headers=founder.headers)).json()
    flagged_ids = [p["post_id"] for p in flagged_q["posts"]]
    assert flagged["post_id"] in flagged_ids
    assert held["post_id"] not in flagged_ids and clean["post_id"] not in flagged_ids
    entry = next(p for p in flagged_q["posts"] if p["post_id"] == flagged["post_id"])
    assert entry["flag_count"] == 1 and entry["flag_reasons"] == ["abuse"]

    bad = await client.get("/posts/moderation/queue?state=everything", headers=founder.headers)
    assert bad.status_code == 422, bad.text

    # A moderator can dismiss the flag on a visible post; it leaves the queue.
    r = await client.post(f"/posts/{flagged['post_id']}/unhide", headers=founder.headers)
    assert r.status_code == 200, r.text
    flagged_q = (await client.get(
        "/posts/moderation/queue?state=flagged&limit=200", headers=founder.headers)).json()
    assert flagged["post_id"] not in [p["post_id"] for p in flagged_q["posts"]]


async def test_deleting_a_post_removes_its_flags_and_log(client, pool, agents, quiet):
    """HUMAN_ACTIONS H4 deletes posts by hand: the new tables must not block it."""
    author = await agents("author")
    founder = await agents("founder", role="FOUNDER")
    post_id = (await _post(client, author, "to be deleted"))["post_id"]
    flagger = await _established(pool, agents, "flagger")
    assert (await _flag(client, flagger, post_id)).status_code == 201
    r = await client.post(
        f"/posts/{post_id}/hide", json={"reason": "spam"}, headers=founder.headers,
    )
    assert r.status_code == 200, r.text

    await pool.execute("DELETE FROM posts WHERE post_id = $1::uuid", post_id)
    assert await pool.fetchval(
        "SELECT count(*) FROM post_flags WHERE post_id = $1::uuid", post_id) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM post_moderation_log WHERE post_id = $1::uuid", post_id) == 0
