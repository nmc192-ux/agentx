"""
Layer 1 S4-8: the media cleanup job on real Postgres with a temp MEDIA_ROOT.

Deleted: unattached uploads after 24 h (row and file), link cards no post
has used for 30 days, link thumbnails no card shows, files with no row (or
the wrong extension), files of REJECTED rows (row kept), old temp files.
Kept: anything on a post, anything a card shows, anything under the grace
periods, the "no link" marker card, files we did not name.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_media_cleanup_db.py -v --db
"""
import hashlib
import io
import os
import time
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from PIL import Image

from src.jobs import media_cleanup as mc
from src.services import media_store
from src.services.link_cards import NO_LINK_KEY

pytestmark = pytest.mark.integration   # skipped unless --db is given


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
    monkeypatch.setattr(settings, "link_cards_enabled", "false")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_min_free_bytes", 0)
    yield tmp_path


def _png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


async def _upload(client, who) -> UUID:
    r = await client.post("/media", files={"file": ("p.png", _png(), "image/png")},
                          data={"alt_text": "pic"}, headers=who.headers)
    assert r.status_code == 201, r.text
    return UUID(r.json()["media_id"])


async def _create(client, who, media_ids=(), content="Hello"):
    r = await client.post("/posts", json={
        "post_type": "UPDATE", "title": "Pictures", "content": content,
        "media_ids": [str(m) for m in media_ids],
    }, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()["post_id"]


async def _thumb(pool, root, owner) -> UUID:
    data = _png((10, 200, 10))
    media_id = uuid4()
    media_store.write(root, media_id, "png", data)
    await pool.execute(
        """INSERT INTO media (id, owner_did, kind, mime, ext, width, height, bytes, sha256, status)
           VALUES ($1, $2, 'LINK_THUMB', 'image/png', 'png', 40, 30, $3, $4, 'APPROVED')""",
        media_id, owner.did, len(data), hashlib.sha256(data).hexdigest())
    return media_id


async def _card(pool, thumb=None, days_old=0) -> str:
    key = hashlib.sha256(uuid4().bytes).hexdigest()
    await pool.execute(
        """INSERT INTO link_cards (url_key, url, title, thumb_media_id, status, fetched_at)
           VALUES ($1, 'https://example.com/', 'T', $2, 'OK', NOW() - make_interval(days => $3))""",
        key, thumb, days_old)
    return key


async def _age_row(pool, media_id, hours):
    await pool.execute("UPDATE media SET created_at = NOW() - make_interval(hours => $2) "
                       "WHERE id = $1", media_id, hours)


def _path(root, media_id, ext="png"):
    return media_store.path_for(root, media_id, ext)


def _age_file(path, seconds=2 * 3600):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _age_all_files(root):
    for p in root.rglob("*"):
        if p.is_file():
            _age_file(p)


async def _exists(pool, media_id) -> bool:
    return await pool.fetchval("SELECT EXISTS (SELECT 1 FROM media WHERE id = $1)", media_id)


# ── Unattached uploads ────────────────────────────────────────────────────────

async def test_unattached_uploads_go_after_a_day_posted_ones_stay(
    client, pool, agents, media_on, quiet,
):
    me = await agents("cleaner", age_days=30)
    newbie = await agents("newbie", age_days=1)
    old_loose = await _upload(client, me)
    young_loose = await _upload(client, me)
    on_post = await _upload(client, me)
    pending_on_post = await _upload(client, newbie)
    pending_loose = await _upload(client, newbie)
    await _create(client, me, [on_post])
    await _create(client, newbie, [pending_on_post])
    for m in (old_loose, on_post, pending_on_post, pending_loose):
        await _age_row(pool, m, 25)
    await _age_row(pool, young_loose, 23)

    summary = await mc.run_media_cleanup()
    assert summary.get("skipped") is None
    for gone in (old_loose, pending_loose):
        assert not await _exists(pool, gone)
        assert not _path(media_on, gone).exists()
    for kept in (young_loose, on_post, pending_on_post):
        assert await _exists(pool, kept)
        assert _path(media_on, kept).exists()
    assert summary["unattached"] >= 2 and summary["files_deleted"] >= 2

    r = await client.post("/posts", json={
        "post_type": "UPDATE", "title": "x", "content": "x", "media_ids": [str(old_loose)],
    }, headers=me.headers)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "media_not_found"


async def test_upload_being_attached_is_skipped_then_removed(client, pool, agents, media_on, quiet):
    me = await agents("locker", age_days=30)
    m = await _upload(client, me)
    await _age_row(pool, m, 30)
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        await conn.execute("SELECT 1 FROM media WHERE id = $1 FOR UPDATE", m)
        await mc.run_media_cleanup()          # does not wait for the lock
        assert await _exists(pool, m) and _path(media_on, m).exists()
        await tx.rollback()
    await mc.run_media_cleanup()
    assert not await _exists(pool, m) and not _path(media_on, m).exists()


async def test_post_deleted_image_is_unattached_and_cleaned(client, pool, agents, media_on, quiet):
    me = await agents("deleter", age_days=30)
    m = await _upload(client, me)
    pid = await _create(client, me, [m])
    await pool.execute("UPDATE media SET post_id = NULL, position = NULL WHERE id = $1", m)
    await _age_row(pool, m, 48)
    await mc.run_media_cleanup()
    assert not await _exists(pool, m)
    assert pid


# ── Link cards and thumbnails ─────────────────────────────────────────────────

async def test_thumbnails_kept_while_a_card_shows_them(client, pool, agents, media_on, quiet):
    me = await agents("linker", age_days=30)
    shown = await _thumb(pool, media_on, me)
    unused_old = await _thumb(pool, media_on, me)
    unused_young = await _thumb(pool, media_on, me)
    await _card(pool, shown)
    for m in (shown, unused_old):
        await _age_row(pool, m, 24 * 40)
    await _age_row(pool, unused_young, 2)

    summary = await mc.run_media_cleanup()
    assert await _exists(pool, shown) and _path(media_on, shown).exists()
    assert await _exists(pool, unused_young) and _path(media_on, unused_young).exists()
    assert not await _exists(pool, unused_old) and not _path(media_on, unused_old).exists()
    assert summary["unused_thumbs"] >= 1


async def test_old_unused_card_goes_with_its_thumbnail(client, pool, agents, media_on, quiet):
    me = await agents("carder", age_days=30)
    t_unused = await _thumb(pool, media_on, me)
    t_used = await _thumb(pool, media_on, me)
    t_young = await _thumb(pool, media_on, me)
    for m in (t_unused, t_used, t_young):
        await _age_row(pool, m, 24 * 40)
    unused = await _card(pool, t_unused, days_old=31)
    used = await _card(pool, t_used, days_old=31)
    young = await _card(pool, t_young, days_old=29)
    pid = await _create(client, me, content="see https://example.com/")
    await pool.execute("UPDATE posts SET link_url_key = $1 WHERE post_id = $2::uuid", used, pid)

    await pool.execute("UPDATE link_cards SET fetched_at = NOW() - interval '400 days' "
                       "WHERE url_key = $1", NO_LINK_KEY)
    await pool.execute("INSERT INTO link_cards (url_key, url, status, fetched_at) "
                       "VALUES ($1, '', 'FAILED', NOW() - interval '400 days') "
                       "ON CONFLICT (url_key) DO NOTHING", NO_LINK_KEY)

    summary = await mc.run_media_cleanup()
    keys = {r["url_key"] for r in await pool.fetch("SELECT url_key FROM link_cards")}
    assert unused not in keys
    assert {used, young, NO_LINK_KEY} <= keys
    assert not await _exists(pool, t_unused) and not _path(media_on, t_unused).exists()
    for m in (t_used, t_young):
        assert await _exists(pool, m) and _path(media_on, m).exists()
    assert summary["old_cards"] >= 1
    r = await client.get(f"/posts/{pid}")
    assert r.status_code == 200


# ── Disk sweep ────────────────────────────────────────────────────────────────

async def test_sweep_removes_orphans_rejected_and_temp_files(client, pool, agents, media_on, quiet):
    me = await agents("sweeper", age_days=30)
    keep = await _upload(client, me)
    await _create(client, me, [keep])
    rejected = await _upload(client, me)
    await _create(client, me, [rejected], content="Second")
    # A reject whose file delete failed: row REJECTED, file still on disk.
    await pool.execute("UPDATE media SET status = 'REJECTED' WHERE id = $1", rejected)

    orphan = uuid4()
    media_store.write(media_on, orphan, "webp", b"no row")
    young_orphan = uuid4()
    media_store.write(media_on, young_orphan, "gif", b"just written")
    wrong_ext = media_store.path_for(media_on, keep, "jpg")
    wrong_ext.write_bytes(b"other ext")
    tmp = _path(media_on, keep).parent / ".upload-zzz.tmp"
    tmp.write_bytes(b"half")
    stranger = media_on / "README"
    stranger.write_text("not ours")
    _age_all_files(media_on)
    os.utime(_path(media_on, young_orphan, "gif"))          # now: under an hour

    summary = await mc.run_media_cleanup()
    assert _path(media_on, keep).exists()
    assert not _path(media_on, rejected).exists()
    assert await pool.fetchval("SELECT status FROM media WHERE id = $1", rejected) == "REJECTED"
    assert not _path(media_on, orphan, "webp").exists()
    assert _path(media_on, young_orphan, "gif").exists()
    assert not wrong_ext.exists()
    assert not tmp.exists()
    assert stranger.exists()
    assert summary["orphan_files"] == 2
    assert summary["rejected_files"] == 1
    assert summary["temp_files"] == 1
    assert summary["files_checked"] == 4   # keep, rejected, orphan, wrong_ext

    r = await client.get(f"/media/{keep}.png")
    assert r.status_code == 200


async def test_young_upload_file_before_its_row_is_safe(pool, agents, media_on):
    """An upload writes the file, then the row: the sweep must not race it."""
    m = uuid4()
    media_store.write(media_on, m, "png", b"row coming")
    summary = await mc.run_media_cleanup()
    assert _path(media_on, m).exists()
    assert summary["orphan_files"] == 0


async def test_many_files_are_checked_in_batches(pool, agents, media_on, monkeypatch):
    monkeypatch.setattr(mc, "BATCH", 3)
    ids = [uuid4() for _ in range(8)]
    for m in ids:
        media_store.write(media_on, m, "png", b"x")
    _age_all_files(media_on)
    summary = await mc.run_media_cleanup()
    assert summary["orphan_files"] == 8 and summary["files_checked"] == 8
    assert not any(_path(media_on, m).exists() for m in ids)


# ── Switch and scheduler ──────────────────────────────────────────────────────

async def test_switched_off_deletes_nothing(client, pool, agents, media_on, quiet, monkeypatch):
    from src.config import get_settings
    me = await agents("offswitch", age_days=30)
    m = await _upload(client, me)
    await _age_row(pool, m, 48)
    orphan = uuid4()
    media_store.write(media_on, orphan, "png", b"x")
    _age_all_files(media_on)
    monkeypatch.setattr(get_settings(), "media_enabled", "false")
    summary = await mc.run_media_cleanup()
    assert summary["skipped"] == "disabled"
    assert await _exists(pool, m) and _path(media_on, m).exists()
    assert _path(media_on, orphan).exists()


async def test_missing_root_deletes_no_rows(client, pool, agents, media_on, quiet, monkeypatch):
    from src.config import get_settings
    me = await agents("noroot", age_days=30)
    m = await _upload(client, me)
    await _age_row(pool, m, 48)
    monkeypatch.setattr(get_settings(), "media_root", str(media_on / "not-mounted"))
    summary = await mc.run_media_cleanup()
    assert summary["skipped"] == "no_media_root"
    assert await _exists(pool, m)


async def test_scheduler_records_the_run(pool, media_on):
    import json
    from src.jobs import scheduler as sch
    job = next(j for j in sch.JOBS if j.name == "media_cleanup")
    await pool.execute("DELETE FROM scheduler_job_runs WHERE job_name = 'media_cleanup'")
    assert await sch.run_job_once(job) == "ok"
    row = await pool.fetchrow("SELECT last_status, last_summary FROM scheduler_job_runs "
                              "WHERE job_name = 'media_cleanup'")
    assert row["last_status"] == "ok"
    data = row["last_summary"] if isinstance(row["last_summary"], dict) else json.loads(row["last_summary"])
    assert "files_checked" in data and "skipped" not in data
    assert await sch.run_job_once(job) == "recent"
