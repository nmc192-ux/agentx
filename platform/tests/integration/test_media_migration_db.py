"""
Layer 1, S4-1 against real local Postgres (``--db``): migration 056 adds the
schema for images on posts and link cards.

  - media: only the four image types, sizes within the limits, a well-formed
    sha256, alt text ≤ 1000, known kind and status; deleting the agent removes
    their media, deleting the post detaches it (the cleanup job owns files);
  - one image per (post, position), positions 0..3 only;
  - link_cards: well-formed key, bounded fields; deleting a card clears the
    post's link and deleting the thumbnail clears the card's image;
  - indexes for the queue, the cleanup job and the per-agent cap exist;
  - downgrade to 055 removes the tables and column, upgrade brings them back,
    and a re-run of 056 on a migrated database changes nothing.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from .conftest import migration_env

pytestmark = pytest.mark.integration

PLATFORM = Path(__file__).resolve().parents[2]
SHA = "a" * 64


def alembic(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=PLATFORM, env=migration_env(),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"alembic {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r


def alembic_head() -> str:
    return alembic("heads").stdout.split()[0]


async def agent(c) -> str:
    did = f"did:agentx:media-{uuid4().hex[:8]}-001"
    await c.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", did, f"Media {uuid4().hex[:10]}")
    return did


async def post(c, author: str):
    return await c.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content) "
        "VALUES ($1, 'UPDATE', 'Update', $2) RETURNING post_id",
        author, f"post {uuid4().hex}",
    )


async def media(c, owner: str, **over):
    row = {"mime": "image/png", "ext": "png", "width": 640, "height": 480, "bytes": 1234,
           "sha256": SHA, "alt_text": "", "kind": "UPLOAD", "status": "PENDING",
           "post_id": None, "position": None}
    row.update(over)
    return await c.fetchval(
        "INSERT INTO media (owner_did, mime, ext, width, height, bytes, sha256, alt_text, kind, status, "
        "post_id, position) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id",
        owner, row["mime"], row["ext"], row["width"], row["height"], row["bytes"], row["sha256"],
        row["alt_text"], row["kind"], row["status"], row["post_id"], row["position"],
    )


async def test_media_defaults(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        mid = await c.fetchval(
            "INSERT INTO media (owner_did, mime, ext, width, height, bytes, sha256) "
            "VALUES ($1, 'image/jpeg', 'jpg', 10, 10, 10, $2) RETURNING id", a, SHA)
        row = await c.fetchrow("SELECT * FROM media WHERE id = $1", mid)
    assert row["kind"] == "UPLOAD" and row["status"] == "PENDING" and row["alt_text"] == ""
    assert row["post_id"] is None and row["position"] is None and row["created_at"] is not None


@pytest.mark.parametrize("over", [
    {"mime": "image/svg+xml"}, {"mime": "text/html"}, {"ext": "svg"}, {"ext": "png.html"},
    {"width": 0}, {"width": 2049}, {"height": 0}, {"height": 4096},
    {"bytes": 0}, {"bytes": 5 * 1024 * 1024 + 1},
    {"sha256": "A" * 64}, {"sha256": "a" * 63}, {"sha256": "../../etc/passwd"},
    {"alt_text": "x" * 1001}, {"kind": "AVATAR"}, {"status": "OK"}, {"position": 4}, {"position": -1},
])
async def test_media_constraints_refuse_bad_rows(pool, over):
    async with pool.acquire() as c:
        a = await agent(c)
        with pytest.raises(asyncpg.CheckViolationError):
            await media(c, a, **over)


async def test_media_limits_accepted(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        await media(c, a, width=2048, height=2048, bytes=5 * 1024 * 1024, alt_text="x" * 1000,
                    mime="image/gif", ext="gif", kind="LINK_THUMB", status="APPROVED")


async def test_media_owner_cascade_and_post_set_null(pool):
    async with pool.acquire() as c:
        a, b = await agent(c), await agent(c)
        p = await post(c, a)
        m = await media(c, a, post_id=p, position=0, status="APPROVED")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await media(c, a, post_id=uuid4(), position=0)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await media(c, "did:agentx:nobody-ffffffff-001")

        # reviewed_by is cleared, not cascaded, when the moderator goes.
        await c.execute("UPDATE media SET reviewed_by = $1, reviewed_at = NOW() WHERE id = $2", b, m)
        await c.execute("DELETE FROM agents WHERE agent_did = $1", b)
        assert await c.fetchval("SELECT reviewed_by FROM media WHERE id = $1", m) is None

        await c.execute("DELETE FROM posts WHERE post_id = $1", p)
        row = await c.fetchrow("SELECT post_id, status FROM media WHERE id = $1", m)
        assert row is not None and row["post_id"] is None   # detached, file left to cleanup

        await c.execute("DELETE FROM agents WHERE agent_did = $1", a)
        assert await c.fetchval("SELECT count(*) FROM media WHERE id = $1", m) == 0


async def test_one_image_per_slot(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        p = await post(c, a)
        for pos in range(4):
            await media(c, a, post_id=p, position=pos)
        with pytest.raises(asyncpg.UniqueViolationError):
            await media(c, a, post_id=p, position=2)
        # Unattached media has no slot and any number may exist.
        await media(c, a)
        await media(c, a)


async def test_link_cards(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        key = hashlib.sha256(b"https://example.com/").hexdigest()
        thumb = await media(c, a, kind="LINK_THUMB", status="APPROVED")
        await c.execute(
            "INSERT INTO link_cards (url_key, url, title, description, site_name, thumb_media_id, status) "
            "VALUES ($1, 'https://example.com/', 'Example', 'An example', 'example.com', $2, 'OK')", key, thumb)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute("INSERT INTO link_cards (url_key, url, status) VALUES ($1, 'x', 'FAILED')", key)
        for bad in ({"url_key": "nothex"}, {"status": "PENDING"}, {"title": "t" * 201},
                    {"description": "d" * 501}, {"site_name": "s" * 201}, {"url": "u" * 2049}):
            vals = {"url_key": uuid4().hex * 2, "url": "https://e.com/", "title": None,
                    "description": None, "site_name": None, "status": "OK", **bad}
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute(
                    "INSERT INTO link_cards (url_key, url, title, description, site_name, status) "
                    "VALUES ($1,$2,$3,$4,$5,$6)", vals["url_key"], vals["url"], vals["title"],
                    vals["description"], vals["site_name"], vals["status"])

        p = await post(c, a)
        await c.execute("UPDATE posts SET link_url_key = $1 WHERE post_id = $2", key, p)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute("UPDATE posts SET link_url_key = $1 WHERE post_id = $2", "b" * 64, p)

        await c.execute("DELETE FROM media WHERE id = $1", thumb)
        assert await c.fetchval("SELECT thumb_media_id FROM link_cards WHERE url_key = $1", key) is None
        await c.execute("DELETE FROM link_cards WHERE url_key = $1", key)
        row = await c.fetchrow("SELECT post_id, link_url_key FROM posts WHERE post_id = $1", p)
        assert row is not None and row["link_url_key"] is None


async def test_indexes_exist(pool):
    async with pool.acquire() as c:
        names = {r["indexname"] for r in await c.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('media', 'posts')")}
    assert {"idx_media_owner_created", "idx_media_pending", "idx_media_unattached", "idx_media_post",
            "idx_posts_link_url_key"} <= names


async def test_downgrade_upgrade_round_trip_and_idempotence(pool):
    """Runs last in this file: it drops and recreates the S4 schema for the whole DB."""
    async with pool.acquire() as c:
        a = await agent(c)
        p = await post(c, a)
        posts_before = await c.fetchval("SELECT count(*) FROM posts")

    alembic("downgrade", "055")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT to_regclass('media')") is None
        assert await c.fetchval("SELECT to_regclass('link_cards')") is None
        cols = {r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'posts'")}
        assert "link_url_key" not in cols
        assert await c.fetchval("SELECT count(*) FROM posts") == posts_before   # posts untouched
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "055"

    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT version_num FROM alembic_version") == alembic_head()
        assert await c.fetchval("SELECT to_regclass('media')") is not None
        assert await c.fetchval("SELECT to_regclass('link_cards')") is not None
        m = await media(c, a, post_id=p, position=0)
        # Re-running 056 on a migrated database changes nothing.
        await c.execute("UPDATE alembic_version SET version_num = '055'")
    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT post_id FROM media WHERE id = $1", m) == p
        assert await c.fetchval("SELECT version_num FROM alembic_version") == alembic_head()
