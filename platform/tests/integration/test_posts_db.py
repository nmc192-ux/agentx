"""
Integration tests: post anti-abuse rules against REAL local Postgres.
Sprint 9, S9-8a.

What is proven:
  • the same author posting the same content again within 24 h → 409, even
    with different case and spacing; nothing extra is stored
  • the same text from another author, or as a reply under a different
    parent, is still allowed
  • the legacy ``{agent_id, type, topic, ...}`` body posts only as the caller

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def quiet(monkeypatch):
    """Redis cache, event bus and limiter are not under test here (the harness
    sends no Bearer token, so every caller would share one per-IP bucket; the
    limits themselves are covered in tests/routers/test_post_abuse_limits.py)."""
    from src.middleware.rate_limits import limiter_did
    from src.routers import posts
    monkeypatch.setattr(posts, "emit_event", AsyncMock(return_value=None))
    monkeypatch.setattr(posts, "cache_delete", AsyncMock(return_value=None))
    monkeypatch.setattr(posts.connection_manager, "broadcast_global", AsyncMock(return_value=0))
    monkeypatch.setattr(limiter_did, "enabled", False)
    yield


def _update(content: str) -> dict:
    return {"post_type": "UPDATE", "title": "Update", "content": content,
            "metadata": {"progress_percent": 0}}


async def _count(pool, did: str) -> int:
    return await pool.fetchval("SELECT count(*) FROM posts WHERE author_did = $1", did)


async def test_duplicate_post_is_409(client, pool, agents, quiet):
    alice, bob = await agents("alice"), await agents("bob")

    first = await client.post("/posts", json=_update("Earn 20% commission!"), headers=alice.headers)
    assert first.status_code == 201, first.text

    again = await client.post(
        "/posts", json=_update("  earn 20%   COMMISSION! "), headers=alice.headers,
    )
    assert again.status_code == 409, again.text
    assert await _count(pool, alice.did) == 1

    other = await client.post("/posts", json=_update("Earn 20% commission!"), headers=bob.headers)
    assert other.status_code == 201, other.text

    changed = await client.post("/posts", json=_update("Something new"), headers=alice.headers)
    assert changed.status_code == 201, changed.text


async def test_duplicate_reply_is_scoped_to_its_parent(client, pool, agents, quiet):
    alice, bob = await agents("alice"), await agents("bob")
    p1 = (await client.post("/posts", json=_update("post one"), headers=bob.headers)).json()["post_id"]
    p2 = (await client.post("/posts", json=_update("post two"), headers=bob.headers)).json()["post_id"]

    r1 = await client.post(f"/posts/{p1}/replies", json=_update("+1"), headers=alice.headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post(f"/posts/{p1}/replies", json=_update("+1"), headers=alice.headers)
    assert r2.status_code == 409, r2.text
    r3 = await client.post(f"/posts/{p2}/replies", json=_update("+1"), headers=alice.headers)
    assert r3.status_code == 201, r3.text
    # A top-level post with the same text is not a duplicate of a reply.
    r4 = await client.post("/posts", json=_update("+1"), headers=alice.headers)
    assert r4.status_code == 201, r4.text


async def test_legacy_body_posts_only_as_caller(client, pool, agents, quiet):
    mallory, victim = await agents("mallory"), await agents("victim")
    body = {"type": "note", "topic": "t", "content": "hi from me", "confidence": 0.5}

    forged = await client.post(
        "/posts", json={**body, "agent_id": str(victim.agent_id)}, headers=mallory.headers,
    )
    assert forged.status_code == 403, forged.text
    assert await _count(pool, victim.did) == 0

    own = await client.post(
        "/posts", json={**body, "agent_id": str(mallory.agent_id)}, headers=mallory.headers,
    )
    assert own.status_code == 201, own.text
    assert await _count(pool, mallory.did) == 1


# ── posts_count (S9-8b) ───────────────────────────────────────────────────────

async def _stored(pool, did: str) -> int:
    return await pool.fetchval("SELECT posts_count FROM agents WHERE agent_did = $1", did)


async def test_posts_count_follows_top_level_posts(client, pool, agents, quiet):
    alice, bob = await agents("alice"), await agents("bob")

    p1 = await client.post("/posts", json=_update("first"), headers=alice.headers)
    assert p1.status_code == 201, p1.text
    legacy = {"type": "note", "topic": "t", "content": "legacy", "confidence": 0.5,
              "agent_id": str(alice.agent_id)}
    assert (await client.post("/posts", json=legacy, headers=alice.headers)).status_code == 201
    # Replies do not count, for either the replier or the parent's author.
    reply = await client.post(
        f"/posts/{p1.json()['post_id']}/replies", json=_update("reply"), headers=bob.headers,
    )
    assert reply.status_code == 201, reply.text
    # A rejected duplicate does not count either.
    assert (await client.post("/posts", json=_update("first"), headers=alice.headers)).status_code == 409

    assert await _stored(pool, alice.did) == 2
    assert await _stored(pool, bob.did) == 0
    profile = await client.get(f"/agents/{alice.did}")
    assert profile.status_code == 200, profile.text
    assert profile.json()["posts_count"] == 2


async def test_delete_post_decrements(pool, agents, quiet):
    from src.services.post_service import delete_post
    alice = await agents("alice")
    post_id = await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content) "
        "VALUES ($1, 'UPDATE', 't', 'c') RETURNING post_id",
        alice.did,
    )
    await pool.execute("UPDATE agents SET posts_count = 1 WHERE agent_did = $1", alice.did)
    assert await delete_post(post_id) is True
    assert await _stored(pool, alice.did) == 0
    assert await delete_post(post_id) is False
    assert await _stored(pool, alice.did) == 0


async def test_backfill_dry_run_then_apply(pool, agents):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "backfill_posts_count",
        Path(__file__).resolve().parents[2] / "scripts" / "backfill_posts_count.py",
    )
    backfill_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backfill_mod)

    alice, bob = await agents("alice"), await agents("bob")
    parent = None
    for i in range(3):
        pid = await pool.fetchval(
            "INSERT INTO posts (author_did, post_type, title, content) "
            "VALUES ($1, 'UPDATE', 't', $2) RETURNING post_id",
            alice.did, f"post {i}",
        )
        parent = parent or pid
    await pool.execute(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id) "
        "VALUES ($1, 'UPDATE', 't', 'a reply', $2)",
        bob.did, parent,
    )
    await pool.execute("UPDATE agents SET posts_count = 7 WHERE agent_did = $1", bob.did)

    async with pool.acquire() as conn:
        drift = {d: (s, a) for d, s, a in await backfill_mod.backfill(conn)}
        assert drift[alice.did] == (0, 3)
        assert drift[bob.did] == (7, 0)
        assert await _stored(pool, alice.did) == 0          # dry run wrote nothing

        await backfill_mod.backfill(conn, apply=True)
        assert await _stored(pool, alice.did) == 3
        assert await _stored(pool, bob.did) == 0
        again = {d for d, _, _ in await backfill_mod.backfill(conn)}
        assert alice.did not in again and bob.did not in again
