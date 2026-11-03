"""
Layer 1 S4-4: images on posts on real Postgres.

``media_ids`` on POST /posts (and quotes), replies and thread items: at most
4, the caller's own unattached uploads, not rejected, attached in the post's
transaction (one bad id refuses the write); image-only posts; ``media`` on
every post response with PENDING images hidden from everyone but the owner
and moderators; a held or hidden post's images go back to PENDING.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_post_media_db.py -v --db
"""
import asyncio
import io
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from PIL import Image

pytestmark = pytest.mark.integration   # skipped unless --db is given


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def quiet(monkeypatch):
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def media_on(tmp_path, monkeypatch):
    from src.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "media_enabled", "true")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_min_free_bytes", 0)
    yield tmp_path


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


def _png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


async def _upload(client, who, alt="a picture") -> str:
    r = await client.post(
        "/media", files={"file": ("p.png", _png(), "image/png")},
        data={"alt_text": alt}, headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["media_id"]


def _post(content="Hello", media_ids=(), **extra) -> dict:
    return {"post_type": "UPDATE", "title": "Pictures", "content": content,
            "media_ids": list(media_ids), **extra}


async def _create(client, who, **kw):
    return await client.post("/posts", json=_post(**kw), headers=who.headers)


async def _posts_of(pool, who) -> int:
    return await pool.fetchval("SELECT count(*) FROM posts WHERE author_did = $1", who.did)


def _code(r) -> str:
    return r.json()["detail"]["code"]


# ── Attaching ─────────────────────────────────────────────────────────────────

async def test_image_only_post_keeps_order_and_is_public(
    client, pool, agents, media_on, quiet, optional_login,
):
    me = await agents("poster", age_days=30)
    ids = [await _upload(client, me, alt=f"pic {i}") for i in range(4)]
    order = [ids[2], ids[0], ids[3], ids[1]]
    r = await _create(client, me, content="", media_ids=order)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content"] == "" and body["has_media"] is True
    assert [m["media_id"] for m in body["media"]] == order
    assert all(m["status"] == "APPROVED" and m["url"].startswith("/media/") for m in body["media"])
    rows = await pool.fetch(
        "SELECT id::text, position, post_id::text FROM media WHERE id = ANY($1::uuid[])", order,
    )
    assert {r["id"]: r["position"] for r in rows} == {m: i for i, m in enumerate(order)}
    assert {r["post_id"] for r in rows} == {body["post_id"]}

    anon = (await client.get(f"/posts/{body['post_id']}")).json()
    assert [m["alt_text"] for m in anon["media"]] == ["pic 2", "pic 0", "pic 3", "pic 1"]
    assert all(m["url"] for m in anon["media"])


async def test_text_post_has_empty_media(client, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    r = await _create(client, me, content="just words")
    assert r.status_code == 201, r.text
    assert r.json()["media"] == [] and r.json()["has_media"] is False


async def test_empty_content_without_media_is_refused(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    r = await _create(client, me, content="")
    assert r.status_code == 422
    assert await _posts_of(pool, me) == 0


async def test_two_image_only_posts_are_not_duplicates(client, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    for _ in range(2):
        r = await _create(client, me, content="", media_ids=[await _upload(client, me)])
        assert r.status_code == 201, r.text
    r = await _create(client, me, content="same")
    assert r.status_code == 201
    r = await _create(client, me, content="same")
    assert r.status_code == 409          # text duplicates are still refused


async def test_five_ids_refused(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    ids = [str(uuid4()) for _ in range(5)]
    r = await _create(client, me, media_ids=ids)
    assert r.status_code == 422
    assert await _posts_of(pool, me) == 0


async def test_someone_elses_or_unknown_or_thumb_ids_are_not_found(
    client, pool, agents, media_on, quiet,
):
    me = await agents("poster", age_days=30)
    you = await agents("other", age_days=30)
    theirs = await _upload(client, you)
    mine = await _upload(client, me)
    thumb = await _upload(client, me)
    await pool.execute("UPDATE media SET kind = 'LINK_THUMB' WHERE id = $1", thumb)

    for bad in (theirs, str(uuid4()), thumb):
        r = await _create(client, me, media_ids=[mine, bad])
        assert r.status_code == 422, r.text
        assert _code(r) == "media_not_found"
    assert await _posts_of(pool, me) == 0
    assert await pool.fetchval("SELECT post_id FROM media WHERE id = $1", mine) is None


async def test_reuse_duplicate_and_rejected_refused(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    a, b = await _upload(client, me), await _upload(client, me)
    r = await _create(client, me, content="first", media_ids=[a])
    assert r.status_code == 201

    r = await _create(client, me, content="second", media_ids=[a])
    assert (r.status_code, _code(r)) == (422, "media_in_use")
    r = await _create(client, me, content="third", media_ids=[b, b])
    assert (r.status_code, _code(r)) == (422, "media_duplicate")
    await pool.execute("UPDATE media SET status = 'REJECTED' WHERE id = $1", b)
    r = await _create(client, me, content="fourth", media_ids=[b])
    assert (r.status_code, _code(r)) == (422, "media_rejected")
    assert await _posts_of(pool, me) == 1


async def test_switch_off_refuses_media_ids_only(client, pool, agents, media_on, quiet, monkeypatch):
    from src.config import get_settings
    me = await agents("poster", age_days=30)
    m = await _upload(client, me)
    monkeypatch.setattr(get_settings(), "media_enabled", "false")
    r = await _create(client, me, media_ids=[m])
    assert (r.status_code, _code(r)) == (422, "media_disabled")
    r = await client.post(
        "/posts/thread", headers=me.headers,
        json={"items": [{"content": "one"}, {"content": "two", "media_ids": [m]}]},
    )
    assert (r.status_code, _code(r)) == (422, "media_disabled")
    assert await _posts_of(pool, me) == 0
    r = await _create(client, me, content="no pictures")
    assert r.status_code == 201


async def test_concurrent_posts_cannot_share_an_upload(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    m = await _upload(client, me)
    results = await asyncio.gather(*(
        _create(client, me, content=f"race {i}", media_ids=[m]) for i in range(4)
    ))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 422, 422, 422], [r.text for r in results]
    assert await _posts_of(pool, me) == 1


# ── Replies, quotes, threads ──────────────────────────────────────────────────

async def test_reply_and_quote_carry_media(client, pool, agents, media_on, quiet, optional_login):
    me = await agents("poster", age_days=30)
    root = (await _create(client, me, content="root")).json()["post_id"]
    m1, m2 = await _upload(client, me), await _upload(client, me)

    r = await client.post(f"/posts/{root}/replies", headers=me.headers,
                          json=_post(content="", media_ids=[m1]))
    assert r.status_code == 201, r.text
    assert [x["media_id"] for x in r.json()["media"]] == [m1]

    r = await _create(client, me, content="look", media_ids=[m2], quote_post_id=root)
    assert r.status_code == 201, r.text
    assert [x["media_id"] for x in r.json()["media"]] == [m2]

    r = await client.post(f"/posts/{root}/replies", headers=me.headers,
                          json=_post(content="again", media_ids=[m1]))
    assert (r.status_code, _code(r)) == (422, "media_in_use")


async def test_thread_items_carry_media_and_a_bad_item_rolls_back(
    client, pool, agents, media_on, quiet,
):
    me = await agents("poster", age_days=30)
    a, b, c = [await _upload(client, me) for _ in range(3)]
    bad = {"items": [
        {"content": "one", "media_ids": [a]},
        {"content": "", "media_ids": [b]},
        {"content": "three", "media_ids": [a]},          # already used by item one
    ]}
    r = await client.post("/posts/thread", json=bad, headers=me.headers)
    assert (r.status_code, _code(r)) == (422, "media_in_use")
    assert await _posts_of(pool, me) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM media WHERE owner_did = $1 AND post_id IS NOT NULL", me.did,
    ) == 0

    good = {"items": [
        {"content": "one", "media_ids": [a, b]},
        {"content": "", "media_ids": [c]},
        {"content": "three"},
    ]}
    r = await client.post("/posts/thread", json=good, headers=me.headers)
    assert r.status_code == 201, r.text
    posts = r.json()["posts"]
    assert [[m["media_id"] for m in p["media"]] for p in posts] == [[a, b], [c], []]


# ── Visibility ────────────────────────────────────────────────────────────────

async def test_pending_media_hidden_from_others(client, pool, agents, media_on, quiet, optional_login):
    new = await agents("newbie", age_days=1)
    other = await agents("reader", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    m = await _upload(client, new, alt="secret alt")
    r = await _create(client, new, content="my first picture", media_ids=[m])
    assert r.status_code == 201, r.text
    pid = r.json()["post_id"]
    own = r.json()["media"][0]
    assert own["status"] == "PENDING" and own["url"] and own["alt_text"] == "secret alt"

    for headers in ({}, other.headers):
        item = (await client.get(f"/posts/{pid}", headers=headers)).json()["media"][0]
        assert item == {"media_id": m, "status": "PENDING", "url": None, "alt_text": None,
                        "width": 40, "height": 30}
    item = (await client.get(f"/posts/{pid}", headers=mod.headers)).json()["media"][0]
    assert item["url"] and item["alt_text"] == "secret alt"
    item = (await client.get(f"/posts/{pid}", headers=new.headers)).json()["media"][0]
    assert item["url"]


async def test_rejected_media_is_left_out(client, pool, agents, media_on, quiet, optional_login):
    me = await agents("poster", age_days=30)
    a, b = await _upload(client, me), await _upload(client, me)
    pid = (await _create(client, me, content="two", media_ids=[a, b])).json()["post_id"]
    await pool.execute("UPDATE media SET status = 'REJECTED' WHERE id = $1", a)
    body = (await client.get(f"/posts/{pid}")).json()
    assert [m["media_id"] for m in body["media"]] == [b]


async def test_held_post_media_is_pending(client, pool, agents, media_on, quiet, optional_login):
    me = await agents("poster", age_days=30)
    m = await _upload(client, me)
    r = await _create(client, me, content="Sign up with my referral link for 30% commission",
                      media_ids=[m])
    assert r.status_code == 201, r.text
    assert r.json()["hidden"] is True
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", m) == "PENDING"


async def test_held_thread_media_is_pending(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    a, b = await _upload(client, me), await _upload(client, me)
    r = await client.post("/posts/thread", headers=me.headers, json={"items": [
        {"content": "nice photo", "media_ids": [a]},
        {"content": "buy followers cheap here", "media_ids": [b]},
    ]})
    assert r.status_code == 201, r.text
    statuses = await pool.fetch("SELECT status FROM media WHERE id = ANY($1::uuid[])", [a, b])
    assert {s["status"] for s in statuses} == {"PENDING"}


async def test_moderator_hide_makes_media_pending(client, pool, agents, media_on, quiet, optional_login):
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = await _upload(client, me)
    pid = (await _create(client, me, content="fine", media_ids=[m])).json()["post_id"]
    r = await client.post(f"/posts/{pid}/hide", json={"reason": "spam"}, headers=mod.headers)
    assert r.status_code == 200, r.text
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", m) == "PENDING"
    r = await client.get(f"/media/{m}.png")
    assert r.status_code == 404                     # no longer public
    r = await client.post(f"/posts/{pid}/unhide", json={}, headers=mod.headers)
    assert r.status_code == 200, r.text
    # Unhiding does not approve the image by itself (S4-5 queue does).
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", m) == "PENDING"


async def test_flag_auto_hide_makes_media_pending(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    m = await _upload(client, me)
    pid = (await _create(client, me, content="fine", media_ids=[m])).json()["post_id"]
    for i in range(3):
        flagger = await agents(f"flagger{i}", age_days=30)
        r = await client.post(f"/posts/{pid}/flag", json={"reason": "spam"},
                              headers=flagger.headers)
        assert r.status_code in (200, 201), r.text
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", m) == "PENDING"


# ── Every read path carries media ─────────────────────────────────────────────

async def test_feeds_conversation_and_profile_carry_media(
    client, pool, agents, media_on, quiet, optional_login,
):
    me = await agents("poster", age_days=30)
    reader = await agents("reader", age_days=30)
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", reader.did, me.did,
    )
    m, rm = await _upload(client, me), await _upload(client, me)
    pid = (await _create(client, me, content="with a picture", media_ids=[m])).json()["post_id"]
    rid = (await client.post(f"/posts/{pid}/replies", headers=me.headers,
                             json=_post(content="reply pic", media_ids=[rm]))).json()["post_id"]

    # Other test files leave posts dated in the future; put this one on top,
    # and drop the 30 s anonymous response cache.
    from src.middleware import response_cache
    await pool.execute(
        "UPDATE posts SET created_at = (SELECT max(created_at) FROM posts) + INTERVAL '1 minute'"
        " WHERE post_id = $1", pid,
    )
    response_cache.invalidate()

    def find(items, post_id):
        for p in items:
            if p["post_id"] == post_id:
                return p
        raise AssertionError(f"{post_id} not in page")

    pages = {
        "global": (await client.get("/posts/global")).json(),
        "list": (await client.get("/posts", params={"author_did": me.did})).json(),
        "latest": (await client.get("/feed/latest")).json(),
        "following": (await client.get("/feed/following", headers=reader.headers)).json(),
        "profile": (await client.get(f"/agents/{me.did}/posts", headers=reader.headers)).json(),
    }
    for name, items in pages.items():
        if isinstance(items, dict):
            items = items.get("posts", items.get("items"))
        assert [x["media_id"] for x in find(items, pid)["media"]] == [m], name

    convo = (await client.get(f"/posts/{pid}/conversation")).json()
    assert [x["media_id"] for x in convo["post"]["media"]] == [m]
    assert [x["media_id"] for x in convo["replies"][0]["post"]["media"]] == [rm]
    replies = (await client.get(f"/agents/{me.did}/replies", headers=reader.headers)).json()
    if isinstance(replies, dict):
        replies = replies.get("posts", replies.get("items"))
    assert [x["media_id"] for x in find(replies, rid)["media"]] == [rm]


async def test_openapi_documents_media(client):
    spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    assert schemas["src__models__post__PostCreate"]["properties"]["media_ids"]["maxItems"] == 4
    assert "media_ids" in schemas["ThreadItem"]["properties"]
    assert "media" in schemas["src__models__post__PostResponse"]["properties"]
    assert set(schemas["PostMedia"]["required"]) >= {"media_id", "status", "width", "height"}
