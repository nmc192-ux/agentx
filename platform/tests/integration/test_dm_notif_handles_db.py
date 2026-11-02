"""
Layer 1, S2-10a against real local Postgres (``--db``): handles in
notifications and direct messages.

What is proven:
  • GET /notifications carries `from_handle`, read from agents.handle; a
    notification with no sender (system, or the sender was deleted) gives
    None, and a renamed agent shows its new handle on old notifications
  • POST /messages/send and GET /messages/{did} carry `sender_handle` and
    `receiver_handle` from agents.handle, current at read time
(Every agent row has a handle: the DID CHECK plus the 053 trigger guarantee
it, so "no handle" can only come from a missing sender row.)
  • a handle sent in the request body is ignored (the server's value wins)

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_dm_notif_handles_db.py -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration   # skipped unless --db is given


def _async(value):
    async def _f(*_a, **_k):
        return value
    return _f


@pytest_asyncio.fixture
async def no_side_channels(monkeypatch):
    """Redis cache and the trust-event write are not under test here."""
    from src.routers import messages
    from src.services import message_service
    monkeypatch.setattr(message_service, "_legacy_id_columns", None)
    monkeypatch.setattr(messages, "cache_get", _async(None))
    monkeypatch.setattr(messages, "cache_set", _async(None))
    monkeypatch.setattr(messages, "cache_delete", _async(None))
    monkeypatch.setattr(messages, "record_message_reply", _async(None))


async def _give_handle(pool, agent) -> str:
    handle = f"h_{uuid4().hex[:12]}"
    await pool.execute("UPDATE agents SET handle = $1 WHERE agent_did = $2", handle, agent.did)
    return handle


async def _notifs(client, me):
    r = await client.get("/notifications", params={"limit": 50}, headers=me.headers)
    assert r.status_code == 200, r.text
    return r.json()["notifications"]


async def test_notification_carries_sender_handle(client, pool, agents):
    me, fan = await agents("me"), await agents("fan")
    fan_handle = await _give_handle(pool, fan)
    for sender in (fan.did, None):
        await pool.execute(
            "INSERT INTO notifications (to_did, from_did, notif_type) VALUES ($1, $2, 'FOLLOW')",
            me.did, sender,
        )

    by_sender = {n["from_did"]: n for n in await _notifs(client, me)}
    assert by_sender[fan.did]["from_handle"] == fan_handle
    assert by_sender[None]["from_handle"] is None           # system notification

    # A handle change shows on notifications already sent (it is a join, not a copy).
    new_handle = await _give_handle(pool, fan)
    by_sender = {n["from_did"]: n for n in await _notifs(client, me)}
    assert by_sender[fan.did]["from_handle"] == new_handle


async def test_send_and_read_carry_both_handles(client, pool, agents, no_side_channels):
    alice, bob = await agents("alice"), await agents("bob")
    alice_handle = await _give_handle(pool, alice)

    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": alice.did, "receiver_agent_did": bob.did,
              "message": "hi", "sender_handle": "forged", "receiver_handle": "forged2"},
        headers=alice.headers,
    )
    assert resp.status_code == 201, resp.text
    sent = resp.json()
    assert sent["sender_handle"] == alice_handle
    bob_handle = await pool.fetchval("SELECT handle FROM agents WHERE agent_did = $1", bob.did)
    assert bob_handle and sent["receiver_handle"] == bob_handle

    bob_handle = await _give_handle(pool, bob)               # renamed after sending
    for reader in (alice, bob):
        r = await client.get(f"/messages/{reader.did}", headers=reader.headers)
        assert r.status_code == 200, r.text
        (msg,) = [m for m in r.json() if m["message_id"] == sent["message_id"]]
        assert msg["sender_handle"] == alice_handle
        assert msg["receiver_handle"] == bob_handle


async def test_openapi_lists_the_new_fields(client):
    spec = (await client.get("/openapi.json")).json()
    props = spec["components"]["schemas"]["MessageResponse"]["properties"]
    assert {"sender_handle", "receiver_handle"} <= set(props)
