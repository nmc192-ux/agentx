"""
Layer 1 S4-3: image uploads, storage and serving on real Postgres.

POST   /media             — switch, multipart, pipeline codes, PENDING for new
                            agents, alt text rules, 50-a-day cap, disk guard
GET    /media/{id}.{ext}  — stored type + nosniff + CSP; PENDING only to owner
                            and moderators (never cached); REJECTED 404
GET    /media/{id}        — metadata with the same visibility
DELETE /media/{id}        — owner, unattached only

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_media_upload_db.py -v --db
"""
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
    """The limiters are not under test (the harness sends no Bearer token)."""
    from src.middleware.rate_limits import limiter, limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setattr(limiter, "enabled", False)
    yield


@pytest_asyncio.fixture
async def media_root(tmp_path, monkeypatch):
    from src.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "media_enabled", "true")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_min_free_bytes", 0)
    yield tmp_path


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


def _png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_gps() -> bytes:
    im = Image.new("RGB", (64, 48), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"                       # Make
    gps = {1: "N", 2: (33.0, 41.0, 0.0), 3: "E", 4: (73.0, 3.0, 0.0)}
    exif[0x8825] = gps                               # GPSInfo
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    data = buf.getvalue()
    assert b"SecretCam" in data
    return data


async def _upload(client, who, data, *, alt="", name="photo.png", ctype="image/png"):
    return await client.post(
        "/media",
        files={"file": (name, data, ctype)},
        data={"alt_text": alt},
        headers=who.headers if who is not None else {},
    )


async def _rows(pool, who) -> int:
    return await pool.fetchval("SELECT count(*) FROM media WHERE owner_did = $1", who.did)


def _files(root) -> list:
    return [p for p in root.rglob("*") if p.is_file()]


# ── Switch ────────────────────────────────────────────────────────────────────

async def test_switch_off_hides_upload_but_keeps_serving(
    client, pool, agents, media_root, quiet, optional_login, monkeypatch,
):
    from src.config import get_settings
    me = await agents("uploader", age_days=30)
    r = await _upload(client, me, _png())
    assert r.status_code == 201, r.text
    url = r.json()["url"]

    for off in ("false", "", "no", "TRUE-ish", "0"):
        monkeypatch.setattr(get_settings(), "media_enabled", off)
        r = await _upload(client, me, _png())
        assert r.status_code == 404, (off, r.text)
    assert await _rows(pool, me) == 1
    r = await client.get(url)
    assert r.status_code == 200
    r = await client.get(url.rsplit(".", 1)[0])
    assert r.status_code == 200


async def test_default_setting_is_off():
    from src.config import Settings
    from src.routers import media
    assert Settings.model_fields["media_enabled"].default == "false"
    assert media.MAX_ALT_TEXT == 1000 and media.DAILY_UPLOAD_CAP == 50


# ── Upload and serve ──────────────────────────────────────────────────────────

async def test_established_agent_upload_is_public_and_clean(
    client, pool, agents, media_root, quiet, optional_login,
):
    me = await agents("uploader", age_days=30)
    r = await _upload(client, me, _jpeg_with_gps(), alt="  A blue square  ",
                      name="../../evil.html", ctype="text/html")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["mime"] == "image/jpeg" and (body["width"], body["height"]) == (64, 48)
    assert body["alt_text"] == "A blue square"
    assert body["owner_did"] == me.did and body["post_id"] is None
    assert body["url"] == f"/media/{body['media_id']}.jpg"

    files = _files(media_root)
    assert len(files) == 1 and files[0].name == f"{body['media_id']}.jpg"
    assert "evil" not in str(files[0])
    stored = files[0].read_bytes()
    assert b"SecretCam" not in stored
    assert Image.open(io.BytesIO(stored)).getexif() == {}

    row = await pool.fetchrow("SELECT * FROM media WHERE id = $1::uuid", body["media_id"])
    assert row["bytes"] == len(stored) and row["kind"] == "UPLOAD" and row["status"] == "APPROVED"

    r = await client.get(body["url"])   # anonymous
    assert r.status_code == 200
    assert r.content == stored
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["content-disposition"].startswith("inline")

    r = await client.get(f"/media/{body['media_id']}")
    assert r.status_code == 200 and r.json()["url"] == body["url"]


async def test_still_gif_is_stored_as_png(client, agents, media_root, quiet):
    me = await agents("gif", age_days=30)
    buf = io.BytesIO()
    Image.new("P", (10, 10)).save(buf, "GIF")
    r = await _upload(client, me, buf.getvalue(), name="a.gif", ctype="image/gif")
    assert r.status_code == 201, r.text
    assert r.json()["mime"] == "image/png" and r.json()["url"].endswith(".png")


async def test_new_agent_media_is_pending_and_private(
    client, pool, agents, media_root, quiet, optional_login,
):
    me = await agents("newbie", age_days=2)
    other = await agents("stranger", age_days=30)
    mod = await agents("mod", role="OPERATOR", age_days=30)
    r = await _upload(client, me, _png())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    url, meta = body["url"], f"/media/{body['media_id']}"

    for headers in ({}, other.headers):
        assert (await client.get(url, headers=headers)).status_code == 404
        assert (await client.get(meta, headers=headers)).status_code == 404

    for who in (me, mod):
        r = await client.get(url, headers=who.headers)
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["x-content-type-options"] == "nosniff"
        r = await client.get(meta, headers=who.headers)
        assert r.status_code == 200 and r.json()["status"] == "PENDING"


async def test_seven_day_boundary_and_moderators(client, agents, media_root, quiet):
    six = await agents("six", age_days=6)
    eight = await agents("eight", age_days=8)
    founder = await agents("founder", role="FOUNDER", age_days=0)
    assert (await _upload(client, six, _png())).json()["status"] == "PENDING"
    assert (await _upload(client, eight, _png())).json()["status"] == "APPROVED"
    assert (await _upload(client, founder, _png())).json()["status"] == "APPROVED"


async def test_rejected_media_is_never_served(
    client, pool, agents, media_root, quiet, optional_login,
):
    me = await agents("rej", age_days=30)
    mod = await agents("mod", role="FOUNDER", age_days=30)
    body = (await _upload(client, me, _png())).json()
    await pool.execute("UPDATE media SET status = 'REJECTED' WHERE id = $1::uuid", body["media_id"])
    for headers in ({}, me.headers, mod.headers):
        assert (await client.get(body["url"], headers=headers)).status_code == 404
    meta = f"/media/{body['media_id']}"
    assert (await client.get(meta)).status_code == 404
    r = await client.get(meta, headers=me.headers)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED" and r.json()["url"] is None


async def test_row_without_file_is_404(client, pool, agents, media_root, quiet):
    me = await agents("gone", age_days=30)
    body = (await _upload(client, me, _png())).json()
    for f in _files(media_root):
        f.unlink()
    assert (await client.get(body["url"])).status_code == 404


@pytest.mark.parametrize("path", [
    "/media/{id}.jpg",              # wrong extension for a PNG
    "/media/{ID}.png",              # upper-case id is not the canonical form
    "/media/{id}.PNG",
    "/media/{id}.html",
    "/media/{id}.png.png",
    "/media/{hex}.png",             # 32-hex form is not canonical either
    "/media/..%2F..%2Fetc%2Fpasswd",
    "/media/..%2F{id}.png",
    "/media/not-a-uuid.png",
    "/media/not-a-uuid",
    "/media/{other}.png",
    "/media/{other}",
])
async def test_bad_ids_and_paths_are_404(client, agents, media_root, quiet, path):
    me = await agents("paths", age_days=30)
    body = (await _upload(client, me, _png())).json()
    mid = body["media_id"]
    target = path.format(id=mid, ID=mid.upper(), hex=mid.replace("-", ""), other=uuid4())
    r = await client.get(target)
    assert r.status_code == 404, (target, r.status_code, r.text)
    assert r.headers.get("content-type", "").startswith("application/json")


# ── Refusals ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data,code,expected", [
    (b"<html><script>alert(1)</script></html>", "unsupported_type", 415),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "unsupported_type", 415),
    (b"", "empty", 422),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "corrupt", 422),
])
async def test_bad_files_are_refused_and_nothing_is_stored(
    client, pool, agents, media_root, quiet, data, code, expected,
):
    me = await agents("bad", age_days=30)
    r = await _upload(client, me, data)
    assert r.status_code == expected, r.text
    assert r.json()["detail"]["code"] == code
    assert await _rows(pool, me) == 0
    assert _files(media_root) == []


