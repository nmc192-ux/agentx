"""
Layer 1 S3-4: quote posts on real Postgres.

POST /posts with quote_post_id — 422 when the original is missing, hidden or
                                 unreadable; 403 across a block either way;
                                 one QUOTE notification (none for self-quotes,
                                 private or held quotes)
quoted_post on post responses   — embed, or {"unavailable": true} once the
                                 original is hidden, deleted, private or across
                                 a block; legacy metadata.quoted_post_id rows
quote_count                     — open, active, unhidden quotes only
GET /posts/{id}/quotes          — newest first, read rules, blocks, cursor

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_quotes_db.py -v --db
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


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
async def poster(pool):
    """post(author, minutes=0, visibility=..., metadata=...) → post_id (deleted after)."""
    base = datetime.now(timezone.utc) - timedelta(days=40)
    made: list[str] = []

    async def post(author, minutes=0, visibility="PUBLIC", title="p", metadata=None):
        made.append(str(await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at, visibility, metadata) "
            "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6::post_visibility, $7::jsonb) "
            "RETURNING post_id",
            author.agent_id, author.did, title, f"{title} body",
            base + timedelta(minutes=minutes), visibility, json.dumps(metadata or {}),
        )))
        return made[-1]

    yield post
    await pool.execute(
        "DELETE FROM posts WHERE post_id = ANY($1::uuid[]) OR quote_post_id = ANY($1::uuid[])",
        made,
    )


@pytest_asyncio.fixture
async def quote(client, pool):
    """quote(agent, post_id, text=..., visibility=...) → response (posts deleted after)."""
    made: list[str] = []

    async def _quote(agent, post_id, text="my take", visibility="PUBLIC"):
        r = await client.post("/posts", headers=agent.headers, json={
            "post_type": "UPDATE", "title": "quote", "content": f"{text} {len(made)}",
            "visibility": visibility, "quote_post_id": post_id,
        })
        if r.status_code == 201:
            made.append(r.json()["post_id"])
        return r

    yield _quote
    await pool.execute("DELETE FROM posts WHERE post_id = ANY($1::uuid[])", made)


async def _block(pool, blocker, blocked):
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        blocker.did, blocked.did,
    )


async def _quote_notifs(pool, to, frm) -> list:
    return [r["ref_post_id"] for r in await pool.fetch(
        "SELECT ref_post_id FROM notifications WHERE to_did = $1 AND from_did = $2 "
        "AND notif_type = 'QUOTE'",
        to.did, frm.did,
    )]


# ── Writing a quote ───────────────────────────────────────────────────────────

async def test_quote_embeds_original_counts_and_notifies_once(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author, title="original")

    r = await quote(me, pid)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["quote_post_id"] == pid
    assert body["quoted_post"]["unavailable"] is False
    assert body["quoted_post"]["post_id"] == pid
    assert body["quoted_post"]["author_did"] == author.did
    assert body["quoted_post"]["content"] == "original body"
    assert body["metadata"]["quoted_post_id"] == pid
    assert [str(x) for x in await _quote_notifs(pool, author, me)] == [body["post_id"]]

    r = await client.get(f"/posts/{pid}", headers=me.headers)
    assert r.json()["quote_count"] == 1 and r.json()["quoted_post"] is None
    r = await client.get(f"/posts/{body['post_id']}")          # anonymous reader
    assert r.json()["quoted_post"]["post_id"] == pid


async def test_self_quote_private_quote_and_held_quote_do_not_notify(
    client, pool, agents, poster, quote, quiet,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author)
    assert (await quote(author, pid)).status_code == 201          # self-quote allowed
    assert (await quote(me, pid, visibility="PRIVATE")).status_code == 201
    assert await _quote_notifs(pool, author, author) == []
    assert await _quote_notifs(pool, author, me) == []
    r = await client.get(f"/posts/{pid}", headers=author.headers)
    assert r.json()["quote_count"] == 1                           # the private one not counted


@pytest.mark.parametrize("case", ["missing", "hidden", "private", "own_hidden"])
async def test_quote_of_unreadable_post_is_422(
    client, pool, agents, poster, quote, quiet, case,
):
    author, me = await agents("author"), await agents("quoter")
    if case == "missing":
        pid = "00000000-0000-0000-0000-000000000000"
    elif case == "private":
        pid = await poster(author, visibility="PRIVATE")
    else:
        pid = await poster(me if case == "own_hidden" else author)
        await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", pid)
    r = await quote(me, pid)
    assert r.status_code == 422, r.text
    assert await _quote_notifs(pool, author, me) == []


@pytest.mark.parametrize("direction", ["i_blocked", "they_blocked"])
async def test_quote_across_a_block_is_403(
    client, pool, agents, poster, quote, quiet, direction,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author)
    if direction == "i_blocked":
        await _block(pool, me, author)
    else:
        await _block(pool, author, me)
    r = await quote(me, pid)
    assert r.status_code == 403, r.text
    assert await pool.fetchval(
        "SELECT count(*) FROM posts WHERE quote_post_id = $1::uuid", pid,
    ) == 0


async def test_own_private_post_may_be_quoted_but_others_see_unavailable(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    me, reader = await agents("quoter"), await agents("reader")
    pid = await poster(me, visibility="PRIVATE")
    r = await quote(me, pid)
    assert r.status_code == 201, r.text
    qid = r.json()["post_id"]
    assert r.json()["quoted_post"]["post_id"] == pid
    r = await client.get(f"/posts/{qid}", headers=reader.headers)
    assert r.json()["quoted_post"] == {
        "unavailable": True, "post_id": None, "author_did": None, "author_handle": None,
        "author_name": None, "post_type": None, "title": None, "content": None,
        "created_at": None,
    }


# ── Reading: unavailable originals ────────────────────────────────────────────

async def test_hidden_or_deleted_original_reads_as_unavailable(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author)
    qid = (await quote(me, pid)).json()["post_id"]

    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", pid)
    for headers in (me.headers, author.headers, {}):               # even its author
        r = await client.get(f"/posts/{qid}", headers=headers)
        assert r.json()["quoted_post"]["unavailable"] is True
        assert r.json()["quoted_post"]["content"] is None

    await pool.execute("DELETE FROM posts WHERE post_id = $1::uuid", pid)
    r = await client.get(f"/posts/{qid}", headers=me.headers)
    assert r.json()["quote_post_id"] is None                       # FK SET NULL
    assert r.json()["quoted_post"]["unavailable"] is True          # via metadata


async def test_block_after_quoting_makes_original_unavailable(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    author, me, reader = await agents("author"), await agents("quoter"), await agents("reader")
    pid = await poster(author)
    qid = (await quote(me, pid)).json()["post_id"]

    await _block(pool, reader, author)                             # reader ↔ original author
    r = await client.get(f"/posts/{qid}", headers=reader.headers)
    assert r.json()["quoted_post"]["unavailable"] is True
    r = await client.get(f"/posts/{qid}")                          # others unaffected
    assert r.json()["quoted_post"]["unavailable"] is False

    await _block(pool, author, me)                                 # quoter ↔ original author
    r = await client.get(f"/posts/{qid}")
    assert r.json()["quoted_post"]["unavailable"] is True


async def test_suspended_original_author_reads_as_unavailable(
    client, pool, agents, poster, quote, quiet,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author)
    qid = (await quote(me, pid)).json()["post_id"]
    await pool.execute(
        "UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", author.did,
    )
    r = await client.get(f"/posts/{qid}")
    assert r.json()["quoted_post"]["unavailable"] is True


async def test_legacy_metadata_quote_rows_still_render(
    client, pool, agents, poster, quiet,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author, title="original")
    legacy = await poster(me, minutes=5, title="Reposted",
                          metadata={"quoted_post_id": pid, "repost": True})
    junk = await poster(me, minutes=6, metadata={"quoted_post_id": "not-a-uuid"})

    r = await client.get(f"/posts/{legacy}")
    assert r.json()["quote_post_id"] is None
    assert r.json()["quoted_post"]["post_id"] == pid
    assert r.json()["metadata"]["repost"] is True
    r = await client.get(f"/posts/{junk}")
    assert r.json()["quoted_post"] is None
    r = await client.get(f"/posts/{pid}")
    assert r.json()["quote_count"] == 0                            # legacy rows are not counted

    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", pid)
    r = await client.get(f"/posts/{legacy}")
    assert r.json()["quoted_post"]["unavailable"] is True


# ── GET /posts/{id}/quotes ────────────────────────────────────────────────────

async def test_quotes_list_newest_first_with_read_rules_and_cursor(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    author, reader = await agents("author"), await agents("reader")
    q1, q2, q3, blocked = [await agents(n) for n in ("q1", "q2", "q3", "blockee")]
    pid = await poster(author)
    ids = []
    for a in (q1, q2, q3, blocked):
        ids.append((await quote(a, pid)).json()["post_id"])
    hidden = (await quote(q1, pid, text="hidden")).json()["post_id"]
    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", hidden)
    private = (await quote(q2, pid, visibility="PRIVATE")).json()["post_id"]
    await _block(pool, reader, blocked)

    r = await client.get(f"/posts/{pid}/quotes", headers=reader.headers)
    assert r.status_code == 200, r.text
    got = [p["post_id"] for p in r.json()["posts"]]
    assert got == list(reversed(ids[:3]))
    assert r.json()["total"] == 3
    assert all(p["quoted_post"]["post_id"] == pid for p in r.json()["posts"])

    first = await client.get(f"/posts/{pid}/quotes?limit=2", headers=reader.headers)
    assert [p["post_id"] for p in first.json()["posts"]] == got[:2]
    nxt = await client.get(
        f"/posts/{pid}/quotes?limit=2&cursor={first.json()['next_cursor']}",
        headers=reader.headers,
    )
    assert [p["post_id"] for p in nxt.json()["posts"]] == got[2:]

    r = await client.get(f"/posts/{pid}/quotes")                   # anonymous: blocked one shows
    assert len(r.json()["posts"]) == 4
    r = await client.get(f"/posts/{pid}/quotes", headers=q2.headers)   # own private quote shows
    assert private in [p["post_id"] for p in r.json()["posts"]]
    assert hidden not in [p["post_id"] for p in r.json()["posts"]]


async def test_quotes_list_of_unreadable_post_is_404(
    client, pool, agents, poster, quiet, optional_login,
):
    author, reader = await agents("author"), await agents("reader")
    private = await poster(author, visibility="PRIVATE")
    hidden = await poster(author)
    await pool.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1::uuid", hidden)
    for pid in (private, hidden, "00000000-0000-0000-0000-000000000000"):
        r = await client.get(f"/posts/{pid}/quotes", headers=reader.headers)
        assert r.status_code == 404, (pid, r.text)
    r = await client.get(f"/posts/{private}/quotes", headers=author.headers)
    assert r.status_code == 200


async def test_quote_fields_on_feeds_and_openapi(
    client, pool, agents, poster, quote, quiet, optional_login,
):
    author, me = await agents("author"), await agents("quoter")
    pid = await poster(author)
    qid = (await quote(me, pid)).json()["post_id"]

    r = await client.get(f"/agents/{me.did}/posts", headers=me.headers)   # profile Posts tab
    assert r.status_code == 200, r.text
    items = {p["post_id"]: p for p in r.json()}
    assert items[qid]["quoted_post"]["post_id"] == pid
    r = await client.get(f"/posts?author_did={me.did}")
    assert r.json()["posts"][0]["quoted_post"]["post_id"] == pid

    spec = (await client.get("/openapi.json")).json()
    assert "/posts/{post_id}/quotes" in spec["paths"]
    props = spec["components"]["schemas"]["src__models__post__PostCreate"]["properties"]
    assert "quote_post_id" in props


# ── S3-10 review: a moderator's read access is not a licence to quote ─────────

@pytest.mark.parametrize("role", ["FOUNDER", "OPERATOR"])
async def test_a_moderator_cannot_quote_another_agents_private_post(
    client, pool, agents, poster, quote, quiet, role,
):
    author, mod = await agents("author"), await agents("mod", role=role)
    private = await poster(author, visibility="PRIVATE")
    r = await quote(mod, private)
    assert r.status_code == 422, r.text
    assert await pool.fetchval(
        "SELECT count(*) FROM posts WHERE quote_post_id = $1::uuid", private) == 0
    assert await _quote_notifs(pool, author, mod) == []
    # Reposting it is refused too (the repost rule already asked for PUBLIC).
    r = await client.post(f"/posts/{private}/repost", headers=mod.headers)
    assert r.status_code in (404, 422), r.text
    # A public post by the same author is still quotable by the moderator.
    public = await poster(author)
    assert (await quote(mod, public)).status_code == 201
