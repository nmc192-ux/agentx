"""
Integration tests: keyset ("cursor") paging against REAL local Postgres.
EG-2 (Neon egress).

What is proven, for followers / following / notifications / both activity
streams:
  • walking every page by cursor returns each row exactly once, in the same
    order as one big page (no overlap, no gaps), including rows that share a
    created_at (the id tie-breaker decides)
  • a row added while a client is paging does not shift later pages (OFFSET
    paging would repeat a row here)
  • the cursor only narrows the query: PRIVATE activity stays owner-only on
    page 2 as on page 1
  • a malformed cursor is a 400, not a 500

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

TIE = "2026-01-01T00:00:00+00"


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


async def _walk_body(client, url, key, limit, headers=None, params=None):
    """Follow next_cursor in the body until it runs out; return every page."""
    pages, cursor = [], None
    for _ in range(50):
        q = {**(params or {}), "limit": limit}
        if cursor:
            q["cursor"] = cursor
        r = await client.get(url, params=q, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        pages.append(body[key])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("cursor never ran out")


async def _walk_header(client, url, limit, headers=None, max_pages=50, params=None):
    pages, cursor = [], None
    for _ in range(max_pages):
        q = {**(params or {}), "limit": limit}
        if cursor:
            q["cursor"] = cursor
        r = await client.get(url, params=q, headers=headers)
        assert r.status_code == 200, r.text
        pages.append(r.json())
        cursor = r.headers.get("X-Next-Cursor")
        if cursor is None:
            break
    return pages


def _flat(pages, key):
    return [item[key] for page in pages for item in page]


# ── Followers / following ─────────────────────────────────────────────────────

async def _follow(pool, follower, following, at=None):
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did, created_at) "
        "VALUES ($1, $2, COALESCE($3::text::timestamptz, now()))",
        follower.did, following.did, at,
    )


async def test_followers_cursor_walk_has_no_overlap_or_gap(client, pool, agents):
    star = await agents("star")
    fans = [await agents(f"fan{i}") for i in range(7)]
    for i, fan in enumerate(fans):
        # Three share one timestamp; the rest are spread out.
        at = TIE if i < 3 else f"2026-01-0{i}T00:00:00+00"
        await _follow(pool, fan, star, at)

    url = f"/agents/{star.did}/followers"
    full = (await client.get(url, params={"limit": 50})).json()["agents"]
    assert len(full) == 7

    pages = await _walk_body(client, url, "agents", limit=3)
    assert [len(p) for p in pages] == [3, 3, 1]
    walked = _flat(pages, "agent_did")
    assert walked == [a["agent_did"] for a in full]
    assert len(set(walked)) == 7


async def test_new_follower_mid_walk_does_not_shift_pages(client, pool, agents):
    star = await agents("star")
    fans = [await agents(f"fan{i}") for i in range(4)]
    for i, fan in enumerate(fans):
        await _follow(pool, fan, star, f"2026-02-0{i + 1}T00:00:00+00")
    url = f"/agents/{star.did}/followers"

    first = (await client.get(url, params={"limit": 2})).json()
    late = await agents("late")
    await _follow(pool, late, star)          # newest: sorts before page 1

    second = (await client.get(
        url, params={"limit": 2, "cursor": first["next_cursor"]},
    )).json()
    seen = [a["agent_did"] for a in first["agents"] + second["agents"]]
    assert seen == [f.did for f in reversed(fans)]   # no repeat, nothing skipped

    # The old page= paging is still there (and would repeat a row here).
    old = (await client.get(url, params={"limit": 2, "page": 2})).json()
    assert old["page"] == 2 and len(old["agents"]) == 2


async def test_following_cursor_walk(client, pool, agents):
    me = await agents("me")
    stars = [await agents(f"s{i}") for i in range(5)]
    for s in stars:
        await _follow(pool, me, s, TIE)          # all tied: id order decides
    url = f"/agents/{me.did}/following"
    full = _flat([(await client.get(url, params={"limit": 50})).json()["agents"]], "agent_did")
    walked = _flat(await _walk_body(client, url, "agents", limit=2), "agent_did")
    assert walked == full and len(set(walked)) == 5


# ── Notifications ─────────────────────────────────────────────────────────────

async def test_notifications_cursor_walk_unread_first(client, pool, agents):
    me, other = await agents("me"), await agents("other")
    for i in range(7):
        await pool.execute(
            "INSERT INTO notifications (to_did, from_did, notif_type, is_read, created_at) "
            "VALUES ($1, $2, 'FOLLOW', $3, $4::text::timestamptz)",
            me.did, other.did, i % 2 == 0, TIE if i < 4 else f"2026-03-0{i}T00:00:00+00",
        )

    full = (await client.get("/notifications", params={"limit": 50},
                             headers=me.headers)).json()["notifications"]
    assert len(full) == 7
    pages = await _walk_body(client, "/notifications", "notifications", limit=2,
                             headers=me.headers)
    walked = _flat(pages, "notif_id")
    assert walked == [n["notif_id"] for n in full]
    assert len(set(walked)) == 7
    reads = [n["is_read"] for page in pages for n in page]
    assert reads == sorted(reads)                 # all unread before any read

    unread = await _walk_body(client, "/notifications", "notifications", limit=2,
                              headers=me.headers, params={"unread_only": "true"})
    assert len(_flat(unread, "notif_id")) == 3


async def test_notification_cursor_cannot_reach_someone_elses(client, pool, agents):
    me, victim = await agents("me"), await agents("victim")
    await pool.execute(
        "INSERT INTO notifications (to_did, notif_type) VALUES ($1, 'FOLLOW')", victim.did,
    )
    await pool.execute(
        "INSERT INTO notifications (to_did, notif_type) VALUES ($1, 'FOLLOW')", me.did,
    )
    # Take a cursor from the victim's own listing and replay it as `me`.
    victim_page = (await client.get("/notifications", params={"limit": 1},
                                    headers=victim.headers)).json()
    from src.pagination import encode_cursor
    n = victim_page["notifications"][0]
    cur = encode_cursor(False, "2099-01-01T00:00:00+00:00", n["notif_id"])
    r = await client.get("/notifications", params={"cursor": cur, "limit": 50},
                         headers=me.headers)
    assert r.status_code == 200
    ids = [x["notif_id"] for x in r.json()["notifications"]]
    assert n["notif_id"] not in ids and len(ids) == 1


# ── Activity streams ──────────────────────────────────────────────────────────

async def test_agent_activity_cursor_walk_keeps_visibility(client, pool, agents, optional_login):
    owner, other = await agents("owner"), await agents("other")
    for i in range(6):
        await pool.execute(
            "INSERT INTO activity_stream (agent_did, stream_type, content, visibility, created_at) "
            "VALUES ($1, 'test', $2, $3, $4::text::timestamptz)",
            owner.did, f"e{i}", "PUBLIC" if i % 2 else "PRIVATE", TIE,
        )
    url = f"/agents/{owner.did}/activity-stream"

    mine = _flat(await _walk_header(client, url, 2, headers=owner.headers), "stream_id")
    assert len(mine) == 6 and len(set(mine)) == 6
    full = _flat([(await client.get(url, params={"limit": 50}, headers=owner.headers)).json()],
                 "stream_id")
    assert mine == full

    for headers in (None, other.headers):
        pages = await _walk_header(client, url, 2, headers=headers)
        assert [len(p) for p in pages] == [2, 1]
        assert {e["visibility"] for p in pages for e in p} == {"PUBLIC"}


async def test_global_activity_cursor_walk(client, pool, agents):
    owner = await agents("owner")
    # Far-future rows sort first in the global stream, whatever else is there.
    for i in range(5):
        await pool.execute(
            "INSERT INTO activity_stream (agent_did, stream_type, content, visibility, created_at) "
            "VALUES ($1, 'test', $2, 'PUBLIC', '2099-06-01T00:00:00+00')",
            owner.did, f"g{i}",
        )
    pages = await _walk_header(client, "/activity", 2, max_pages=3)
    walked = [e for p in pages for e in p][:5]
    assert {e["agent_did"] for e in walked} == {owner.did}
    assert len({e["stream_id"] for e in walked}) == 5


# ── Ranked feeds (EG-2b) ──────────────────────────────────────────────────────
# The database is shared across the run, so these tests make their own posts
# sort first (huge like counts / far-future timestamps) and check those.

HOT = 10_000_000   # far above any like count other tests create


async def _post(pool, author, at=TIE, likes=0, title="p"):
    return await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
        "created_at, like_count) VALUES ($1, $2, 'UPDATE', $3, $4, $5::text::timestamptz, $6) "
        "RETURNING post_id",
        author.agent_id, author.did, title, f"{title} body", at, likes,
    )


async def test_global_feed_cursor_walk_by_score(client, pool, agents):
    author = await agents("ranked")
    ids = []
    for i in range(7):
        # Three share score and timestamp (post_id decides); the rest differ.
        likes = HOT if i < 3 else HOT + i
        ids.append(str(await _post(pool, author, likes=likes, title=f"r{i}")))

    full = _flat([(await client.get("/feed/global", params={"limit": 7})).json()], "post_id")
    assert sorted(full) == sorted(ids)            # ours are the top 7

    pages = await _walk_header(client, "/feed/global", 3, max_pages=3)
    assert [len(p) for p in pages][:2] == [3, 3]   # page 3 may hold other tests' posts
    walked = _flat(pages, "post_id")[:7]
    assert walked == full and len(set(walked)) == 7
    # The scores really are non-increasing across page borders.
    likes = [p["like_count"] for page in pages for p in page][:7]
    assert likes == sorted(likes, reverse=True)


async def test_global_feed_cursor_keeps_block_filter(client, pool, agents, optional_login):
    me, good, blocked = await agents("me"), await agents("good"), await agents("blocked")
    for i in range(4):
        await _post(pool, good, likes=HOT * 2 + i, title=f"g{i}")
        await _post(pool, blocked, likes=HOT * 2 + i, title=f"b{i}")
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        me.did, blocked.did,
    )
    pages = await _walk_header(client, "/feed/global", 2, headers=me.headers, max_pages=2)
    authors = [p["author_did"] for page in pages for p in page]
    assert authors == [good.did] * 4              # blocked author absent on page 2 too

    anon = await _walk_header(client, "/feed/global", 2, max_pages=2)
    assert {p["author_did"] for page in anon for p in page} == {good.did, blocked.did}


async def test_personal_feed_walks_whole_feed_once(client, pool, agents):
    me, star = await agents("reader"), await agents("star")
    await _follow(pool, me, star)
    mine = {str(await _post(pool, star, at=f"2026-0{m}-01T00:00:00+00")) for m in range(1, 6)}

    eligible = await pool.fetchval(
        "SELECT count(*) FROM posts WHERE visibility IN ('PUBLIC', 'SYSTEM') "
        "AND status = 'ACTIVE' AND hidden_at IS NULL",
    )
    pages = await _walk_header(client, "/feed", 50, max_pages=500,
                               params={"agent_id": me.did})
    walked = _flat(pages, "post_id")
    assert len(walked) == len(set(walked)) == eligible   # every post once, none twice
    assert mine <= set(walked)

    # Small pages give the same order as one big page.
    big = _flat([(await client.get("/feed", params={"agent_id": me.did, "limit": 12})).json()],
                "post_id")
    small = _flat(await _walk_header(client, "/feed", 3, max_pages=4,
                                     params={"agent_id": me.did}), "post_id")
    assert small[:len(big)] == big


async def test_personal_feed_new_post_mid_walk_does_not_shift_pages(client, pool, agents):
    me, star = await agents("reader"), await agents("star")
    await _follow(pool, me, star)
    first = await client.get("/feed", params={"agent_id": me.did, "limit": 4})
    cursor = first.headers["X-Next-Cursor"]
    page1 = _flat([first.json()], "post_id")

    # A brand-new post from a followed author ranks at the very top.
    fresh = str(await _post(pool, star, at="now", title="fresh"))
    second = await client.get("/feed", params={"agent_id": me.did, "limit": 4, "cursor": cursor})
    page2 = _flat([second.json()], "post_id")
    assert fresh not in page2
    assert not set(page1) & set(page2)
    # ...and with no cursor it is first.
    top = (await client.get("/feed", params={"agent_id": me.did, "limit": 1})).json()
    assert top[0]["post_id"] == fresh


async def test_activity_feed_cursor_walk_mixes_both_kinds(client, pool, agents):
    owner = await agents("owner")
    for i in range(3):
        await pool.execute(
            "INSERT INTO activity_stream (agent_did, stream_type, content, visibility, created_at) "
            "VALUES ($1, 'test', $2, 'PUBLIC', '2099-07-01T00:00:00+00')",
            owner.did, f"a{i}",
        )
        await _post(pool, owner, at="2099-07-01T00:00:00+00", title=f"m{i}")
    pages = await _walk_header(client, "/feed/activity", 4, max_pages=2)
    walked = [e for p in pages for e in p][:6]
    assert {e["agent_did"] for e in walked} == {owner.did}
    assert len({e["id"] for e in walked}) == 6
    assert sorted(e["item_type"] for e in walked) == ["activity"] * 3 + ["post"] * 3


# ── Bad cursors ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cursor", ["%%%", "e30", "WyJ4Il0", "x" * 600])
async def test_bad_cursor_is_400(client, pool, agents, optional_login, cursor):
    me = await agents("me")
    for url, headers in (
        (f"/agents/{me.did}/followers", None),
        (f"/agents/{me.did}/following", None),
        ("/notifications", me.headers),
        (f"/agents/{me.did}/activity-stream", None),
        ("/activity", None),
        ("/feed/global", None),
        ("/feed/activity", None),
        ("/feed", me.headers),
    ):
        r = await client.get(url, params={"cursor": cursor}, headers=headers)
        assert r.status_code == 400, (url, r.status_code, r.text)
