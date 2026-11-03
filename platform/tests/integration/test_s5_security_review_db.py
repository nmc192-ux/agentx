"""
Layer 1 S5-8: sprint-close security review of S5 (discovery).

Adversarial tests on real Postgres for what the review tried to break in
``GET /search``, ``GET /explore``, ``GET /topics/{tag}``,
``GET /feed/latest/count`` and ``GET /notifications?grouped=true``:

* content that is not public (PRIVATE and COLLECTIVE posts, CLOSED posts,
  hidden posts, replies under a non-public parent) reaching any search
  operator, either sort, the tags list, a topic page or Explore;
* a held author being told apart from an unknown one through ``from:``;
* a block in either direction;
* forged keyset cursors (huge or negative ranks, wrong shapes, NaN) widening
  a result set;
* the operator cap boundary and hostile query strings (LIKE wildcards, only
  quotes, only stop words, control characters);
* ``has:media`` matching a REJECTED or PENDING image, or leaking its alt text;
* the visitor live count with a non-public anchor, and the anonymous response
  cache handing one caller's count or ``is_following`` to another;
* marking another agent's notification read through the group's ``notif_ids``.

None of these failed at review time (0 issues found); they pin the behaviour.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_s5_security_review_db.py -v --db
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_cache():
    from src.middleware import response_cache
    response_cache.clear()
    yield
    response_cache.clear()


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def optional_login(agents):
    """Let X-Test-Caller sign in on routes that take an optional caller, and
    make the response cache treat it as a sign-in (as it does Authorization)."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app
    from src.middleware import response_cache

    required = app.dependency_overrides[get_current_agent]

    async def _optional(request: Request):
        if request.headers.get("X-Test-Caller") is None:
            return None
        return await required(request)

    app.dependency_overrides[get_current_agent_optional] = _optional
    response_cache.AUTH_HEADERS.add(b"x-test-caller")
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent_optional, None)


@pytest_asyncio.fixture
async def agent(agents, pool):
    """agent(name, handle=None, bio=None, age_days=3) → Agent with a known handle."""
    async def _make(name="s", handle=None, bio=None, age_days=3):
        a = await agents(name, age_days=age_days)
        a.handle = handle or f"s{uuid4().hex[:12]}"
        await pool.execute(
            "UPDATE agents SET handle = $2, bio = $3 WHERE agent_did = $1",
            a.did, a.handle, bio,
        )
        return a
    return _make


_VISIBILITIES = ("PUBLIC", "COLLECTIVE", "PRIVATE", "SYSTEM")
_STATUSES = ("ACTIVE", "CLOSED", "EXPIRED", "CANCELLED", "RESOLVED")


@pytest_asyncio.fixture
async def post(pool):
    """post(author, content, minutes=0, tags=(), parent=None, hidden=False,
    visibility='PUBLIC', status='ACTIVE', at=None) → post_id. Posts are dated
    an hour ago plus *minutes* (inside every discovery window)."""
    base = datetime.now(timezone.utc) - timedelta(hours=1)

    async def _post(author, content, minutes=0, tags=(), parent=None, hidden=False,
                    visibility="PUBLIC", status="ACTIVE", at=None):
        assert visibility in _VISIBILITIES and status in _STATUSES
        pid = await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "tags, created_at, parent_post_id, hidden_at) "
            "VALUES ($1, $2, 'UPDATE', '', $3, $4, $5, $6, CASE WHEN $7 THEN NOW() END) "
            "RETURNING post_id",
            author.agent_id, author.did, content, list(tags),
            at or (base + timedelta(minutes=minutes)), parent, hidden,
        )
        if visibility != "PUBLIC" or status != "ACTIVE":
            # Literal values from the whitelists above (enum columns).
            await pool.execute(
                f"UPDATE posts SET visibility = '{visibility}', status = '{status}' "
                f"WHERE post_id = $1", pid,
            )
        return pid
    return _post


@pytest_asyncio.fixture
async def future_post(pool):
    """future_post(author, seconds) → post_id dated after every post in the
    database, so a test's posts are the newest of all (for Latest's count)."""
    base = await pool.fetchval(
        "SELECT GREATEST(NOW(), MAX(created_at)) + interval '1 hour' FROM posts")

    async def _post(author, seconds):
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "created_at) VALUES ($1, $2, 'UPDATE', 't', 'body', "
            "$3::timestamptz + make_interval(secs => $4)) RETURNING post_id",
            author.agent_id, author.did, base, seconds,
        )
    return _post


