"""
Layer 1 S4-5: the media approval queue on real Postgres.

GET  /media/moderation/queue  — PENDING images, oldest first, with owner and post
POST /media/{id}/approve      — PENDING → APPROVED (public, cacheable); refused
                                while the post is hidden or held
POST /media/{id}/reject       — → REJECTED, file deleted, row kept, post shows nothing

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_media_moderation_db.py -v --db
"""
import asyncio
import io

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


@pytest_asyncio.fixture
async def clean_pending(pool):
    """The queue is global: start from no PENDING images of other test files."""
    await pool.execute("UPDATE media SET status = 'REJECTED' WHERE status = 'PENDING'")
    yield


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


async def _create(client, who, content="Hello", media_ids=()):
    r = await client.post("/posts", json={
        "post_type": "UPDATE", "title": "Pictures", "content": content,
        "media_ids": list(media_ids),
    }, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()["post_id"]


def _code(r) -> str:
    return r.json()["detail"]["code"]


async def _status(pool, media_id) -> str:
    return await pool.fetchval("SELECT status FROM media WHERE id = $1", media_id)


def _file(root, media_id):
    return root / media_id[:2] / f"{media_id}.png"


# ── Who may review ────────────────────────────────────────────────────────────

async def test_agents_and_anonymous_cannot_review(client, pool, agents, media_on, quiet):
    new = await agents("newbie", age_days=1)
    other = await agents("other", age_days=30)
    m = await _upload(client, new)
    for who in (new, other):
        assert (await client.get("/media/moderation/queue", headers=who.headers)).status_code == 403
        assert (await client.post(f"/media/{m}/approve", headers=who.headers)).status_code == 403
        assert (await client.post(f"/media/{m}/reject", headers=who.headers)).status_code == 403
    assert (await client.get("/media/moderation/queue")).status_code == 401
    assert (await client.post(f"/media/{m}/approve")).status_code == 401
    assert (await client.post(f"/media/{m}/reject")).status_code == 401
    assert await _status(pool, m) == "PENDING"
    assert _file(media_on, m).exists()


# ── Queue ─────────────────────────────────────────────────────────────────────

async def test_queue_lists_pending_oldest_first_with_owner_and_post(
    client, pool, agents, media_on, quiet, clean_pending, optional_login,
):
    new = await agents("newbie", age_days=2)
    old = await agents("veteran", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    first = await _upload(client, new, alt="first")
    second = await _upload(client, new, alt="second")
    public = await _upload(client, old)                    # APPROVED: not queued
    await pool.execute(
        "UPDATE media SET created_at = NOW() - INTERVAL '1 hour' WHERE id = $1", second,
    )
    pid = await _create(client, new, content="look at this", media_ids=[first])

    r = await client.get("/media/moderation/queue", headers=mod.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [m["media_id"] for m in body["media"]]
    assert ids == [second, first]
    assert public not in ids
    assert body["total"] == 2 and body["has_more"] is False
    item = body["media"][1]
    assert item["status"] == "PENDING" and item["kind"] == "UPLOAD"
    assert item["url"] == f"/media/{first}.png" and item["alt_text"] == "first"
    assert item["owner"]["did"] == new.did and item["owner"]["created_at"]
    assert item["post"] == {"post_id": pid, "hidden": False, "content": "look at this"}
    assert body["media"][0]["post"] is None
    # The moderator can fetch the pending file with their token.
    assert (await client.get(item["url"], headers=mod.headers)).status_code == 200

    r = await client.get("/media/moderation/queue?limit=1&page=2", headers=mod.headers)
    assert [m["media_id"] for m in r.json()["media"]] == [first]
    r = await client.get("/media/moderation/queue?limit=1", headers=mod.headers)
    assert r.json()["has_more"] is True
    for bad in ("limit=0", "page=0", "page=x"):
        assert (await client.get(f"/media/moderation/queue?{bad}", headers=mod.headers)).status_code == 422


# ── Approve ───────────────────────────────────────────────────────────────────

async def test_approve_makes_image_public_and_cacheable(
    client, pool, agents, media_on, quiet, optional_login,
):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = await _upload(client, new)
    pid = await _create(client, new, media_ids=[m])
    assert (await client.get(f"/media/{m}.png")).status_code == 404
    anon = (await client.get(f"/posts/{pid}")).json()["media"][0]
    assert anon["url"] is None

    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["reviewed_by"] == mod.did and body["reviewed_at"]
    row = await pool.fetchrow("SELECT reviewed_by, reviewed_at FROM media WHERE id = $1", m)
    assert row["reviewed_by"] == mod.did and row["reviewed_at"] is not None

    f = await client.get(f"/media/{m}.png")
    assert f.status_code == 200
    assert f.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert f.headers["x-content-type-options"] == "nosniff"
    anon = (await client.get(f"/posts/{pid}")).json()["media"][0]
    assert anon["url"] == f"/media/{m}.png" and anon["alt_text"] == "a picture"
    # Public details carry no reviewer.
    assert "reviewed_by" not in (await client.get(f"/media/{m}")).json()

    # Not pending any more: approve again or approve a rejected image → 409.
    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 409 and _code(r) == "not_pending"


async def test_approve_refused_while_post_is_hidden(
    client, pool, agents, media_on, quiet, optional_login,
):
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = await _upload(client, me)
    pid = await _create(client, me, content="fine", media_ids=[m])
    assert (await client.post(f"/posts/{pid}/hide", json={"reason": "spam"},
                              headers=mod.headers)).status_code == 200
    assert await _status(pool, m) == "PENDING"

    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 409 and _code(r) == "post_hidden"
    assert await _status(pool, m) == "PENDING"
    assert (await client.get(f"/media/{m}.png")).status_code == 404

    q = (await client.get("/media/moderation/queue?limit=200", headers=mod.headers)).json()
    entry = next(x for x in q["media"] if x["media_id"] == m)
    assert entry["post"]["hidden"] is True

    assert (await client.post(f"/posts/{pid}/unhide", json={},
                              headers=mod.headers)).status_code == 200
    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert (await client.get(f"/media/{m}.png")).status_code == 200


async def test_approve_refused_on_held_post(client, pool, agents, media_on, quiet):
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    m = await _upload(client, me)
    pid = await _create(client, me, content="buy followers cheap here", media_ids=[m])
    assert await pool.fetchval("SELECT hidden_at IS NOT NULL FROM posts WHERE post_id = $1", pid)
    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 409 and _code(r) == "post_hidden"
    assert await _status(pool, m) == "PENDING"


async def test_unattached_pending_image_can_be_approved(client, pool, agents, media_on, quiet):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    m = await _upload(client, new)
    r = await client.post(f"/media/{m}/approve", headers=mod.headers)
    assert r.status_code == 200 and r.json()["post"] is None
    assert (await client.get(f"/media/{m}.png")).status_code == 200


# ── Reject ────────────────────────────────────────────────────────────────────

async def test_reject_deletes_file_keeps_row_and_post_shows_nothing(
    client, pool, agents, media_on, quiet, optional_login,
):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    keep = await _upload(client, new, alt="keep")
    bad = await _upload(client, new, alt="bad")
    pid = await _create(client, new, media_ids=[bad, keep])
    assert _file(media_on, bad).exists()

    r = await client.post(f"/media/{bad}/reject", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED" and r.json()["url"] is None
    assert r.json()["reviewed_by"] == mod.did
    assert not _file(media_on, bad).exists()
    assert await _status(pool, bad) == "REJECTED"           # row kept

    for headers in ({}, new.headers, mod.headers):
        media = (await client.get(f"/posts/{pid}", headers=headers)).json()["media"]
        assert [x["media_id"] for x in media] == [keep]
        assert (await client.get(f"/media/{bad}.png", headers=headers)).status_code == 404
    # The owner still sees what happened.
    owner_view = await client.get(f"/media/{bad}", headers=new.headers)
    assert owner_view.status_code == 200 and owner_view.json()["status"] == "REJECTED"
    assert (await client.get(f"/media/{bad}")).status_code == 404

    r = await client.post(f"/media/{bad}/reject", headers=mod.headers)
    assert r.status_code == 409 and _code(r) == "already_rejected"
    r = await client.post(f"/media/{bad}/approve", headers=mod.headers)
    assert r.status_code == 409 and _code(r) == "not_pending"


async def test_reject_an_approved_image_takes_it_down(
    client, pool, agents, media_on, quiet, optional_login,
):
    me = await agents("poster", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    m = await _upload(client, me)
    pid = await _create(client, me, media_ids=[m])
    assert (await client.get(f"/media/{m}.png")).status_code == 200
    r = await client.post(f"/media/{m}/reject", headers=mod.headers)
    assert r.status_code == 200, r.text
    assert (await client.get(f"/media/{m}.png")).status_code == 404
    assert (await client.get(f"/posts/{pid}")).json()["media"] == []
    assert not _file(media_on, m).exists()


async def test_rejected_unattached_image_cannot_be_posted(client, pool, agents, media_on, quiet):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = await _upload(client, new)
    assert (await client.post(f"/media/{m}/reject", headers=mod.headers)).status_code == 200
    r = await client.post("/posts", json={
        "post_type": "UPDATE", "title": "x", "content": "x", "media_ids": [m],
    }, headers=new.headers)
    assert r.status_code == 422 and _code(r) == "media_rejected"


async def test_reject_survives_a_missing_file(client, pool, agents, media_on, quiet):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    m = await _upload(client, new)
    _file(media_on, m).unlink()
    r = await client.post(f"/media/{m}/reject", headers=mod.headers)
    assert r.status_code == 200 and await _status(pool, m) == "REJECTED"


# ── Ids and races ─────────────────────────────────────────────────────────────

async def test_bad_and_unknown_ids_are_404(client, agents, media_on, quiet):
    from uuid import uuid4
    mod = await agents("mod", role="FOUNDER", age_days=30)
    for bad in (str(uuid4()), "not-a-uuid", str(uuid4()).upper(), "..%2F..%2Fetc"):
        for action in ("approve", "reject"):
            r = await client.post(f"/media/{bad}/{action}", headers=mod.headers)
            assert r.status_code == 404, (bad, action, r.text)


async def test_parallel_approve_and_reject_end_in_one_state(
    client, pool, agents, media_on, quiet,
):
    new = await agents("newbie", age_days=1)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    for _ in range(3):
        m = await _upload(client, new)
        a, r = await asyncio.gather(
            client.post(f"/media/{m}/approve", headers=mod.headers),
            client.post(f"/media/{m}/reject", headers=mod.headers),
        )
        final = await _status(pool, m)
        # Reject always lands (it may follow an approval); approve lands only first.
        assert r.status_code == 200 and final == "REJECTED"
        assert a.status_code in (200, 409)
        assert not _file(media_on, m).exists()


async def test_openapi_lists_review_routes(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "get" in paths["/media/moderation/queue"]
    assert "post" in paths["/media/{media_id}/approve"]
    assert "post" in paths["/media/{media_id}/reject"]
