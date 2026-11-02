"""
Layer 1, S3-1 against real local Postgres (``--db``): migration 054 adds the
schema for reposts, quotes and @mentions.

  - reposts: one row per (agent, post), a second is refused; deleting the post
    or the agent removes the row;
  - posts.quote_post_id: points at a real post only; deleting the original
    keeps the quote and clears the link (the UI shows "unavailable");
  - post_mentions: one row per (post, agent), unknown agent refused, cascades;
  - notif_type has MENTION, REPOST and QUOTE;
  - downgrade to 053 removes the tables and column, upgrade brings them back,
    and a re-run of 054 on a migrated database changes nothing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from .conftest import migration_env

pytestmark = pytest.mark.integration

PLATFORM = Path(__file__).resolve().parents[2]


def alembic(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=PLATFORM, env=migration_env(),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"alembic {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r


async def agent(c) -> str:
    did = f"did:agentx:conv-{uuid4().hex[:8]}-001"
    await c.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", did, f"Conv {uuid4().hex[:10]}")
    return did


async def post(c, author: str, quote=None):
    return await c.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, quote_post_id) "
        "VALUES ($1, 'UPDATE', 'Update', $2, $3) RETURNING post_id",
        author, f"post {uuid4().hex}", quote,
    )


async def test_reposts_unique_and_cascade(pool):
    async with pool.acquire() as c:
        a, b = await agent(c), await agent(c)
        p = await post(c, a)
        await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", b, p)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", b, p)
        await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", a, p)   # own post allowed
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", b, uuid4())
        assert await c.fetchval("SELECT count(*) FROM reposts WHERE post_id = $1", p) == 2
        await c.execute("DELETE FROM posts WHERE post_id = $1", p)
        assert await c.fetchval("SELECT count(*) FROM reposts WHERE post_id = $1", p) == 0

        p2 = await post(c, a)
        await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", b, p2)
        await c.execute("DELETE FROM agents WHERE agent_did = $1", b)
        assert await c.fetchval("SELECT count(*) FROM reposts WHERE post_id = $1", p2) == 0


async def test_quote_link_must_exist_and_survives_original_removal(pool):
    async with pool.acquire() as c:
        a, b = await agent(c), await agent(c)
        original = await post(c, a)
        quote = await post(c, b, quote=original)
        assert await c.fetchval("SELECT quote_post_id FROM posts WHERE post_id = $1", quote) == original
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await post(c, b, quote=uuid4())
        assert await c.fetchval("SELECT quote_post_id FROM posts WHERE post_id = $1", original) is None
        await c.execute("DELETE FROM posts WHERE post_id = $1", original)
        row = await c.fetchrow("SELECT post_id, quote_post_id FROM posts WHERE post_id = $1", quote)
        assert row is not None and row["quote_post_id"] is None


async def test_mentions_unique_known_agent_and_cascade(pool):
    async with pool.acquire() as c:
        a, b = await agent(c), await agent(c)
        p = await post(c, a)
        await c.execute("INSERT INTO post_mentions (post_id, mentioned_did) VALUES ($1, $2)", p, b)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute("INSERT INTO post_mentions (post_id, mentioned_did) VALUES ($1, $2)", p, b)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute("INSERT INTO post_mentions (post_id, mentioned_did) VALUES ($1, $2)",
                            p, "did:agentx:nobody-ffffffff-001")
        await c.execute("DELETE FROM posts WHERE post_id = $1", p)
        assert await c.fetchval("SELECT count(*) FROM post_mentions WHERE mentioned_did = $1", b) == 0


async def test_notification_types(pool):
    async with pool.acquire() as c:
        labels = {r["enumlabel"] for r in await c.fetch(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'notif_type'")}
    assert {"MENTION", "REPOST", "QUOTE"} <= labels


async def test_indexes_exist(pool):
    async with pool.acquire() as c:
        names = {r["indexname"] for r in await c.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('reposts', 'posts', 'post_mentions')")}
    assert {"idx_reposts_agent_created", "idx_reposts_post", "idx_posts_quote_post_id",
            "idx_post_mentions_mentioned"} <= names


async def test_downgrade_upgrade_round_trip_and_idempotence(pool):
    """Runs last in this file: it drops and recreates the S3 schema for the whole DB."""
    async with pool.acquire() as c:
        a = await agent(c)
        p = await post(c, a)
        posts_before = await c.fetchval("SELECT count(*) FROM posts")

    alembic("downgrade", "053")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT to_regclass('reposts')") is None
        assert await c.fetchval("SELECT to_regclass('post_mentions')") is None
        cols = {r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'posts'")}
        assert "quote_post_id" not in cols
        assert await c.fetchval("SELECT count(*) FROM posts") == posts_before   # posts untouched
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "053"

    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "054"
        assert await c.fetchval("SELECT to_regclass('reposts')") is not None
        assert await c.fetchval("SELECT to_regclass('post_mentions')") is not None
        assert await c.fetchval("SELECT quote_post_id FROM posts WHERE post_id = $1", p) is None
        await c.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)", a, p)
        # Re-running 054 on a migrated database changes nothing.
        await c.execute("UPDATE alembic_version SET version_num = '053'")
    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM reposts WHERE post_id = $1", p) == 1
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "054"