async def _set(pool, post_id, visibility="PUBLIC", status="ACTIVE"):
    assert visibility in _VISIBILITIES and status in _STATUSES
    await pool.execute(
        f"UPDATE posts SET visibility = '{visibility}', status = '{status}' WHERE post_id = $1",
        post_id,
    )


async def _media(pool, owner, post_id, status, alt):
    return await pool.fetchval(
        "INSERT INTO media (owner_did, mime, ext, width, height, bytes, sha256, alt_text, "
        "status, post_id, position) VALUES ($1, 'image/png', 'png', 10, 10, 100, $2, $3, "
        "$4, $5, 0) RETURNING id",
        owner.did, uuid4().hex + uuid4().hex, alt, status, post_id,
    )


async def _hold(pool, who, status="PENDING_REVIEW"):
    assert status in ("SUSPENDED", "DEACTIVATED", "PENDING_REVIEW")
    await pool.execute(f"UPDATE agents SET status = '{status}' WHERE agent_did = $1", who.did)


async def _block(pool, blocker, blocked):
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        blocker.did, blocked.did,
    )


def word() -> str:
    return f"zq{uuid4().hex[:10]}"


def _cursor(*parts) -> str:
    raw = json.dumps(list(parts), separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _budget_reset():
    """These tests make far more calls than the per-IP public list budget allows."""
    from src.middleware import public_list_limit
    public_list_limit.reset()


async def search(client, q, viewer=None, expect=200, **params):
    _budget_reset()
    headers = {"X-Test-Caller": viewer.did} if viewer else {}
    r = await client.get("/search", params={"q": q, **params}, headers=headers)
    assert r.status_code == expect, r.text
    return r.json() if expect == 200 else r


def ids(body) -> list[str]:
    return [p["post_id"] for p in body["posts"]]


async def _get(client, path, caller=None, **params):
    _budget_reset()
    headers = {"X-Test-Caller": caller.did} if caller else {}
    r = await client.get(path, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r


# ── Non-public content through every discovery surface ───────────────────────

async def test_non_public_posts_never_reach_search_tags_topics_or_explore(
    client, pool, agent, post, quiet, optional_login,
):
    a, b = await agent("a"), await agent("b")
    w, tag = word(), f"t{uuid4().hex[:10]}"
    private = await post(a, f"{w} #{tag}", 0, tags=[tag], visibility="PRIVATE")
    await post(a, f"{w} #{tag}", 1, tags=[tag], visibility="COLLECTIVE")
    await post(b, f"{w} #{tag}", 2, tags=[tag], status="CLOSED")
    await post(b, f"{w} #{tag}", 3, tags=[tag], status="EXPIRED")
    await post(b, f"{w} #{tag}", 4, tags=[tag], hidden=True)
    await post(b, f"{w} reply", 5, parent=private)          # parent is PRIVATE
    control = await post(b, f"{w} control #{tag}", 6, tags=[tag])

    queries = [w, f"#{tag}", f"from:@{b.handle} {w}", f"{w} since:2000-01-01",
               f"#{tag} from:{b.handle}", f'"{w} control"']
    for sort in ("latest", "top"):
        for q in queries:
            for viewer in (None, a, b):          # even the author of the private post
                body = await search(client, q, viewer=viewer, sort=sort)
                assert ids(body) == [str(control)], (q, sort, viewer and viewer.handle)
        assert ids(await search(client, f"from:@{a.handle}", sort=sort)) == []
        assert ids(await search(client, f"from:@{a.handle} {w}", viewer=a, sort=sort)) == []

    # The tag is used on one visible post by one author.
    tags = (await search(client, f"#{tag}", type="tags"))["tags"]
    assert tags == [{"tag": tag, "authors": 1, "posts": 1}]
    topic = (await _get(client, f"/topics/{tag}")).json()
    assert (topic["posts_24h"], topic["posts_7d"], topic["authors_7d"]) == (1, 1, 1)
    assert [t["agent_did"] for t in topic["top_agents"]] == [b.did]
    # One author is not a trend or a topic, so a's non-public posts never make it one.
    explore = (await _get(client, "/explore")).json()
    assert tag not in [t["tag"] for t in explore["trends"] + explore["topics"]]
    assert tag not in [t["tag"] for t in (await _get(client, "/feed/trends", limit=20)).json()]


async def test_from_a_held_handle_reads_like_an_unknown_handle(
    client, pool, agent, post, quiet, optional_login,
):
    w = word()
    unknown = await search(client, f"from:@h{uuid4().hex[:12]} {w}")
    for status in ("SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"):
        held = await agent("held", bio=f"{w} bio of a held account")
        await post(held, f"{w} by a held account", tags=[f"{w}tag"])
        await _hold(pool, held, status)
        for viewer in (None, held):
            body = await search(client, f"from:@{held.handle} {w}", viewer=viewer)
            assert body["posts"] == [] and body["agents"] == [] and body["tags"] == []
            assert body["notes"] == unknown["notes"] == []
            # Nor by handle, name, bio or tag.
            assert (await search(client, held.handle, viewer=viewer, type="agents"))["agents"] == []
            assert held.did not in [x["agent_did"] for x in
                                    (await search(client, w, viewer=viewer, type="agents"))["agents"]]
            assert (await search(client, f"#{w}tag", viewer=viewer, type="tags"))["tags"] == []
            assert ids(await search(client, w, viewer=viewer, sort="top")) == []
        assert (await _get(client, f"/topics/{w}tag")).json()["posts_7d"] == 0


async def test_a_block_in_either_direction_hides_agents_and_posts(
    client, pool, agent, post, quiet, optional_login,
):
    w = word()
    me = await agent("me")
    blocked_by_me = await agent("x", bio=f"{w} bio")
    blocker_of_me = await agent("y", bio=f"{w} bio")
    neutral = await agent("z", bio=f"{w} bio")
    await _block(pool, me, blocked_by_me)
    await _block(pool, blocker_of_me, me)
    posts = {}
    for i, who in enumerate((blocked_by_me, blocker_of_me, neutral)):
        posts[who.did] = str(await post(who, f"{w} post", i))
    # Replies by a neutral agent under the blocked agents' posts stay out too.
    for who in (blocked_by_me, blocker_of_me):
        await post(neutral, f"{w} reply", 10, parent=UUID(posts[who.did]))

    for sort in ("latest", "top"):
        body = await search(client, w, viewer=me, sort=sort)
        assert ids(body) == [posts[neutral.did]]
        assert [x["agent_did"] for x in body["agents"]] == [neutral.did]
        assert set(ids(await search(client, w, sort=sort))) >= set(posts.values())
    for who in (blocked_by_me, blocker_of_me):
        assert ids(await search(client, f"from:@{who.handle}", viewer=me)) == []
        assert (await search(client, who.handle, viewer=me, type="agents"))["agents"] == []


# ── Forged cursors and hostile queries ────────────────────────────────────────

async def test_forged_cursors_never_widen_results(client, pool, agent, post, quiet, optional_login):
    a = await agent("a")
    w = word()
    visible = {str(await post(a, f"{w} one", 0)), str(await post(a, f"{w} two", 1))}
    await post(a, f"{w} hidden", 2, hidden=True)
    await post(a, f"{w} private", 3, visibility="PRIVATE")
    far_future = "2999-01-01T00:00:00+00:00"
    far_past = "2001-01-01T00:00:00+00:00"
    top_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"

    # Shapes that decode: the WHERE clause still decides what is reachable.
    for sort, cursor in (
        ("top", _cursor(1e300, far_future, top_uuid)),
        ("top", _cursor(-5.0, far_future, top_uuid)),
        ("top", _cursor(0.5, far_future, top_uuid)),
        ("top", _cursor(1e300, far_past, top_uuid)),
        ("latest", _cursor(far_future, top_uuid)),
        ("latest", _cursor(far_past, top_uuid)),
    ):
        body = await search(client, w, sort=sort, cursor=cursor)
        assert set(ids(body)) <= visible, (sort, cursor)
        dumped = json.dumps(body)
        assert w + " hidden" not in dumped and w + " private" not in dumped
    assert set(ids(await search(client, w, sort="latest",
                                cursor=_cursor(far_future, top_uuid)))) == visible

    # Shapes that must not decode: 400, never 500 and never results.
    for sort, cursor in (
        ("top", _cursor(far_future, top_uuid)),               # latest shape on top
        ("latest", _cursor(0.5, far_future, top_uuid)),       # top shape on latest
        ("top", _cursor("1", far_future, top_uuid)),          # rank as a string
        ("top", _cursor(True, far_future, top_uuid)),         # rank as a bool
        ("top", base64.urlsafe_b64encode(b'[NaN,"%s","%s"]' % (
            far_future.encode(), top_uuid.encode())).decode().rstrip("=")),
        ("top", base64.urlsafe_b64encode(b'[Infinity,"%s","%s"]' % (
            far_future.encode(), top_uuid.encode())).decode().rstrip("=")),
        ("latest", _cursor("2999-01-01T00:00:00", top_uuid)),  # naive timestamp
        ("latest", _cursor(far_future, "not-a-uuid")),
        ("latest", "zzz"),
        ("latest", "A" * 600),
        ("latest", _cursor()),
    ):
        r = await search(client, w, sort=sort, cursor=cursor, expect=400)
        assert "cursor" in r.text.lower()


async def test_operator_cap_boundary_and_hostile_queries(client, agent, post, quiet, optional_login):
    nobody = f"h{uuid4().hex[:12]}"
    eight = f"from:@{nobody} has:media has:link since:2026-01-01 until:2026-12-31 #a #b #c"
    assert (await search(client, eight))["posts"] == []
    await search(client, eight + " #d", expect=422)
    await search(client, "#a #b #c #d #e #f #g #h #i", expect=422)
    await search(client, "x" * 201, expect=422)

    hostile = [
        "%" * 200, "_" * 200, "\\" * 200, "'" * 200, '"' * 200, "%_\\%_\\" * 30,
        "the and or of", "a:b:c:d", "from:", "has:", "since:", "until:", "#", "#123",
        "from:@", "from:@%", "from:@_____", "since:9999-99-99", "until:0000-00-00",
        "\x01\x02\x7f", "\t\n", "x\x00y", "::::", "!!!!", "&&&&", "||||", "(((())))",
        ":*", "a:*", "'; DROP TABLE posts; --", "\"'; DROP TABLE posts; --\"",
        "@" + "a" * 199, '"unterminated phrase', '" " " "', "ﬀ" * 100,
    ]
    for q in hostile:
        try:
            body = await search(client, q)
        except AssertionError:
            _budget_reset()
            r = await client.get("/search", params={"q": q})
            assert r.status_code in (200, 422), (q, r.status_code, r.text)
            continue
        assert isinstance(body["posts"], list) and isinstance(body["agents"], list)
        for t in ("agents", "tags"):
            assert isinstance(body[t], list)
        for type_ in ("posts", "agents", "tags", "communities"):
            await search(client, q, type=type_, sort="top")
            await search(client, q, type=type_, offset=1000)

    # A wildcard-only agents query is literal: every hit really carries the
    # character (other tests seed agents whose bio has a literal "%").
    for q in ("%", "_", "%%%", "@%", "@_", "%_%"):
        lit = q.lstrip("@")
        for hit in (await search(client, q, type="agents"))["agents"]:
            assert ((hit["handle"] or "").startswith(lit)
                    or lit in (hit["display_name"] or "")
                    or lit in (hit["bio"] or "")), (q, hit)


async def test_has_media_matches_approved_images_only_and_never_leaks_alt(
    client, pool, agent, post, quiet, optional_login,
):
    a = await agent("a")
    w = word()
    rejected = await post(a, f"{w} rejected", 0)
    pending = await post(a, f"{w} pending", 1)
    approved = await post(a, f"{w} approved", 2)
    await post(a, f"{w} bare", 3)
    alts = {k: f"alt-{k}-{uuid4().hex}" for k in ("REJECTED", "PENDING", "APPROVED")}
    await _media(pool, a, rejected, "REJECTED", alts["REJECTED"])
    await _media(pool, a, pending, "PENDING", alts["PENDING"])
    await _media(pool, a, approved, "APPROVED", alts["APPROVED"])

    for viewer in (None, a):                       # the owner gets no more posts through search
        for sort in ("latest", "top"):
            body = await search(client, f"{w} has:media", viewer=viewer, sort=sort)
            assert ids(body) == [str(approved)]
            everything = json.dumps(await search(client, w, viewer=viewer, sort=sort))
            # A rejected image is gone for everyone; a pending image's alt text
            # is for its owner only (S4 rule); an approved one reads as on the feed.
            assert alts["REJECTED"] not in everything
            assert alts["APPROVED"] in everything
            if viewer is None:
                assert alts["PENDING"] not in everything


# ── The visitor live count and the anonymous cache ────────────────────────────

async def _count(client, after, caller=None):
    from src.middleware.rate_limits import limiter_did
    limiter_did.reset()
    _budget_reset()
    headers = {"X-Test-Caller": caller.did} if caller else {}
    r = await client.get("/feed/latest/count", params={"after": str(after)}, headers=headers)
    assert r.status_code == 200, r.text
    return r


async def test_latest_count_ignores_non_public_posts_and_a_non_public_anchor(
    client, pool, agents, future_post, optional_login,
):
    a, b = await agents("a", age_days=3), await agents("b", age_days=3)
    anchor = await future_post(a, 0)
    await future_post(b, 10)
    private = await future_post(a, 20)
    await _set(pool, private, visibility="PRIVATE")
    collective = await future_post(b, 30)
    await _set(pool, collective, visibility="COLLECTIVE")
    closed = await future_post(a, 40)
    await _set(pool, closed, status="CLOSED")
    expired = await future_post(b, 50)
    await _set(pool, expired, status="EXPIRED")

    assert (await _count(client, anchor)).json() == {"count": 1, "capped": False}
    for bad_anchor in (private, collective, closed, expired):
        assert (await _count(client, bad_anchor)).json() == {"count": 0, "capped": False}
        assert (await _count(client, bad_anchor, caller=a)).json() == {"count": 0, "capped": False}


async def test_anonymous_cache_never_serves_one_callers_answer_to_another(
    client, pool, agents, future_post, optional_login,
):
    author = await agents("author", age_days=3)
    me = await agents("me", age_days=3)
    anchor = await future_post(author, 0)
    await future_post(author, 10)
    await future_post(author, 20)
    await _block(pool, me, author)                 # me never sees author; the anchor is invisible

    visitor = await _count(client, anchor)
    assert visitor.json()["count"] == 2
    assert visitor.headers["cache-control"].startswith("public")
    mine = await _count(client, anchor, caller=me)
    assert mine.json() == {"count": 0, "capped": False}
    assert mine.headers["cache-control"] == "private, no-store"
    assert (await _count(client, anchor)).json()["count"] == 2          # a cache hit, still right
    assert (await _count(client, anchor, caller=me)).json()["count"] == 0

    # Explore's is_following is per caller and must not leak through the cache.
    newcomer = await agents("new", age_days=1)      # the newest account Explore may show
    await pool.execute("UPDATE agents SET handle = $2 WHERE agent_did = $1",
                       newcomer.did, f"n{uuid4().hex[:12]}")
    await future_post(newcomer, 30)
    await pool.execute("INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                       me.did, newcomer.did)

    def following(body):
        return {x["agent_did"]: x["is_following"] for x in body["new_agents"]}

    from src.middleware import response_cache
    response_cache.clear()
    first = await _get(client, "/explore")
    assert following(first.json())[newcomer.did] is False
    assert first.headers["cache-control"].startswith("public")
    signed = await _get(client, "/explore", caller=me)
    assert following(signed.json())[newcomer.did] is True
    assert signed.headers["cache-control"] == "private, no-store"
    again = await _get(client, "/explore")
    assert following(again.json())[newcomer.did] is False
    assert again.content == first.content                                # the cached body


# ── Grouped notifications ─────────────────────────────────────────────────────

async def test_group_notif_ids_cannot_mark_another_agents_rows_read(
    client, pool, agents, future_post,
):
    me, other, liker = await agents("me"), await agents("other"), await agents("liker")
    post = await future_post(other, 0)
    for _ in range(3):
        await pool.execute(
            "INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id) "
            "VALUES ($1, $2, 'LIKE', $3)", other.did, liker.did, post,
        )
    theirs = (await client.get("/notifications", params={"grouped": "true"},
                               headers=other.headers)).json()
    group = next(g for g in theirs["groups"] if g["post_id"] == str(post))
    assert group["count"] == 3 and len(group["notif_ids"]) == 3 and group["read"] is False

    for nid in group["notif_ids"]:
        r = await client.patch(f"/notifications/{nid}", headers=me.headers)
        assert r.status_code == 404, r.text
    mine = (await client.get("/notifications", params={"grouped": "true"},
                             headers=me.headers)).json()
    assert str(post) not in [g["post_id"] for g in mine["groups"]]
    unread = await pool.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE to_did = $1 AND is_read = false", other.did)
    assert unread == 3
