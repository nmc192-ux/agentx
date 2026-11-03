"""
Layer 1 S5-2: GET /search on real Postgres.

Each operator of the grammar; what search must never reach (hidden posts,
held authors, either side of a block, replies under a hidden post, a PENDING
image's url, has:media through a pending image); literal LIKE matching
(``100%_``); queries that used to break ``to_tsquery``; keyset paging for
both sorts; the old ``type=communities``; the 422 caps and the 429 limit.

The database is shared across the run, so every test searches for its own
random word.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_search_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def optional_login(agents):
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
async def agent(agents, pool):
    """agent(name, handle=None, bio=None) → Agent with a known handle."""
    async def _make(name="s", handle=None, display_name=None, bio=None):
        a = await agents(name, age_days=3)
        a.handle = handle or f"s{uuid4().hex[:12]}"
        await pool.execute(
            "UPDATE agents SET handle = $2, display_name = COALESCE($3, display_name), "
            "bio = $4 WHERE agent_did = $1",
            a.did, a.handle, display_name, bio,
        )
        return a
    return _make


_BASE = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def post(pool):
    """post(author, content, minutes=0, tags=(), parent=None, hidden=False,
    at=None, link=False) → post_id."""
    async def _post(author, content, minutes=0, tags=(), parent=None, hidden=False,
                    at=None, link=False):
        key = None
        if link:
            key = uuid4().hex + uuid4().hex
            await pool.execute(
                "INSERT INTO link_cards (url_key, url, status) VALUES ($1, $2, 'OK')",
                key, f"https://example.com/{key}",
            )
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "tags, created_at, parent_post_id, hidden_at, link_url_key) "
            "VALUES ($1, $2, 'UPDATE', '', $3, $4, $5, $6, CASE WHEN $7 THEN NOW() END, $8) "
            "RETURNING post_id",
            author.agent_id, author.did, content, list(tags),
            at or (_BASE + timedelta(minutes=minutes)), parent, hidden,
            key,
        )
    return _post


async def _media(pool, owner, post_id, status):
    return await pool.fetchval(
        "INSERT INTO media (owner_did, mime, ext, width, height, bytes, sha256, alt_text, "
        "status, post_id, position) VALUES ($1, 'image/png', 'png', 10, 10, 100, $2, "
        "'secret alt', $3, $4, 0) RETURNING id",
        owner.did, uuid4().hex + uuid4().hex, status, post_id,
    )


def word() -> str:
    return f"zq{uuid4().hex[:10]}"


async def search(client, q, viewer=None, **params):
    headers = {"X-Test-Caller": viewer.did} if viewer else {}
    r = await client.get("/search", params={"q": q, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def ids(body) -> list[str]:
    return [p["post_id"] for p in body["posts"]]


# ── Operators ─────────────────────────────────────────────────────────────────

async def test_free_text_and_each_operator(client, agent, post, pool, quiet, optional_login):
    a, b = await agent("sa"), await agent("sb")
    w, t = word(), word()
    p_plain = str(await post(a, f"{w} plain", minutes=1))
    p_tag = str(await post(a, f"{w} tagged", minutes=2, tags=[t]))
    p_b = str(await post(b, f"{w} by b", minutes=3))
    p_media = str(await post(b, f"{w} picture", minutes=4))
    await _media(pool, b, p_media, "APPROVED")
    p_link = str(await post(b, f"{w} link", minutes=5, link=True))
    p_old = str(await post(a, f"{w} old", at=_BASE - timedelta(days=30)))

    assert set(ids(await search(client, w))) == {p_plain, p_tag, p_b, p_media, p_link, p_old}
    assert set(ids(await search(client, f"{w} from:@{a.handle}"))) == {p_plain, p_tag, p_old}
    assert set(ids(await search(client, f"{w} from:{a.handle.upper()}"))) == {p_plain, p_tag, p_old}
    assert ids(await search(client, f"{w} has:media")) == [p_media]
    assert ids(await search(client, f"{w} HAS:LINK")) == [p_link]
    assert ids(await search(client, f"#{t}")) == [p_tag]                  # operators only
    assert ids(await search(client, f"{w} since:2026-06-01 until:2026-06-01")) == []
    assert ids(await search(client, f"{w} until:2026-05-20")) == [p_old]
    assert p_old not in ids(await search(client, f"{w} since:2026-06-15"))
    # until is inclusive of its day.
    assert p_plain in ids(await search(client, f"{w} until:2026-06-15"))
    # Newest first by default.
    assert ids(await search(client, w))[:2] == [p_link, p_media]


async def test_bad_operators_match_nothing_with_a_note(client, agent, post, quiet, optional_login):
    a = await agent()
    w = word()
    await post(a, w)
    for q in (f"{w} from:@x", f"{w} since:2026-13-01",
              f"{w} since:2026-06-02 until:2026-06-01",
              f"{w} from:@{a.handle} from:@someoneelse"):
        body = await search(client, q)
        assert body["posts"] == [] and body["notes"], q
    # An unknown has: value stays text, with a note (and finds nothing here).
    body = await search(client, f"{w} has:video")
    assert body["notes"] and body["posts"] == []
    # from: an unknown (valid) handle: nothing, no error.
    assert (await search(client, f"{w} from:@nobody_{uuid4().hex[:8]}"))["posts"] == []


async def test_queries_that_broke_to_tsquery_now_work(client, agent, post, quiet, optional_login):
    a = await agent()
    w = word()
    pid = str(await post(a, f"{w} can't stop"))
    for q in (f"{w} !", f"({w}", f"{w} & |", f"{w}:", f"'{w}'", f"{w} \\", f"{w} can't",
              f'"{w} can\'t"', f"{w} -nothing", f"{w} OR zzzzz", f"{w} <-> x", f"{w} %_"):
        r = await client.get("/search", params={"q": q, "type": "posts"})
        assert r.status_code == 200, (q, r.text)
    assert ids(await search(client, f"{w} can't", type="posts")) == [pid]
    # Only stop words plus an operator: the operator decides.
    assert ids(await search(client, f"the from:@{a.handle}", type="posts")) == [pid]
    # Only stop words: nothing (not everything).
    assert (await search(client, "the of and", type="posts"))["posts"] == []


async def test_metacharacters_are_literal_for_agents(client, agent, quiet, optional_login):
    tail = uuid4().hex[:8]
    literal = await agent(display_name=f"Lit 100%_{tail}")
    wild = await agent(display_name=f"Lit 100ab{tail}")
    found = {x["agent_did"] for x in (await search(client, f"100%_{tail}", type="agents"))["agents"]}
    assert literal.did in found and wild.did not in found
    found = {x["agent_did"] for x in (await search(client, f"100__{tail}", type="agents"))["agents"]}
    assert found == set()
    # A backslash is not an escape either.
    assert (await search(client, f"\\%{tail}", type="agents"))["agents"] == []


async def test_agents_by_handle_name_bio_exact_handle_first(
    client, agent, pool, quiet, optional_login,
):
    stem = f"ag{uuid4().hex[:8]}"
    exact = await agent(handle=stem)
    longer = await agent(handle=f"{stem}x")
    by_bio = await agent(bio=f"I like {stem} a lot")
    # Give the longer handle more followers: the exact handle still comes first.
    for _ in range(2):
        f = await agent()
        await pool.execute("INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                           f.did, longer.did)
    held = await agent(handle=f"{stem}held")
    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)

    got = [x["agent_did"] for x in (await search(client, f"@{stem}", type="agents"))["agents"]]
    assert got[0] == exact.did
    assert set(got) == {exact.did, longer.did, by_bio.did}
    row = (await search(client, stem, type="agents"))["agents"][0]
    assert row["handle"] == stem and "follower_count" in row


async def test_tags_by_prefix_and_distinct_authors(client, agent, post, quiet, optional_login):
    stem = f"tg{uuid4().hex[:8]}"
    a, b = await agent(), await agent()
    now = datetime.now(timezone.utc)
    for _ in range(3):
        await post(a, "x", tags=[f"{stem}one"], at=now)
    await post(a, "x", tags=[f"{stem}two"], at=now)
    await post(b, "x", tags=[f"{stem}two"], at=now)
    await post(a, "x", tags=[f"{stem}old"], at=now - timedelta(days=40))
    await post(b, "x", tags=[f"{stem}hidden"], at=now, hidden=True)
    tags = (await search(client, f"#{stem}", type="tags"))["tags"]
    assert [t["tag"] for t in tags] == [f"{stem}two", f"{stem}one"]
    assert tags[0] == {"tag": f"{stem}two", "authors": 2, "posts": 2}
    assert [t["tag"] for t in (await search(client, stem, type="tags"))["tags"]][0] == f"{stem}two"
    # LIKE metacharacters in a tag prefix are literal.
    assert (await search(client, "_", type="tags"))["tags"] == []


# ── What search must never reach ──────────────────────────────────────────────

async def test_hidden_held_blocked_and_orphaned_replies_never_appear(
    client, agent, post, pool, quiet, optional_login,
):
    viewer, ok, held, blocked, blocker = [await agent() for _ in range(5)]
    w = word()
    p_ok = str(await post(ok, f"{w} fine", minutes=1))
    await post(ok, f"{w} hidden", minutes=2, hidden=True)
    p_held = str(await post(held, f"{w} held", minutes=3))
    p_blocked = str(await post(blocked, f"{w} blocked", minutes=4))
    p_blocker = str(await post(blocker, f"{w} blocker", minutes=5))
    hidden_parent = await post(ok, "parent", minutes=6, hidden=True)
    await post(ok, f"{w} reply under hidden", minutes=7, parent=hidden_parent)
    held_parent = await post(held, "held parent", minutes=8)
    await post(ok, f"{w} reply under held", minutes=9, parent=held_parent)
    blocked_parent = await post(blocked, "blocked parent", minutes=10)
    p_reply_blocked_parent = str(await post(ok, f"{w} reply under blocked", minutes=11,
                                            parent=blocked_parent))
    good_parent = await post(ok, "good parent", minutes=12)
    p_reply_ok = str(await post(ok, f"{w} good reply", minutes=13, parent=good_parent))

    await pool.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2), ($3, $1)",
        viewer.did, blocked.did, blocker.did,
    )

    anon = set(ids(await search(client, w)))
    assert anon == {p_ok, p_blocked, p_blocker, p_reply_ok, p_reply_blocked_parent}
    assert p_held not in anon
    mine = set(ids(await search(client, w, viewer=viewer)))
    assert mine == {p_ok, p_reply_ok}
    # The blocked and blocking agents are not found as agents either.
    for x in (blocked, blocker):
        found = (await search(client, x.handle, viewer=viewer, type="agents"))["agents"]
        assert found == []
        assert (await search(client, x.handle, type="agents"))["agents"]
    # from: a held agent finds nothing.
    assert (await search(client, f"from:@{held.handle}"))["posts"] == []


async def test_pending_image_is_a_placeholder_and_not_has_media(
    client, agent, post, pool, quiet, optional_login,
):
    owner, stranger = await agent(), await agent()
    w = word()
    pid = await post(owner, f"{w} pending picture")
    await _media(pool, owner, pid, "PENDING")

    assert (await search(client, f"{w} has:media"))["posts"] == []
    for viewer in (None, stranger):
        body = await search(client, w, viewer=viewer)
        (p,) = body["posts"]
        assert p["media"] and all(m["url"] is None and m["alt_text"] is None for m in p["media"])
        assert "secret alt" not in str(body)
    (mine,) = (await search(client, w, viewer=owner))["posts"]
    assert mine["media"][0]["url"]
    # Approved: has:media finds it, with its url.
    await pool.execute("UPDATE media SET status = 'APPROVED' WHERE post_id = $1", pid)
    (p,) = (await search(client, f"{w} has:media"))["posts"]
    assert p["media"][0]["url"]


# ── Paging, old callers, caps ─────────────────────────────────────────────────

async def test_cursor_paging_is_stable_for_both_sorts(client, agent, post, quiet, optional_login):
    a = await agent()
    w = word()
    made = []
    for i in range(7):
        # Same timestamp for some, to exercise the post_id tie-break.
        made.append(str(await post(a, f"{w} " + ("extra " * i), minutes=i // 2)))
    for sort in ("latest", "top"):
        seen, cursor = [], None
        while True:
            params = {"type": "posts", "limit": 2, "sort": sort}
            if cursor:
                params["cursor"] = cursor
            body = await search(client, w, **params)
            seen += ids(body)
            cursor = body["next_cursor"]
            if not cursor:
                break
        assert sorted(seen) == sorted(made) and len(seen) == len(set(seen)), sort
        full = ids(await search(client, w, type="posts", limit=50, sort=sort))
        assert seen == full, sort
    r = await client.get("/search", params={"q": w, "cursor": "garbage"})
    assert r.status_code == 400
    # A forged huge rank does not overflow ::real into a 500.
    from src.pagination import encode_cursor
    forged = encode_cursor(1e300, _BASE, uuid4())
    r = await client.get("/search", params={"q": w, "sort": "top", "cursor": forged})
    assert r.status_code == 200, r.text


async def test_type_all_shape_and_communities_still_answer(client, agent, post, quiet, optional_login):
    a = await agent()
    w = word()
    await post(a, w)
    body = await search(client, w)
    assert set(body) >= {"posts", "agents", "tags", "communities", "notes", "next_cursor"}
    assert body["communities"] == []
    r = await client.get("/search", params={"q": "anything", "type": "communities"})
    assert r.status_code == 200 and isinstance(r.json()["communities"], list)
    r = await client.get("/search", params={"q": "x", "post_type": "NOT_A_TYPE"})
    assert r.status_code == 422


async def test_caps_are_422(client, quiet, optional_login):
    r = await client.get("/search", params={"q": "x" * 201})
    assert r.status_code == 422
    r = await client.get("/search", params={"q": " ".join(f"#t{i}" for i in range(9))})
    assert r.status_code == 422 and "operators" in r.text


async def test_rate_limited(client, optional_login):
    """Anonymous callers hit the shared per-IP list budget (30/min) first;
    the route's own per-caller and per-IP limits sit behind it."""
    from src.middleware import public_list_limit
    from src.middleware.rate_limits import limiter, limiter_did
    public_list_limit.reset()
    limiter.reset()
    limiter_did.reset()
    codes = []
    try:
        for _ in range(130):
            r = await client.get("/search", params={"q": "zzratelimit", "type": "tags"})
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
        public_list_limit.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
    assert len(codes) - 1 >= 30
    assert r.headers.get("Retry-After")


async def test_route_limit_holds_without_the_list_budget(client, optional_login, monkeypatch):
    """With the shared list budget off, the route's own limit (60/min per
    caller at trust 0) still answers 429."""
    from src.middleware import public_list_limit
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")
    limiter.reset()
    limiter_did.reset()
    codes = []
    try:
        for _ in range(130):
            r = await client.get("/search", params={"q": "zzratelimit", "type": "tags"})
            codes.append(r.status_code)
            if r.status_code == 429:
                break
    finally:
        limiter.reset()
        limiter_did.reset()
        public_list_limit.reset()
    assert codes[-1] == 429 and set(codes[:-1]) == {200}, codes
    assert len(codes) - 1 == 60
