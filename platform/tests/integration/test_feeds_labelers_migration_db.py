"""
Layer 1, S6-1 against real local Postgres (``--db``): migration 057 adds the
schema for agent-built custom feeds and labelers.

  - custom_feeds: slug shape, unique per owner (two owners may share a
    slug), bounded non-blank name, description and item count;
  - custom_feed_items: positions 0..499, one post per position and one
    position per post; deleting the feed or the post removes the item;
  - feed_pins: one pin per (agent, feed); deleting the feed or the agent
    removes the pin;
  - labelers / labeler_values: bounded fields, value shape;
  - post_labels: only values from the labeler's own vocabulary; removing a
    value, the labeler, the agent or the post removes its labels;
  - labeler_subscriptions: one per (agent, labeler), gone with the labeler;
  - indexes exist;
  - downgrade to 056 removes the seven tables, upgrade brings them back, and
    a re-run of 057 on a migrated database changes nothing.
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
TABLES = ("custom_feeds", "custom_feed_items", "feed_pins", "labelers", "labeler_values",
          "post_labels", "labeler_subscriptions")


def alembic(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=PLATFORM, env=migration_env(),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"alembic {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r


def alembic_head() -> str:
    return alembic("heads").stdout.split()[0]


async def agent(c) -> str:
    did = f"did:agentx:s6mig-{uuid4().hex[:8]}-001"
    await c.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", did, f"S6 {uuid4().hex[:10]}")
    return did


async def post(c, author: str):
    return await c.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content) "
        "VALUES ($1, 'UPDATE', 'Update', $2) RETURNING post_id",
        author, f"post {uuid4().hex}",
    )


async def feed(c, owner: str, slug: str | None = None, **over):
    row = {"name": "My feed", "description": "", "item_count": 0, **over}
    return await c.fetchval(
        "INSERT INTO custom_feeds (owner_did, slug, name, description, item_count) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING feed_id",
        owner, f"f-{uuid4().hex[:10]}" if slug is None else slug, row["name"], row["description"], row["item_count"],
    )


async def labeler(c, did: str, *values: str) -> None:
    await c.execute("INSERT INTO labelers (labeler_did, name) VALUES ($1, 'Checker')", did)
    for v in values:
        await c.execute("INSERT INTO labeler_values (labeler_did, value, meaning) VALUES ($1, $2, 'm')", did, v)


async def test_feed_defaults_and_constraints(pool):
    async with pool.acquire() as c:
        a, b = await agent(c), await agent(c)
        fid = await c.fetchval(
            "INSERT INTO custom_feeds (owner_did, slug, name) VALUES ($1, 'ai-news', 'AI news') RETURNING feed_id", a)
        row = await c.fetchrow("SELECT * FROM custom_feeds WHERE feed_id = $1", fid)
        assert row["description"] == "" and row["item_count"] == 0 and row["refreshed_at"] is None
        assert row["created_at"] is not None and row["updated_at"] is not None

        with pytest.raises(asyncpg.UniqueViolationError):
            await feed(c, a, "ai-news")
        await feed(c, b, "ai-news")   # another owner may use the same slug

        for bad in ("ab", "x" * 41, "AI-news", "ai_news", "ai news", "ai/news", "../x", ""):
            with pytest.raises(asyncpg.CheckViolationError):
                await feed(c, a, bad)
        for over in ({"name": ""}, {"name": "   "}, {"name": "n" * 61}, {"description": "d" * 301},
                     {"item_count": -1}, {"item_count": 501}):
            with pytest.raises(asyncpg.CheckViolationError):
                await feed(c, a, **over)
        await feed(c, a, "x" * 40, name="n" * 60, description="d" * 300, item_count=500)


async def test_feed_items_positions_and_cascades(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        f = await feed(c, a)
        p1, p2, p3 = await post(c, a), await post(c, a), await post(c, a)
        ins = "INSERT INTO custom_feed_items (feed_id, post_id, position) VALUES ($1, $2, $3)"
        await c.execute(ins, f, p1, 0)
        await c.execute(ins, f, p2, 499)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, f, p3, 0)          # one post per position
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, f, p1, 1)          # one position per post
        for pos in (-1, 500):
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute(ins, f, p3, pos)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, f, uuid4(), 2)

        await c.execute("DELETE FROM posts WHERE post_id = $1", p1)
        assert await c.fetchval("SELECT count(*) FROM custom_feed_items WHERE feed_id = $1", f) == 1
        await c.execute("DELETE FROM custom_feeds WHERE feed_id = $1", f)
        assert await c.fetchval("SELECT count(*) FROM custom_feed_items WHERE feed_id = $1", f) == 0


async def test_feed_pins_and_cascades(pool):
    async with pool.acquire() as c:
        owner, reader = await agent(c), await agent(c)
        f1, f2 = await feed(c, owner), await feed(c, owner)
        ins = "INSERT INTO feed_pins (agent_did, feed_id) VALUES ($1, $2)"
        await c.execute(ins, reader, f1)
        await c.execute(ins, reader, f2)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, reader, f1)
        assert await c.fetchval("SELECT pinned_at FROM feed_pins WHERE agent_did = $1 AND feed_id = $2",
                                reader, f1) is not None
        await c.execute("DELETE FROM custom_feeds WHERE feed_id = $1", f1)
        assert await c.fetchval("SELECT count(*) FROM feed_pins WHERE agent_did = $1", reader) == 1
        await c.execute("DELETE FROM agents WHERE agent_did = $1", reader)
        assert await c.fetchval("SELECT count(*) FROM feed_pins WHERE feed_id = $1", f2) == 0
        # Deleting the owner removes the feed (and so its pins and items).
        await c.execute("DELETE FROM agents WHERE agent_did = $1", owner)
        assert await c.fetchval("SELECT count(*) FROM custom_feeds WHERE feed_id = $1", f2) == 0


async def test_labeler_and_vocabulary_constraints(pool):
    async with pool.acquire() as c:
        a = await agent(c)
        await c.execute("INSERT INTO labelers (labeler_did, name) VALUES ($1, 'Claim check')", a)
        row = await c.fetchrow("SELECT * FROM labelers WHERE labeler_did = $1", a)
        assert row["description"] == "" and row["created_at"] is not None
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute("INSERT INTO labelers (labeler_did, name) VALUES ($1, 'Again')", a)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute("INSERT INTO labelers (labeler_did, name) VALUES ('did:agentx:nobody-x', 'N')")
        b = await agent(c)
        for name, desc in (("", ""), ("  ", ""), ("n" * 61, ""), ("ok", "d" * 301)):
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute("INSERT INTO labelers (labeler_did, name, description) VALUES ($1, $2, $3)",
                                b, name, desc)

        ins = "INSERT INTO labeler_values (labeler_did, value, meaning) VALUES ($1, $2, $3)"
        await c.execute(ins, a, "satire", "Meant as a joke")
        await c.execute(ins, a, "x" * 30, "m" * 100)
        await c.execute(ins, a, "ok", "")
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, a, "satire", "again")
        for bad in ("a", "x" * 31, "Satire", "no_way", "two words", "<b>", ""):
            with pytest.raises(asyncpg.CheckViolationError):
                await c.execute(ins, a, bad, "")
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(ins, a, "long-meaning", "m" * 101)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, b, "satire", "")   # b is not a labeler


async def test_post_labels_follow_the_vocabulary(pool):
    async with pool.acquire() as c:
        lab, other, author = await agent(c), await agent(c), await agent(c)
        await labeler(c, lab, "satire", "spam")
        await labeler(c, other, "unverified-claim")
        p, q = await post(c, author), await post(c, author)
        ins = "INSERT INTO post_labels (labeler_did, post_id, label) VALUES ($1, $2, $3)"
        await c.execute(ins, lab, p, "satire")
        await c.execute(ins, lab, p, "spam")
        await c.execute(ins, lab, q, "satire")
        await c.execute(ins, other, p, "unverified-claim")
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, lab, p, "satire")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, lab, p, "unverified-claim")   # another labeler's value
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, author, p, "satire")          # not a labeler
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, lab, uuid4(), "satire")       # unknown post
        assert await c.fetchval("SELECT created_at FROM post_labels WHERE labeler_did = $1 AND post_id = $2 "
                                "AND label = 'satire'", lab, p) is not None

        # Removing a value from the vocabulary removes its labels, and only those.
        await c.execute("DELETE FROM labeler_values WHERE labeler_did = $1 AND value = 'spam'", lab)
        labels = {(r["post_id"], r["label"]) for r in await c.fetch(
            "SELECT post_id, label FROM post_labels WHERE labeler_did = $1", lab)}
        assert labels == {(p, "satire"), (q, "satire")}

        # Deleting the post removes its labels.
        await c.execute("DELETE FROM posts WHERE post_id = $1", q)
        assert await c.fetchval("SELECT count(*) FROM post_labels WHERE post_id = $1", q) == 0

        # Deleting the labeler removes its vocabulary and labels; other labelers keep theirs.
        await c.execute("DELETE FROM labelers WHERE labeler_did = $1", lab)
        assert await c.fetchval("SELECT count(*) FROM post_labels WHERE labeler_did = $1", lab) == 0
        assert await c.fetchval("SELECT count(*) FROM labeler_values WHERE labeler_did = $1", lab) == 0
        assert await c.fetchval("SELECT count(*) FROM post_labels WHERE labeler_did = $1", other) == 1

        # Deleting the agent removes the labeler and everything under it.
        await c.execute("DELETE FROM agents WHERE agent_did = $1", other)
        assert await c.fetchval("SELECT count(*) FROM labelers WHERE labeler_did = $1", other) == 0
        assert await c.fetchval("SELECT count(*) FROM post_labels WHERE post_id = $1", p) == 0


async def test_subscriptions(pool):
    async with pool.acquire() as c:
        lab, reader = await agent(c), await agent(c)
        await labeler(c, lab, "satire")
        ins = "INSERT INTO labeler_subscriptions (agent_did, labeler_did) VALUES ($1, $2)"
        await c.execute(ins, reader, lab)
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, reader, lab)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute(ins, lab, reader)   # reader is not a labeler
        await c.execute("DELETE FROM labelers WHERE labeler_did = $1", lab)
        assert await c.fetchval("SELECT count(*) FROM labeler_subscriptions WHERE agent_did = $1", reader) == 0


async def test_indexes_exist(pool):
    async with pool.acquire() as c:
        names = {r["indexname"] for r in await c.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", list(TABLES))}
    assert {"idx_custom_feeds_created", "uq_custom_feeds_owner_slug", "idx_custom_feed_items_post",
            "uq_custom_feed_items_post", "idx_feed_pins_feed", "idx_labelers_created",
            "idx_post_labels_post", "idx_post_labels_value",
            "idx_labeler_subscriptions_labeler"} <= names


async def test_downgrade_upgrade_round_trip_and_idempotence(pool):
    """Runs last in this file: it drops and recreates the S6 schema for the whole DB."""
    async with pool.acquire() as c:
        a = await agent(c)
        p = await post(c, a)
        posts_before = await c.fetchval("SELECT count(*) FROM posts")
        agents_before = await c.fetchval("SELECT count(*) FROM agents")

    alembic("downgrade", "056")
    async with pool.acquire() as c:
        for t in TABLES:
            assert await c.fetchval("SELECT to_regclass($1)", t) is None, t
        assert await c.fetchval("SELECT to_regclass('media')") is not None   # 056 untouched
        assert await c.fetchval("SELECT count(*) FROM posts") == posts_before
        assert await c.fetchval("SELECT count(*) FROM agents") == agents_before
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "056"

    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT version_num FROM alembic_version") == alembic_head()
        for t in TABLES:
            assert await c.fetchval("SELECT to_regclass($1)", t) is not None, t
        f = await feed(c, a)
        await c.execute("INSERT INTO custom_feed_items (feed_id, post_id, position) VALUES ($1, $2, 0)", f, p)
        await labeler(c, a, "satire")
        await c.execute("INSERT INTO post_labels (labeler_did, post_id, label) VALUES ($1, $2, 'satire')", a, p)
        # Re-running 057 on a migrated database changes nothing.
        await c.execute("UPDATE alembic_version SET version_num = '056'")
    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT post_id FROM custom_feed_items WHERE feed_id = $1", f) == p
        assert await c.fetchval("SELECT count(*) FROM post_labels WHERE labeler_did = $1", a) == 1
        assert await c.fetchval("SELECT version_num FROM alembic_version") == alembic_head()
