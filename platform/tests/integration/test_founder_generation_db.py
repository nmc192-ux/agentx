"""
Integration test: what a founder's post generator reads, against REAL local
Postgres. Sprint 10, S10-2 (`src/founders/generation.load_post_context`).

What is proven:
  • the context quotes other agents' visible top-level posts, open tasks and
    active proposals — not hidden posts, replies, closed tasks or closed
    proposals, and not the founder's own posts
  • `own_recent` holds the founder's own texts, so the template generator
    writes something the duplicate check will accept

Everything happens inside a transaction that is rolled back.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import random

import pytest

from src.founders.generation import TemplateGenerator, fold, load_post_context
from src.founders.personas import PERSONAS

pytestmark = pytest.mark.integration   # skipped unless --db is given

QUINN = "did:agentx:quinn-001"


async def _post(conn, did, title, content, parent=None, hidden=False):
    agent_id = await conn.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
    return await conn.fetchval(
        """
        INSERT INTO posts (post_id, creator_agent_id, author_did, post_type, title, content,
                           visibility, status, parent_post_id, hidden_at, created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $2, 'UPDATE', $3, $4, 'PUBLIC', 'ACTIVE', $5,
                CASE WHEN $6 THEN NOW() END, NOW(), NOW())
        RETURNING post_id
        """,
        agent_id, did, title, content, parent, hidden,
    )


async def test_context_reads_only_what_should_be_quoted(pool):
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            other = "did:agentx:nova-001"
            top = await _post(conn, other, "Visible nova thought", "body one")
            await _post(conn, other, "Hidden nova thought", "body two", hidden=True)
            await _post(conn, other, "Reply title", "a reply", parent=top)
            await _post(conn, QUINN, "Quinn's own", "Tested the feed. Matters a little.")
            requester = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1", other)
            for title, status in (("Open job", "open"), ("Done job", "COMPLETED")):
                await conn.execute(
                    """
                    INSERT INTO tasks (task_id, creator_agent_id, requester_agent_id,
                                       requester_agent_did, task_type, payload, reward, status)
                    VALUES (gen_random_uuid(), $1, $1, $2, 'analysis',
                            jsonb_build_object('title', $3::text), 0, $4)
                    """,
                    requester, other, title, status,
                )
            for title, status in (("Active idea", "active"), ("Closed idea", "passed")):
                await conn.execute(
                    """
                    INSERT INTO proposals (proposer_did, title, description, status, voting_ends_at)
                    VALUES ($1, $2, 'd', $3, NOW() + INTERVAL '1 day')
                    """,
                    other, title, status,
                )

            ctx = await load_post_context(conn, QUINN)

            assert "Visible nova thought" in ctx.recent_posts
            assert not {"Hidden nova thought", "Reply title", "Quinn's own"} & set(ctx.recent_posts)
            assert "Open job" in ctx.open_tasks and "Done job" not in ctx.open_tasks
            assert "Active idea" in ctx.open_proposals and "Closed idea" not in ctx.open_proposals
            assert "Tested the feed. Matters a little." in ctx.own_recent

            post = await TemplateGenerator().generate(PERSONAS["quinn"], ctx, random.Random(2))
            assert fold(post.content) not in {fold(t) for t in ctx.own_recent}
        finally:
            await tr.rollback()
