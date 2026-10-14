"""
Integration tests: list reads ship only what they show, against REAL local
Postgres. EG-5 (Neon egress).

Neon bills what Postgres sends to the API, so the check is on the rows the
database returns, not on the API response (which was already trimmed in
Python). A spy on asyncpg's fetch/fetchrow records every row.

What is proven:
  • POST /heartbeat (polled by every agent) gets at most 300 characters of
    any post or message body from the DB: pending tasks, replies to you,
    unanswered messages
  • GET /notifications gets at most 120 characters of the referenced post
  • GET /agents/{did}/recommended-tasks ranks its candidates without their
    bodies and reads full text for the `limit` winners only; it finds TASK
    posts by post_type (it used to filter on the legacy `type` column, which
    the posts API never fills, so it found nothing)

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

LONG = "x" * 2000                      # the PostCreate content maximum


@pytest.fixture
def db_rows(monkeypatch):
    """Every record the DB returns while the test runs."""
    seen: list[asyncpg.Record] = []
    real_fetch, real_fetchrow = asyncpg.Connection.fetch, asyncpg.Connection.fetchrow

    async def fetch(self, *a, **kw):
        rows = await real_fetch(self, *a, **kw)
        seen.extend(rows)
        return rows

    async def fetchrow(self, *a, **kw):
        row = await real_fetchrow(self, *a, **kw)
        if row is not None:
            seen.append(row)
        return row

    monkeypatch.setattr(asyncpg.Connection, "fetch", fetch)
    monkeypatch.setattr(asyncpg.Connection, "fetchrow", fetchrow)
    return seen


def _longest_text(rows) -> int:
    return max((len(v) for r in rows for v in r.values() if isinstance(v, str)), default=0)


async def _post(pool, did, *, post_type="UPDATE", parent=None, metadata="{}"):
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id, "
        "metadata, created_at, updated_at) "
        "VALUES ($1, $2, 't', $3, $4, $5::jsonb, NOW(), NOW()) RETURNING post_id",
        did, post_type, LONG, parent, metadata,
    )


async def test_heartbeat_reads_only_previews(client, pool, agents, db_rows):
    me, other = await agents("me"), await agents("other")
    mine = await _post(pool, me.did)
    await _post(pool, other.did, parent=mine)                  # reply to you
    await _post(pool, other.did, post_type="TASK")             # pending task
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message) "
        "VALUES ($1, $2, $3)",
        other.did, me.did, LONG,
    )

    db_rows.clear()
    resp = await client.post("/heartbeat", json={"agent_did": me.did}, headers=me.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["replies_to_you"] and body["unanswered_messages"] and body["pending_tasks"]
    assert len(body["replies_to_you"][0]["content"]) == 300
    assert len(body["unanswered_messages"][0]["message"]) == 300
    assert len(body["pending_tasks"][0]["content"]) == 300
    assert _longest_text(db_rows) <= 300


async def test_notifications_read_only_the_preview(client, pool, agents, db_rows):
    me, other = await agents("me"), await agents("other")
    post = await _post(pool, me.did)
    await pool.execute(
        "INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id) "
        "VALUES ($1, $2, 'LIKE', $3)",
        me.did, other.did, post,
    )

    db_rows.clear()
    resp = await client.get("/notifications", headers=me.headers)
    assert resp.status_code == 200, resp.text
    [notif] = resp.json()["notifications"]
    assert len(notif["post_content"]) == 120
    assert _longest_text(db_rows) <= 120


async def test_recommended_tasks_read_full_text_for_the_winners_only(
    client, pool, agents, db_rows,
):
    me, author = await agents("me"), await agents("author")
    for _ in range(8):
        await _post(pool, author.did, post_type="TASK",
                    metadata='{"required_capabilities": ["code.python"]}')

    db_rows.clear()
    resp = await client.get(
        f"/agents/{me.did}/recommended-tasks", params={"limit": 3}, headers=me.headers,
    )
    assert resp.status_code == 200, resp.text
    recs = resp.json()
    assert len(recs) == 3                                      # found by post_type
    assert all(r["content"] == LONG for r in recs)             # full text for winners
    full_bodies = [v for r in db_rows for v in r.values() if v == LONG]
    assert len(full_bodies) == 3                               # and only for them
