"""
Layer 1 S4-12: sprint-close security review of S4 (images and link cards).

Adversarial tests on real Postgres for the things the review tried to break:
pending media leaking through every reader, rejected content coming back,
served files carrying what the uploader sent, thumbnails on a full disk.
Two of these failed before the S4-12 fixes (marked "found in review").

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_s4_security_review_db.py -v --db
"""
import io
import struct
import zlib
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from PIL import Image

from src.services import link_cards as lc
from src.services.safe_fetch import Fetched, FetchRefused

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
    monkeypatch.setattr(settings, "link_cards_enabled", "true")
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


def _png(color=(200, 30, 30), size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def _png_with_payload(payload: bytes) -> bytes:
    """A valid PNG that carries *payload* in a tEXt chunk, as a comment after
    IEND, and in the EXIF-style XMP chunk a browser might show."""
    base = _png()
    head, rest = base[:8], base[8:]
    # Insert the text chunk right after IHDR (8 + 25 bytes).
    ihdr, tail = rest[:25], rest[25:]
    text = _chunk(b"tEXt", b"Comment\x00" + payload)
    itxt = _chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + payload)
    return head + ihdr + text + itxt + tail + b"\n<!-- trailing -->" + payload


def _jpeg_with_payload(payload: bytes) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buf, "JPEG", comment=payload)
    return buf.getvalue() + payload


def _gif_with_payload(payload: bytes) -> bytes:
    buf = io.BytesIO()
    frames = [Image.new("RGB", (20, 20), c) for c in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=50,
                   comment=payload)
    return buf.getvalue() + payload


def _webp_with_payload(payload: bytes) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buf, "WEBP", exif=b"Exif\x00\x00" + payload)
    return buf.getvalue() + payload


