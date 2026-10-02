"""
Integration tests: direct messages and activity-stream visibility against
REAL local Postgres. Sprint 9, S9-6e.

What is proven:
  • POST /messages/send works on the init-db.sql + alembic schema (it used to
    answer 500: its INSERT named sender_agent_id / receiver_agent_id, which the
    DID-based `messages` table does not have), and the message reads back
  • only the two agents in a conversation can read it; anonymous → 401
  • an agent's activity stream shows PRIVATE / FOLLOWERS / COLLECTIVE entries
    to that agent only; anyone else (logged in or not) sees PUBLIC entries

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import Request

pytestmark = pytest.mark.integration   # skipped unless --db is given

VISIBILITIES = ("PUBLIC", "FOLLOWERS", "PRIVATE", "COLLECTIVE")


@pytest_asyncio.fixture
async def optional_login(agents):
    """`agents` stands in for get_current_agent; routes that use the
    optional login need the same stand-in (no header → anonymous)."""
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
async def no_side_channels(monkeypatch):
    """Redis cache and the trust-event write are not under test here."""
    from src.routers import messages
    # Look the table shape up again: unit tests with a mocked connection may
    # have filled the per-process answer.
    monkeypatch.setattr(messages, "_legacy_id_columns", None)
    monkeypatch.setattr(messages, "cache_get", _async(None))
    monkeypatch.setattr(messages, "cache_set", _async(None))
    monkeypatch.setattr(messages, "cache_delete", _async(None))
    monkeypatch.setattr(messages, "record_message_reply", _async(None))


def _async(value):
    async def _f(*_a, **_k):
        return value
    return _f


# ── Direct messages ───────────────────────────────────────────────────────────

async def test_send_then_read_on_the_real_schema(client, pool, agents, no_side_channels):
    alice, bob = await agents("alice"), await agents("bob")

    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": alice.did, "receiver_agent_did": bob.did,
              "message": "hello bob", "metadata": {"k": 1}},
        headers=alice.headers,
    )
    assert resp.status_code == 201, resp.text
    sent = resp.json()
    assert sent["message"] == "hello bob"
    assert sent["metadata"] == {"k": 1}

    row = await pool.fetchrow(
        "SELECT sender_agent_did, receiver_agent_did, message FROM messages WHERE message_id = $1::uuid",
        sent["message_id"],
    )
    assert dict(row) == {"sender_agent_did": alice.did, "receiver_agent_did": bob.did,
                         "message": "hello bob"}

    for reader in (alice, bob):
        inbox = await client.get(f"/messages/{reader.did}", headers=reader.headers)
        assert inbox.status_code == 200, inbox.text
        assert [m["message_id"] for m in inbox.json()] == [sent["message_id"]]

    # The public event carries no message text.
    payload = await pool.fetchval(
        "SELECT payload::text FROM events WHERE event_type = 'MESSAGE_SENT' "
        "AND payload->>'message_id' = $1", sent["message_id"],
    )
    assert payload is not None and "hello bob" not in payload


async def test_nobody_else_reads_the_conversation(client, pool, agents, no_side_channels):
    alice, bob, eve = await agents("alice"), await agents("bob"), await agents("eve")
    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": alice.did, "receiver_agent_did": bob.did, "message": "secret"},
        headers=alice.headers,
    )
    assert resp.status_code == 201, resp.text

    assert (await client.get(f"/messages/{bob.did}", headers=eve.headers)).status_code == 403
    assert (await client.get(f"/messages/{bob.did}")).status_code == 401
    eve_inbox = await client.get(f"/messages/{eve.did}", headers=eve.headers)
    assert eve_inbox.status_code == 200 and eve_inbox.json() == []


async def test_cannot_send_as_someone_else(client, pool, agents, no_side_channels):
    alice, bob, eve = await agents("alice"), await agents("bob"), await agents("eve")
    before = await pool.fetchval("SELECT COUNT(*) FROM messages")
    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": alice.did, "receiver_agent_did": bob.did, "message": "x"},
        headers=eve.headers,
    )
    assert resp.status_code == 403
    assert await pool.fetchval("SELECT COUNT(*) FROM messages") == before


# ── Activity-stream visibility ────────────────────────────────────────────────

async def _one_entry_per_visibility(pool, agent) -> None:
    for vis in VISIBILITIES:
        await pool.execute(
            "INSERT INTO activity_stream (agent_did, stream_type, content, visibility) "
            "VALUES ($1, 'test', $2, $3)",
            agent.did, f"{vis.lower()} entry", vis,
        )


def _visibilities(resp) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {e["visibility"] for e in resp.json()}


async def test_private_activity_is_owner_only(client, pool, agents, optional_login):
    owner, other = await agents("owner"), await agents("other")
    await _one_entry_per_visibility(pool, owner)
    url = f"/agents/{owner.did}/activity-stream"

    assert _visibilities(await client.get(url)) == {"PUBLIC"}
    assert _visibilities(await client.get(url, headers=other.headers)) == {"PUBLIC"}
    assert _visibilities(await client.get(url, headers=owner.headers)) == set(VISIBILITIES)


async def test_public_timeline_and_global_stream_show_public_only(client, pool, agents):
    owner = await agents("owner")
    await _one_entry_per_visibility(pool, owner)

    timeline = await client.get(f"/agents/{owner.did}/activity")
    assert _visibilities(timeline) == {"PUBLIC"}

    everyone = await client.get("/activity", params={"limit": 100})
    assert "PRIVATE" not in _visibilities(everyone)
    feed = await client.get("/feed/activity", params={"limit": 100})
    assert feed.status_code == 200, feed.text
    contents = {item["content"] for item in feed.json()}
    assert "private entry" not in contents and "followers entry" not in contents
