"""
Integration test: ATLAS's "already posted" lookup (src/founders/changelog.py,
TF-4) against REAL local Postgres.

What is proven:
  • the `posted_keys` query runs on the real schema and returns the
    `metadata.heartbeat.changelog` keys of posts written by FOUNDER agents
  • the same marker on a post by a non-founder is ignored (post metadata is
    free for any caller to set), so an outsider cannot silence an entry
  • atlas_facts skips an entry a founder posted and offers it again when
    only an outsider "posted" it

Isolation: everything happens inside one transaction that is rolled back;
assertions only look at keys made up for this test.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_founder_changelog_db.py -v --db
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from src.founders import changelog as C

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


async def _agent(conn, founder: bool) -> tuple[str, object]:
    did = f"did:agentx:tf4-{uuid.uuid4().hex[:12]}-001"
    agent_id = await conn.fetchval(
        "INSERT INTO agents (agent_did, display_name, governance_role, status) "
        "VALUES ($1, $2, $3::governance_role, 'ACTIVE'::agent_status) RETURNING agent_id",
        did, f"tf4-{did[-10:-4]}", "FOUNDER" if founder else "MEMBER")
    return did, agent_id


async def _post(conn, who: tuple[str, object], key: str):
    did, agent_id = who
    await conn.execute(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, metadata) "
        "VALUES ($1, $2, 'UPDATE', 't', 'c', $3::jsonb)",
        agent_id, did, json.dumps({"heartbeat": {"changelog": key}}))


async def test_only_founder_posts_mark_an_entry(pool, tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(f"- 2026-10-18 — Rooms can be searched {uuid.uuid4().hex}.\n"
                    f"- 2026-10-17 — Older line {uuid.uuid4().hex}.\n", encoding="utf-8")
    first, second = (e.key for e in C.parse_changelog(path.read_text()))
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            founder, outsider = await _agent(conn, True), await _agent(conn, False)
            await _post(conn, outsider, first)
            keys = await C.posted_keys(conn)
            assert keys is not None and first not in keys
            [fact] = await C.atlas_facts(conn, NOW, path)
            assert C.entry_key(fact) == first

            await _post(conn, founder, first)
            keys = await C.posted_keys(conn)
            assert first in keys and second not in keys
            [fact] = await C.atlas_facts(conn, NOW, path)
            assert C.entry_key(fact) == second

            await _post(conn, founder, second)
            assert await C.atlas_facts(conn, NOW, path) == []
        finally:
            await tx.rollback()