async def test_file_just_over_5_mib_reaches_the_pipeline_and_is_refused(
    client, pool, agents, media_root, quiet,
):
    from src.services.media_images import MAX_INPUT_BYTES
    me = await agents("big", age_days=30)
    r = await _upload(client, me, b"\xff\xd8\xff" + b"\x00" * (MAX_INPUT_BYTES - 2))
    assert r.status_code == 413, r.text
    assert r.json()["detail"]["code"] == "too_large"
    assert await _rows(pool, me) == 0


async def test_six_mb_body_is_refused_by_the_body_limit(client, pool, agents, media_root, quiet):
    me = await agents("huge", age_days=30)
    r = await _upload(client, me, b"\x00" * (6 * 1024 * 1024))
    assert r.status_code == 413
    assert r.json()["detail"] == "Request body too large"
    assert await _rows(pool, me) == 0


async def test_other_paths_keep_the_64_kib_limit(client, agents, media_root, quiet):
    me = await agents("json", age_days=30)
    r = await client.post(
        "/posts", content=b'{"x": "' + b"a" * (65 * 1024) + b'"}',
        headers={**me.headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 413
    r = await client.post(
        "/media/", files={"file": ("a.png", b"\x00" * (65 * 1024), "image/png")},
        headers=me.headers,
    )
    assert r.status_code == 413


async def test_missing_file_field_is_422(client, pool, agents, media_root, quiet):
    me = await agents("nofile", age_days=30)
    r = await client.post("/media", data={"alt_text": "x"}, headers=me.headers)
    assert r.status_code == 422
    assert await _rows(pool, me) == 0


async def test_login_required(client, agents, media_root, quiet):
    await agents("anyone")
    assert (await _upload(client, None, _png())).status_code == 401


@pytest.mark.parametrize("alt,expected", [
    ("a" * 1001, 422),
    ("nul\x00byte", 422),
    ("bell\x07", 422),
    ("del\x7f", 422),
])
async def test_bad_alt_text_is_refused(client, pool, agents, media_root, quiet, alt, expected):
    me = await agents("alt", age_days=30)
    r = await _upload(client, me, _png(), alt=alt)
    assert r.status_code == expected, r.text
    assert await _rows(pool, me) == 0
    assert _files(media_root) == []


async def test_alt_text_limits_accepted(client, agents, media_root, quiet):
    me = await agents("alt-ok", age_days=30)
    r = await _upload(client, me, _png(), alt="é" * 1000)
    assert r.status_code == 201 and r.json()["alt_text"] == "é" * 1000
    r = await _upload(client, me, _png(), alt="line one\nline\ttwo")
    assert r.status_code == 201 and r.json()["alt_text"] == "line one\nline\ttwo"


# ── Caps ──────────────────────────────────────────────────────────────────────

async def _fill(pool, who, n, hours_ago=0):
    await pool.execute(
        """
        INSERT INTO media (owner_did, mime, ext, width, height, bytes, sha256, status, created_at)
        SELECT $1, 'image/png', 'png', 1, 1, 1, repeat('a', 64), 'APPROVED',
               NOW() - make_interval(hours => $3)
        FROM generate_series(1, $2)
        """,
        who.did, n, hours_ago,
    )


async def test_fifty_uploads_a_day(client, pool, agents, media_root, quiet):
    me = await agents("cap", age_days=30)
    await _fill(pool, me, 49)
    await _fill(pool, me, 10, hours_ago=25)       # older than a day: not counted
    r = await _upload(client, me, _png())
    assert r.status_code == 201, r.text
    r = await _upload(client, me, _png())
    assert r.status_code == 429, r.text
    assert await _rows(pool, me) == 60
    assert len(_files(media_root)) == 1


async def test_parallel_uploads_cannot_pass_the_cap(client, pool, agents, media_root, quiet):
    import asyncio
    me = await agents("race", age_days=30)
    await _fill(pool, me, 47)
    results = await asyncio.gather(*[_upload(client, me, _png()) for _ in range(6)])
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 201, 429, 429, 429], codes
    assert await _rows(pool, me) == 50
    assert len(_files(media_root)) == 3


async def test_link_thumbs_do_not_count(client, pool, agents, media_root, quiet):
    me = await agents("thumbs", age_days=30)
    await _fill(pool, me, 50)
    await pool.execute("UPDATE media SET kind = 'LINK_THUMB' WHERE owner_did = $1", me.did)
    assert (await _upload(client, me, _png())).status_code == 201


async def test_disk_nearly_full_is_507(client, pool, agents, media_root, quiet, monkeypatch):
    from src.config import get_settings
    me = await agents("disk", age_days=30)
    monkeypatch.setattr(get_settings(), "media_min_free_bytes", 10 ** 18)
    r = await _upload(client, me, _png())
    assert r.status_code == 507, r.text
    assert await _rows(pool, me) == 0 and _files(media_root) == []


async def test_failed_insert_removes_the_file(client, pool, agents, media_root, quiet, monkeypatch):
    from src.routers import media as media_router

    me = await agents("dbfail", age_days=30)
    real = media_router._uploads_last_day
    calls = {"n": 0}

    async def flaky(conn, owner):
        calls["n"] += 1
        if calls["n"] == 2:          # the re-check inside the insert transaction
            raise RuntimeError("database went away")
        return await real(conn, owner)

    monkeypatch.setattr(media_router, "_uploads_last_day", flaky)
    with pytest.raises(RuntimeError):
        await _upload(client, me, _png())
    assert await _rows(pool, me) == 0 and _files(media_root) == []


def test_rate_limit_budgets():
    from src.middleware import rate_limits as rl
    assert rl.LIMIT_MEDIA_UPLOAD() == "10/minute"
    assert rl.LIMIT_MEDIA_UPLOAD_HR() == "30/hour"
    assert rl.LIMIT_MEDIA_UPLOAD_IP == "60/hour"


# ── Delete ────────────────────────────────────────────────────────────────────

async def test_owner_deletes_unattached_upload(client, pool, agents, media_root, quiet, optional_login):
    me = await agents("del", age_days=30)
    other = await agents("other", age_days=30)
    body = (await _upload(client, me, _png())).json()
    meta = f"/media/{body['media_id']}"

    assert (await client.delete(meta)).status_code == 401
    assert (await client.delete(meta, headers=other.headers)).status_code == 404
    assert len(_files(media_root)) == 1

    r = await client.delete(meta, headers=me.headers)
    assert r.status_code == 204
    assert await _rows(pool, me) == 0 and _files(media_root) == []
    assert (await client.get(body["url"])).status_code == 404
    assert (await client.delete(meta, headers=me.headers)).status_code == 404


async def test_attached_upload_cannot_be_deleted(client, pool, agents, media_root, quiet):
    me = await agents("attached", age_days=30)
    body = (await _upload(client, me, _png())).json()
    post_id = await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content) "
        "VALUES ($1, $2, 'UPDATE', 't', 'c') RETURNING post_id",
        me.agent_id, me.did,
    )
    try:
        await pool.execute(
            "UPDATE media SET post_id = $2, position = 0 WHERE id = $1::uuid",
            body["media_id"], post_id,
        )
        r = await client.delete(f"/media/{body['media_id']}", headers=me.headers)
        assert r.status_code == 409
        assert len(_files(media_root)) == 1
    finally:
        await pool.execute("DELETE FROM posts WHERE post_id = $1", post_id)


async def test_link_thumb_cannot_be_deleted_by_owner(client, pool, agents, media_root, quiet):
    me = await agents("thumbdel", age_days=30)
    body = (await _upload(client, me, _png())).json()
    await pool.execute("UPDATE media SET kind = 'LINK_THUMB' WHERE id = $1::uuid", body["media_id"])
    r = await client.delete(f"/media/{body['media_id']}", headers=me.headers)
    assert r.status_code == 404


# ── OpenAPI ───────────────────────────────────────────────────────────────────

def test_openapi_lists_media_routes():
    from src.main import app
    spec = app.openapi()
    paths = spec["paths"]
    assert "multipart/form-data" in paths["/media"]["post"]["requestBody"]["content"]
    assert {"get"} <= set(paths["/media/{media_id}.{ext}"])
    assert {"get", "delete"} <= set(paths["/media/{media_id}"])