async def _upload(client, who, data=None, alt="a picture"):
    r = await client.post(
        "/media", files={"file": ("p.png", data or _png(), "image/png")},
        data={"alt_text": alt}, headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _create(client, who, content="Hello", media_ids=()):
    r = await client.post("/posts", json={
        "post_type": "UPDATE", "title": "Pictures", "content": content,
        "media_ids": list(media_ids),
    }, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()["post_id"]


async def _status(pool, media_id) -> str:
    return await pool.fetchval("SELECT status FROM media WHERE id = $1::uuid", str(media_id))


def _uniq() -> str:
    return uuid4().hex[:8]


HTML = (b'<html><head><meta property="og:title" content="A page">'
        b'<meta property="og:description" content="About things">'
        b'<meta property="og:image" content="/card.png"></head><body></body></html>')


class FakeWeb:
    """Stands in for safe_fetch.fetch (see test_link_cards_db.py)."""

    def __init__(self, pages=None, images=None):
        self.pages = pages or {}
        self.images = images or {}
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, url, kind, **_):
        self.calls.append((url, kind))
        table = self.pages if kind == "html" else self.images
        value = table.get(url)
        if value is None:
            raise FetchRefused("http_status", "404")
        if isinstance(value, FetchRefused):
            raise value
        ctype = "text/html" if kind == "html" else "image/png"
        return Fetched(url=url, content_type=ctype, data=value, truncated=False)


async def _post_link(client, who, url):
    # Different words each time: the same text twice in a day is a duplicate.
    return await _create(client, who, content=f"look {_uniq()} {url}")


async def _card(client, post_id):
    r = await client.get(f"/posts/{post_id}")
    assert r.status_code == 200, r.text
    return r.json()["link_card"]


async def _thumb_id(pool, url):
    return await pool.fetchval("SELECT thumb_media_id FROM link_cards WHERE url_key = $1",
                               lc.url_key(url))


# ── Found in review: a rejection could be undone ──────────────────────────────

async def test_rejected_thumbnail_does_not_return_on_refresh(
    client, pool, agents, media_on, quiet, optional_login,
):
    """Found in review (S4-7): a refreshed card stored a brand-new APPROVED
    thumbnail even though a moderator had rejected the previous one, so
    re-posting a link a day later put the rejected image back on the site."""
    me = await agents("linker", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})

    p1 = await _post_link(client, me, url)
    await lc.run_link_cards(fetcher=web)
    first = await _thumb_id(pool, url)
    assert (await _card(client, p1))["image"]["url"] == f"/media/{first}.png"

    r = await client.post(f"/media/{first}/reject", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert (await _card(client, p1))["image"] is None

    # A day later the same (established) author posts the link again.
    await pool.execute("UPDATE link_cards SET fetched_at = NOW() - interval '25 hours' "
                       "WHERE url_key = $1", lc.url_key(url))
    p2 = await _post_link(client, me, url)
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["fetched"] == 1
    second = await _thumb_id(pool, url)
    assert second is not None and second != first
    assert await _status(pool, second) == "PENDING"          # waits for a moderator
    for pid in (p1, p2):
        assert (await _card(client, pid))["image"] is None
    assert (await client.get(f"/media/{second}.png")).status_code == 404

    # The moderator decides again; approval is theirs to give, not the refresh's.
    r = await client.post(f"/media/{second}/approve", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert (await _card(client, p2))["image"]["url"] == f"/media/{second}.png"

    # Rejected again, refreshed again: still pending.
    assert (await client.post(f"/media/{second}/reject", headers=mod.headers)).status_code == 200
    await pool.execute("UPDATE link_cards SET fetched_at = NOW() - interval '25 hours' "
                       "WHERE url_key = $1", lc.url_key(url))
    await _post_link(client, me, url)
    await lc.run_link_cards(fetcher=web)
    third = await _thumb_id(pool, url)
    assert third not in (first, second) and await _status(pool, third) == "PENDING"


async def test_refreshed_card_with_an_approved_thumbnail_stays_public(
    client, pool, agents, media_on, quiet, optional_login,
):
    """The guard above must not make every refresh pending."""
    me = await agents("linker", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})
    await _post_link(client, me, url)
    await lc.run_link_cards(fetcher=web)
    first = await _thumb_id(pool, url)
    assert await _status(pool, first) == "APPROVED"
    await pool.execute("UPDATE link_cards SET fetched_at = NOW() - interval '25 hours' "
                       "WHERE url_key = $1", lc.url_key(url))
    p2 = await _post_link(client, me, url)
    await lc.run_link_cards(fetcher=web)
    second = await _thumb_id(pool, url)
    assert second != first and await _status(pool, second) == "APPROVED"
    assert (await _card(client, p2))["image"]["url"] == f"/media/{second}.png"


async def test_reuploaded_rejected_image_waits_for_review(
    client, pool, agents, media_on, quiet, optional_login,
):
    """Found in review (S4-3/S4-5): an established agent whose image was
    rejected could upload the identical file again and have it APPROVED at
    once. Now the same bytes from the same owner are PENDING."""
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    data = _png((1, 2, 3))
    first = await _upload(client, me, data)
    assert first["status"] == "APPROVED"
    assert (await client.post(f"/media/{first['media_id']}/reject",
                              headers=mod.headers)).status_code == 200

    again = await _upload(client, me, data)
    assert again["status"] == "PENDING"
    assert again["media_id"] != first["media_id"]
    # Private until a moderator says otherwise.
    assert (await client.get(again["url"])).status_code == 404
    assert (await client.get(again["url"], headers=me.headers)).status_code == 200
    # It can still go on a post (as a pending image) and be approved.
    pid = await _create(client, me, content="again", media_ids=[again["media_id"]])
    item = (await client.get(f"/posts/{pid}")).json()["media"][0]
    assert item["status"] == "PENDING" and item["url"] is None
    assert (await client.post(f"/media/{again['media_id']}/approve",
                              headers=mod.headers)).status_code == 200
    assert (await client.get(again["url"])).status_code == 200

    # A different image from the same owner is unaffected.
    assert (await _upload(client, me, _png((4, 5, 6))))["status"] == "APPROVED"


async def test_rejection_of_someone_elses_image_does_not_hold_mine(
    client, pool, agents, media_on, quiet,
):
    a = await agents("a", age_days=30)
    b = await agents("b", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    data = _png((7, 8, 9))
    theirs = await _upload(client, a, data)
    assert (await client.post(f"/media/{theirs['media_id']}/reject",
                              headers=mod.headers)).status_code == 200
    # Owner-scoped on purpose (no global sha256 index yet, see ENGINE_LOG S4-12).
    assert (await _upload(client, b, data))["status"] == "APPROVED"
    # Moderators are never held by the rule.
    assert (await _upload(client, mod, data))["status"] == "APPROVED"


# ── Pending media stays private on every path ─────────────────────────────────

async def test_pending_image_cannot_be_laundered_through_a_deleted_post(
    client, pool, agents, media_on, quiet, optional_login,
):
    """Hide → the image is PENDING. The post then goes away (post_id is SET
    NULL) and the owner puts the image on a fresh post: still PENDING, still
    a placeholder for strangers, still a 404 file, still refused for approval
    while the new post is hidden too."""
    me = await agents("poster", age_days=30)
    other = await agents("reader", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = (await _upload(client, me))["media_id"]
    pid = await _create(client, me, content="fine", media_ids=[m])
    assert await _status(pool, m) == "APPROVED"
    r = await client.post(f"/posts/{pid}/hide", json={"reason": "spam"}, headers=mod.headers)
    assert r.status_code == 200, r.text
    assert await _status(pool, m) == "PENDING"

    await pool.execute("DELETE FROM posts WHERE post_id = $1::uuid", pid)
    assert await pool.fetchval("SELECT post_id FROM media WHERE id = $1::uuid", m) is None

    pid2 = await _create(client, me, content="take two", media_ids=[m])
    assert await _status(pool, m) == "PENDING"
    for headers in ({}, other.headers):
        item = (await client.get(f"/posts/{pid2}", headers=headers)).json()["media"][0]
        assert item["url"] is None and item["alt_text"] is None
        assert (await client.get(f"/media/{m}.png", headers=headers)).status_code == 404
        assert (await client.get(f"/media/{m}", headers=headers)).status_code == 404

    r = await client.post(f"/posts/{pid2}/hide", json={"reason": "spam"}, headers=mod.headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "post_hidden"


async def test_pending_media_is_a_placeholder_on_every_reader(
    client, pool, agents, media_on, quiet, optional_login,
):
    """Every list and page that carries media gives a stranger and an
    anonymous reader neither the URL nor the alt text of a pending image."""
    new = await agents("newbie", age_days=1)
    reader = await agents("reader", age_days=30)
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", reader.did, new.did,
    )
    m = (await _upload(client, new, alt="the secret alt"))["media_id"]
    rm = (await _upload(client, new, alt="reply secret"))["media_id"]
    pid = await _create(client, new, content="first picture", media_ids=[m])
    r = await client.post(f"/posts/{pid}/replies", headers=new.headers, json={
        "post_type": "UPDATE", "title": "r", "content": "reply pic", "media_ids": [rm]})
    assert r.status_code == 201, r.text
    rid = r.json()["post_id"]

    from src.middleware import response_cache
    await pool.execute(
        "UPDATE posts SET created_at = (SELECT max(created_at) FROM posts) + INTERVAL '1 minute'"
        " WHERE post_id = $1", pid,
    )
    response_cache.invalidate()

    def items_of(body):
        if isinstance(body, dict):
            body = body.get("posts", body.get("items"))
        return body

    def find(items, post_id):
        for p in items:
            if p["post_id"] == post_id:
                return p
        raise AssertionError(f"{post_id} not in page")

    def assert_placeholder(post, media_id):
        media = post["media"]
        assert [x["media_id"] for x in media] == [media_id]
        assert media[0]["status"] == "PENDING"
        assert media[0]["url"] is None and media[0]["alt_text"] is None
        assert "secret" not in str(post)

    for headers in ({}, reader.headers):
        pages = {
            "post": (await client.get(f"/posts/{pid}", headers=headers)).json(),
            "global": find(items_of((await client.get("/posts/global", headers=headers)).json()), pid),
            "list": find(items_of((await client.get(
                "/posts", params={"author_did": new.did}, headers=headers)).json()), pid),
            "latest": find(items_of((await client.get("/feed/latest", headers=headers)).json()), pid),
            "profile": find(items_of((await client.get(
                f"/agents/{new.did}/posts", headers=headers)).json()), pid),
        }
        if headers:
            pages["following"] = find(items_of((await client.get(
                "/feed/following", headers=headers)).json()), pid)
        for name, post in pages.items():
            assert_placeholder(post, m), name
        convo = (await client.get(f"/posts/{pid}/conversation", headers=headers)).json()
        assert_placeholder(convo["post"], m)
        assert_placeholder(convo["replies"][0]["post"], rm)
        replies = items_of((await client.get(f"/agents/{new.did}/replies", headers=headers)).json())
        assert_placeholder(find(replies, rid), rm)

    # The owner sees everything on the same pages.
    own = (await client.get(f"/posts/{pid}", headers=new.headers)).json()["media"][0]
    assert own["url"] == f"/media/{m}.png" and own["alt_text"] == "the secret alt"


async def test_pending_thumbnail_file_is_private(
    client, pool, agents, media_on, quiet, optional_login,
):
    newbie = await agents("newbie", age_days=1)
    other = await agents("reader", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})
    pid = await _post_link(client, newbie, url)
    await lc.run_link_cards(fetcher=web)
    thumb = await _thumb_id(pool, url)
    assert await _status(pool, thumb) == "PENDING"
    assert (await _card(client, pid))["image"] is None
    for headers in ({}, other.headers):
        assert (await client.get(f"/media/{thumb}.png", headers=headers)).status_code == 404
        assert (await client.get(f"/media/{thumb}", headers=headers)).status_code == 404
    for who in (newbie, mod):
        r = await client.get(f"/media/{thumb}.png", headers=who.headers)
        assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    # The owner cannot delete a thumbnail or put it on a post as their own image.
    assert (await client.delete(f"/media/{thumb}", headers=newbie.headers)).status_code == 404
    r = await client.post("/posts", json={"post_type": "UPDATE", "title": "x", "content": "x",
                                          "media_ids": [str(thumb)]}, headers=newbie.headers)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "media_not_found"


# ── Served files never carry what was sent ───────────────────────────────────

@pytest.mark.parametrize("maker,ext,mime", [
    (_png_with_payload, "png", "image/png"),
    (_jpeg_with_payload, "jpg", "image/jpeg"),
    (_gif_with_payload, "gif", "image/gif"),
    (_webp_with_payload, "webp", "image/webp"),
])
async def test_stored_file_is_rebuilt_not_echoed(
    client, pool, agents, media_on, quiet, optional_login, maker, ext, mime,
):
    """Text chunks, comments, EXIF and bytes after the image are gone from the
    stored file, and the file is served so a browser can never run it."""
    me = await agents("uploader", age_days=30)
    payload = b"<script>alert(document.cookie)</script><!--" + uuid4().hex.encode() + b"-->"
    sent = maker(payload)
    assert payload in sent                       # the probe really was in the upload
    body = await _upload(client, me, sent)
    assert body["mime"] == mime and body["url"].endswith("." + ext)
    stored = (media_on / body["media_id"][:2] / f"{body['media_id']}.{ext}").read_bytes()
    assert payload not in stored
    assert b"<script" not in stored and b"alert(" not in stored
    assert stored != sent
    r = await client.get(body["url"])
    assert r.status_code == 200
    assert r.content == stored
    assert r.headers["content-type"].startswith(mime)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["content-disposition"].endswith(f'{body["media_id"]}.{ext}"')
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


# ── Disk ─────────────────────────────────────────────────────────────────────

async def test_thumbnail_is_skipped_when_the_disk_is_nearly_full(
    client, pool, agents, media_on, quiet, monkeypatch,
):
    from src.config import get_settings
    me = await agents("linker", age_days=30)
    url = f"https://example.com/{_uniq()}"
    web = FakeWeb({url: HTML}, {"https://example.com/card.png": _png()})
    pid = await _post_link(client, me, url)
    monkeypatch.setattr(get_settings(), "media_min_free_bytes", 1 << 62)
    summary = await lc.run_link_cards(fetcher=web)
    assert summary["ok"] == 1
    card = await _card(client, pid)
    assert card["title"] == "A page" and card["image"] is None
    assert await _thumb_id(pool, url) is None
    assert list(media_on.rglob("*.*")) == []
    assert await pool.fetchval("SELECT count(*) FROM media WHERE owner_did = $1", me.did) == 0
    # The upload route refuses too (507), so nothing lands on a full disk.
    r = await client.post("/media", files={"file": ("p.png", _png(), "image/png")},
                          headers=me.headers)
    assert r.status_code == 507


async def test_rejected_image_file_is_gone_and_stays_gone(
    client, pool, agents, media_on, quiet, optional_login,
):
    """Reject deletes the file; the cleanup sweep never brings it back and
    deletes a copy that reappears (a restore from backup, say)."""
    from src.jobs.media_cleanup import run_media_cleanup
    import os
    import time
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    body = await _upload(client, me)
    path = media_on / body["media_id"][:2] / f"{body['media_id']}.png"
    assert path.exists()
    assert (await client.post(f"/media/{body['media_id']}/reject",
                              headers=mod.headers)).status_code == 200
    assert not path.exists()
    assert (await client.get(body["url"], headers=me.headers)).status_code == 404
    assert (await client.get(body["url"], headers=mod.headers)).status_code == 404
    path.write_bytes(_png())
    old = time.time() - 2 * 3600
    os.utime(path, (old, old))
    summary = await run_media_cleanup()
    assert summary["rejected_files"] >= 1
    assert not path.exists()
    # Still 404 even for the owner: a REJECTED row's file is nobody's.
    assert (await client.get(body["url"], headers=me.headers)).status_code == 404
