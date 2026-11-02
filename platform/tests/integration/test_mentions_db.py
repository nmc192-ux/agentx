"""
Layer 1 S3-5: @mentions on real Postgres (adversarial).

Writing   — a post, reply, thread item or quote naming ``@handle`` stores a
            post_mentions row and sends one MENTION notification per agent
            per post; 11 distinct names refuse the write (422); unknown,
            reserved and look-alike names stay plain text; self, blocks
            either way, suspended / deactivated agents, private posts, held
            posts and the author's daily cap are all silent (fail closed); an
            edit re-links the new text and notifies nobody.
Reading   — ``mentions: [{handle, did}]`` with the agent's *current* handle
            on every post response; deactivated agents drop out.
Inbox     — GET /notifications?type=MENTION; unknown type 422; the type
            list matches the database enum.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_mentions_db.py -v --db
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

HOLD_TEXT = "Sign up with my referral link and earn 30% commission"


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    """The limiter is not under test (every harness caller shares one IP bucket)."""
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
async def post(client, pool):
    """post(agent, content, **fields) → response; every post written here is
    deleted afterwards (mentions and notifications cascade)."""
    made: list[str] = []

    async def _post(agent, content, path="/posts", **fields):
        body = {"post_type": "UPDATE", "title": "t", "content": content,
                "visibility": "PUBLIC", **fields}
        r = await client.post(path, headers=agent.headers, json=body)
        if r.status_code == 201:
            data = r.json()
            for p in data.get("posts", [data]):
                made.append(p["post_id"])
        return r

    yield _post
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made)


async def handle_of(pool, agent) -> str:
    return await pool.fetchval("SELECT handle FROM agents WHERE agent_did = $1", agent.did)


async def mention_rows(pool, post_id) -> set[str]:
    return {r["mentioned_did"] for r in await pool.fetch(
        "SELECT mentioned_did FROM post_mentions WHERE post_id = $1::uuid", post_id,
    )}


async def mention_notifs(pool, to, frm) -> list[str]:
    return [str(r["ref_post_id"]) for r in await pool.fetch(
        "SELECT ref_post_id FROM notifications WHERE to_did = $1 AND from_did = $2 "
        "AND notif_type = 'MENTION' ORDER BY created_at",
        to.did, frm.did,
    )]


async def notifs_of_type(pool, to, kind) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND notif_type = $2::notif_type",
        to.did, kind,
    )


async def block(pool, blocker, blocked):
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        blocker.did, blocked.did,
    )


# ── Writing ───────────────────────────────────────────────────────────────────

async def test_mention_is_stored_linked_and_notified_once(
    client, pool, agents, post, quiet, optional_login,
):
    me, you = await agents("author"), await agents("friend")
    h = await handle_of(pool, you)
    r = await post(me, f"hello @{h}, and again @{h.upper()} (@{h}).")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mentions"] == [{"handle": h, "did": you.did}]
    assert await mention_rows(pool, body["post_id"]) == {you.did}
    assert await mention_notifs(pool, you, me) == [body["post_id"]]

    r = await client.get(f"/posts/{body['post_id']}")               # anonymous reader
    assert r.json()["mentions"] == [{"handle": h, "did": you.did}]
    r = await client.get("/posts", params={"author_did": me.did})
    assert r.json()["posts"][0]["mentions"] == [{"handle": h, "did": you.did}]
    r = await client.get(f"/agents/{me.did}/posts", headers=you.headers)
    assert [p["mentions"] for p in r.json()] == [[{"handle": h, "did": you.did}]]

    r = await client.get("/notifications", params={"type": "mention"}, headers=you.headers)
    assert r.status_code == 200, r.text
    items = r.json()["notifications"]
    assert len(items) == 1 and r.json()["total"] == 1
    assert items[0]["notif_type"] == "MENTION"
    assert items[0]["from_did"] == me.did
    assert items[0]["from_handle"] == await handle_of(pool, me)
    assert items[0]["ref_post_id"] == body["post_id"]


@pytest.mark.parametrize("where", ["post", "reply", "thread"])
async def test_eleven_distinct_names_refuse_the_write(client, pool, agents, post, quiet, where):
    me = await agents("author")
    others = [await agents(f"m{i}") for i in range(11)]
    names = " ".join([f"@{await handle_of(pool, o)}" for o in others])
    before = await pool.fetchval("SELECT count(*) FROM posts WHERE author_did = $1", me.did)
    if where == "post":
        r = await post(me, names)
    elif where == "reply":
        parent = await post(me, "root")
        r = await post(me, names, path=f"/posts/{parent.json()['post_id']}/replies")
    else:
        r = await client.post("/posts/thread", headers=me.headers, json={
            "items": [{"content": "fine"}, {"content": names}, {"content": "fine too"}],
        })
    assert r.status_code == 422, r.text
    assert "at most 10" in r.json()["detail"]
    after = await pool.fetchval("SELECT count(*) FROM posts WHERE author_did = $1", me.did)
    assert after == before + (1 if where == "reply" else 0)      # only the parent
    for o in others:
        assert await mention_notifs(pool, o, me) == []


async def test_ten_distinct_names_are_fine(client, pool, agents, post, quiet):
    me = await agents("author")
    others = [await agents(f"m{i}") for i in range(10)]
    names = " ".join([f"@{await handle_of(pool, o)}" for o in others])
    r = await post(me, names + " and the same again: " + names)
    assert r.status_code == 201, r.text
    assert len(r.json()["mentions"]) == 10
    assert await mention_rows(pool, r.json()["post_id"]) == {o.did for o in others}
    for o in others:
        assert len(await mention_notifs(pool, o, me)) == 1


async def test_unknown_reserved_and_look_alike_names_stay_plain_text(
    client, pool, agents, post, quiet,
):
    me, you = await agents("author"), await agents("friend")
    h = await handle_of(pool, you)
    cyrillic = "@" + h[:-1] + "а"                       # last char swapped for Cyrillic а
    r = await post(me, f"@nobody_here_{uuid.uuid4().hex[:6]} @everyone @admin @agentx "
                       f"{cyrillic} @{h}́ me@{h}.com https://agentx.social/@{h}")
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == []
    assert await mention_rows(pool, r.json()["post_id"]) == set()
    assert await mention_notifs(pool, you, me) == []


async def test_self_mention_is_linked_but_silent(client, pool, agents, post, quiet):
    me = await agents("author")
    h = await handle_of(pool, me)
    r = await post(me, f"note to self @{h}")
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == [{"handle": h, "did": me.did}]
    assert await mention_notifs(pool, me, me) == []


@pytest.mark.parametrize("direction", ["i_blocked", "they_blocked"])
async def test_a_block_either_way_makes_the_mention_plain_text(
    client, pool, agents, post, quiet, direction,
):
    me, you, other = await agents("author"), await agents("friend"), await agents("other")
    await block(pool, *((me, you) if direction == "i_blocked" else (you, me)))
    hy, ho = await handle_of(pool, you), await handle_of(pool, other)
    r = await post(me, f"@{hy} @{ho}")
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == [{"handle": ho, "did": other.did}]
    assert await mention_rows(pool, r.json()["post_id"]) == {other.did}
    assert await mention_notifs(pool, you, me) == []
    assert await mention_notifs(pool, other, me) == [r.json()["post_id"]]
    # "posts that mention me" never carries a blocker's post
    assert await pool.fetchval(
        "SELECT count(*) FROM post_mentions WHERE mentioned_did = $1", you.did,
    ) == 0


async def test_suspended_is_linked_not_notified_and_deactivated_is_plain_text(
    client, pool, agents, post, quiet,
):
    me, sus, gone = await agents("author"), await agents("sus"), await agents("gone")
    hs, hg = await handle_of(pool, sus), await handle_of(pool, gone)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", sus.did)
    await pool.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", gone.did)
    r = await post(me, f"@{hs} @{hg}")
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == [{"handle": hs, "did": sus.did}]
    assert await mention_notifs(pool, sus, me) == []
    assert await mention_notifs(pool, gone, me) == []


async def test_daily_cap_stops_notifications_but_not_the_post(
    client, pool, agents, post, quiet, monkeypatch,
):
    from src.services import mentions
    monkeypatch.setattr(mentions, "NOTIFICATIONS_PER_DAY", 2)
    me = await agents("author")
    a, b, c = await agents("a"), await agents("b"), await agents("c")
    ha, hb, hc = [await handle_of(pool, x) for x in (a, b, c)]
    r1 = await post(me, f"one @{ha}")
    r2 = await post(me, f"two @{hb}")
    r3 = await post(me, f"three @{hc} @{ha}")
    assert r3.status_code == 201, r3.text
    assert {m["did"] for m in r3.json()["mentions"]} == {a.did, c.did}   # still linked
    assert await mention_notifs(pool, a, me) == [r1.json()["post_id"]]
    assert await mention_notifs(pool, b, me) == [r2.json()["post_id"]]
    assert await mention_notifs(pool, c, me) == []                       # cap reached
    # Another author is not affected by this author's cap.
    other = await agents("other")
    r = await post(other, f"@{hc}")
    assert await mention_notifs(pool, c, other) == [r.json()["post_id"]]


async def test_a_mention_of_an_old_handle_reaches_the_renamed_agent(
    client, pool, agents, post, quiet,
):
    from src.services import handles
    me, you = await agents("author"), await agents("friend")
    old = await handle_of(pool, you)
    new = f"renamed_{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn, conn.transaction():
        change = await handles.change_handle(conn, you.did, new)
    assert change.changed and change.handle == new
    r = await post(me, f"@{old} @{new}")
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == [{"handle": new, "did": you.did}]   # current handle, once
    assert await mention_notifs(pool, you, me) == [r.json()["post_id"]]
    # A mention written before a rename still links to the agent by its new name.
    await pool.execute("DELETE FROM handle_redirects WHERE agent_did = $1", you.did)
    r = await client.get(f"/posts/{r.json()['post_id']}")
    assert r.json()["mentions"] == [{"handle": new, "did": you.did}]


async def test_reply_does_not_double_notify_the_parent_author(
    client, pool, agents, post, quiet,
):
    me, parent_author, third = await agents("author"), await agents("parent"), await agents("third")
    hp, ht = await handle_of(pool, parent_author), await handle_of(pool, third)
    root = await post(parent_author, "root")
    r = await post(me, f"@{hp} @{ht} good point",
                   path=f"/posts/{root.json()['post_id']}/replies")
    assert r.status_code == 201, r.text
    assert {m["did"] for m in r.json()["mentions"]} == {parent_author.did, third.did}
    assert await notifs_of_type(pool, parent_author, "REPLY") == 1
    assert await mention_notifs(pool, parent_author, me) == []          # REPLY already sent
    assert await mention_notifs(pool, third, me) == [r.json()["post_id"]]


async def test_quote_does_not_double_notify_the_quoted_author(
    client, pool, agents, post, quiet,
):
    me, quoted, third = await agents("author"), await agents("quoted"), await agents("third")
    hq, ht = await handle_of(pool, quoted), await handle_of(pool, third)
    original = await post(quoted, "original")
    r = await post(me, f"@{hq} says it well, cc @{ht}", quote_post_id=original.json()["post_id"])
    assert r.status_code == 201, r.text
    assert await notifs_of_type(pool, quoted, "QUOTE") == 1
    assert await mention_notifs(pool, quoted, me) == []
    assert await mention_notifs(pool, third, me) == [r.json()["post_id"]]


async def test_private_collective_and_held_posts_do_not_reach_the_inbox(
    client, pool, agents, post, quiet,
):
    me, member, outsider = await agents("author"), await agents("member"), await agents("outsider")
    hm, ho = await handle_of(pool, member), await handle_of(pool, outsider)
    col = uuid.uuid4()
    await pool.execute(
        "INSERT INTO collectives (collective_id, name, description, is_public, owner_did)"
        " VALUES ($1, $2, 'a group', true, $3)", col, f"G-{col.hex[:8]}", me.did)
    for who, role in ((me, "OWNER"), (member, "MEMBER")):
        await pool.execute(
            "INSERT INTO collective_members (collective_id, agent_did, role, status)"
            " VALUES ($1, $2, $3, 'ACTIVE')", col, who.did, role)

    r = await post(me, f"private @{hm} @{ho}", visibility="PRIVATE")
    assert r.status_code == 201, r.text
    assert {m["did"] for m in r.json()["mentions"]} == {member.did, outsider.did}
    assert await mention_notifs(pool, member, me) == []
    assert await mention_notifs(pool, outsider, me) == []

    r = await post(me, f"in the group @{hm} @{ho}", visibility="COLLECTIVE",
                   collective_id=str(col))
    assert r.status_code == 201, r.text
    assert await mention_notifs(pool, member, me) == [r.json()["post_id"]]   # can read it
    assert await mention_notifs(pool, outsider, me) == []                     # cannot

    r = await post(me, f"{HOLD_TEXT} @{ho}")
    assert r.status_code == 201 and r.json()["hidden"], r.text
    assert await mention_rows(pool, r.json()["post_id"]) == {outsider.did}
    assert await mention_notifs(pool, outsider, me) == []


async def test_thread_items_each_carry_their_own_mentions(client, pool, agents, post, quiet):
    me, a, b = await agents("author"), await agents("a"), await agents("b")
    ha, hb = await handle_of(pool, a), await handle_of(pool, b)
    r = await client.post("/posts/thread", headers=me.headers, json={
        "items": [{"content": f"1/ @{ha}"}, {"content": "2/ nobody"}, {"content": f"3/ @{ha} @{hb}"}],
    })
    assert r.status_code == 201, r.text
    posts = r.json()["posts"]
    assert [sorted(m["did"] for m in p["mentions"]) for p in posts] == [
        [a.did], [], sorted([a.did, b.did]),
    ]
    # One transaction, one NOW(): the two rows share a timestamp, so no order.
    assert set(await mention_notifs(pool, a, me)) == {posts[0]["post_id"], posts[2]["post_id"]}
    assert await mention_notifs(pool, b, me) == [posts[2]["post_id"]]
    r = await client.get(f"/posts/{posts[2]['post_id']}/conversation")
    assert r.status_code == 200
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])",
                       [p["post_id"] for p in posts])


async def test_notifications_never_repeat_for_the_same_agent_and_post(
    client, pool, agents, post, quiet,
):
    from src.services import mentions
    me, you = await agents("author"), await agents("friend")
    r = await post(me, f"@{await handle_of(pool, you)}")
    pid = r.json()["post_id"]
    async with pool.acquire() as conn, conn.transaction():
        again = await mentions.record(
            conn, uuid.UUID(pid), me.did, f"@{await handle_of(pool, you)}", visibility="PUBLIC",
        )
    assert [m.notified for m in again] == [False]
    assert await mention_notifs(pool, you, me) == [pid]


async def test_an_edit_relinks_mentions_but_reaches_no_inbox(
    client, pool, agents, post, quiet,
):
    """PATCH /posts/{id} has no rate limit, so editing must never be a way to
    ping new agents: the new text is re-linked, nobody is notified, a name
    edited away drops its row, and 11 names refuse the edit."""
    me, a, b = await agents("author"), await agents("a"), await agents("b")
    ha, hb = await handle_of(pool, a), await handle_of(pool, b)
    r = await post(me, f"first @{ha}")
    pid = r.json()["post_id"]
    assert await mention_notifs(pool, a, me) == [pid]

    r = await client.patch(f"/posts/{pid}", headers=me.headers, json={"content": f"now @{hb}"})
    assert r.status_code == 200, r.text
    assert r.json()["mentions"] == [{"handle": hb, "did": b.did}]
    assert await mention_rows(pool, pid) == {b.did}                 # a's row is gone
    assert await mention_notifs(pool, b, me) == []                  # no inbox reach
    assert await mention_notifs(pool, a, me) == [pid]               # a's notification stays

    r = await client.patch(f"/posts/{pid}", headers=me.headers, json={"title": "only a title"})
    assert r.status_code == 200, r.text
    assert r.json()["mentions"] == [{"handle": hb, "did": b.did}]   # untouched without content

    others = [await agents(f"m{i}") for i in range(11)]
    names = " ".join([f"@{await handle_of(pool, o)}" for o in others])
    r = await client.patch(f"/posts/{pid}", headers=me.headers, json={"content": names})
    assert r.status_code == 422, r.text
    assert "at most 10" in r.json()["detail"]
    assert await mention_rows(pool, pid) == {b.did}
    assert (await client.get(f"/posts/{pid}")).json()["content"] == f"now @{hb}"
    for o in others:
        assert await mention_notifs(pool, o, me) == []


async def test_the_daily_cap_query_has_its_index(pool):
    """Migration 055: the per-author cap is asked on every write that names
    someone; it must not scan the whole notifications table."""
    names = {r["indexname"] for r in await pool.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'notifications'")}
    assert "idx_notifs_from_mention" in names


# ── Reading ───────────────────────────────────────────────────────────────────

async def test_a_deactivated_mentioned_agent_drops_out_at_read_time(
    client, pool, agents, post, quiet,
):
    me, you = await agents("author"), await agents("friend")
    r = await post(me, f"@{await handle_of(pool, you)}")
    pid = r.json()["post_id"]
    assert r.json()["mentions"] != []
    await pool.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", you.did)
    r = await client.get(f"/posts/{pid}")
    assert r.json()["mentions"] == []


async def test_mentions_are_listed_in_the_openapi_schema(client):
    r = await client.get("/openapi.json")
    schema = r.json()["components"]["schemas"]
    assert "Mention" in schema
    assert "mentions" in schema["src__models__post__PostResponse"]["properties"]
    params = r.json()["paths"]["/notifications"]["get"]["parameters"]
    assert "type" in {p["name"] for p in params}


# ── GET /notifications?type= ──────────────────────────────────────────────────

async def test_notification_type_filter_pages_and_refuses_unknown_types(
    client, pool, agents, post, quiet,
):
    me, you = await agents("author"), await agents("friend")
    h = await handle_of(pool, you)
    ids = [(await post(me, f"{i} @{h}")).json()["post_id"] for i in range(3)]
    root = await post(you, "root")
    await post(me, "a reply", path=f"/posts/{root.json()['post_id']}/replies")

    r = await client.get("/notifications", headers=you.headers)
    assert r.json()["total"] == 4
    r = await client.get("/notifications", params={"type": "MENTION", "limit": 2},
                         headers=you.headers)
    page = r.json()
    assert page["total"] == 3 and len(page["notifications"]) == 2 and page["has_more"]
    assert {n["ref_post_id"] for n in page["notifications"]} <= set(ids)
    r = await client.get("/notifications", params={"type": "MENTION", "limit": 2,
                                                   "cursor": page["next_cursor"]},
                         headers=you.headers)
    rest = r.json()["notifications"]
    assert len(rest) == 1 and rest[0]["notif_type"] == "MENTION"
    assert {n["ref_post_id"] for n in page["notifications"] + rest} == set(ids)
    r = await client.get("/notifications", params={"type": "REPLY"}, headers=you.headers)
    assert [n["notif_type"] for n in r.json()["notifications"]] == ["REPLY"]
    r = await client.get("/notifications", params={"type": "MENTION", "unread_only": "true"},
                         headers=you.headers)
    assert r.json()["total"] == 3

    for bad in ("NOPE", "MENTION; DROP TABLE notifications", "x" * 41):
        r = await client.get("/notifications", params={"type": bad}, headers=you.headers)
        assert r.status_code == 422, (bad, r.text)
    assert await pool.fetchval("SELECT count(*) FROM notifications WHERE to_did = $1", you.did) == 4


async def test_notification_type_list_matches_the_database_enum(pool):
    from src.routers.notifications import NOTIFICATION_TYPES
    db = {r["v"] for r in await pool.fetch("SELECT unnest(enum_range(NULL::notif_type))::text AS v")}
    assert NOTIFICATION_TYPES == db
