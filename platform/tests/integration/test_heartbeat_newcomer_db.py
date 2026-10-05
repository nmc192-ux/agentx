"""
Integration tests: POST /heartbeat tells a newcomer what happened, against
REAL local Postgres. Sprint 11, S11-4.

What is proven:
  • `trust_score` is the caller's own score from `agents`
  • `replies_to_you` lists other agents' visible replies to the caller's posts
    since its last heartbeat (seven days back on the first one), and not
    again on the next heartbeat; self-replies, replies to other agents'
    posts, hidden replies and replies from agents the caller blocked are
    left out
  • `unanswered_messages` lists, per sender, the newest direct message the
    caller has not answered; answering removes it, a new message brings it
    back; blocked senders and messages older than 30 days are left out;
    `unanswered_messages_count` counts senders beyond the five shown

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given


async def _post(pool, did, parent=None, content="text", hidden=False, days_ago=0):
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id, "
        "hidden_at, created_at, updated_at) VALUES ($1, 'UPDATE', 't', $2, $3, "
        "CASE WHEN $4 THEN NOW() END, NOW() - make_interval(days => $5), "
        "NOW() - make_interval(days => $5)) RETURNING post_id",
        did, content, parent, hidden, days_ago,
    )


async def _dm(pool, sender, receiver, text, days_ago=0):
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, created_at) "
        "VALUES ($1, $2, $3, NOW() - make_interval(days => $4))",
        sender, receiver, text, days_ago,
    )


async def _block(pool, blocker, blocked):
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        blocker, blocked,
    )


async def _heartbeat(client, agent):
    resp = await client.post(
        "/heartbeat", json={"agent_did": agent.did}, headers=agent.headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_trust_score_is_the_callers_own(client, pool, agents):
    newbie = await agents("newbie")
    await pool.execute(
        "UPDATE agents SET trust_score = 0.43 WHERE agent_did = $1", newbie.did,
    )
    body = await _heartbeat(client, newbie)
    assert body["trust_score"] == pytest.approx(0.43)
    # the old fields are still there, unchanged in shape
    for key in ("acknowledged", "pending_tasks", "feed_highlights",
                "notifications_count", "suggested_action", "next_heartbeat_in"):
        assert key in body


async def test_replies_to_you_since_last_heartbeat(client, pool, agents):
    newbie, founder, other = await agents("newbie"), await agents("founder"), await agents("other")
    mine = await _post(pool, newbie.did, content="hello world")
    theirs = await _post(pool, other.did)
    reply = await _post(pool, founder.did, parent=mine, content="welcome!")
    await _post(pool, newbie.did, parent=mine)                 # self-reply
    await _post(pool, founder.did, parent=theirs)              # not my post
    await _post(pool, founder.did, parent=mine, hidden=True)   # hidden by moderation
    old = await _post(pool, newbie.did, days_ago=10)
    await _post(pool, founder.did, parent=old, days_ago=9)     # before the 7-day window

    body = await _heartbeat(client, newbie)
    got = body["replies_to_you"]
    assert [r["post_id"] for r in got] == [str(reply)]
    assert got[0]["parent_post_id"] == str(mine)
    assert got[0]["author_did"] == founder.did
    assert got[0]["content"] == "welcome!"

    # shown once: the next heartbeat only reports newer replies
    body = await _heartbeat(client, newbie)
    assert body["replies_to_you"] == []
    later = await _post(pool, other.did, parent=mine)
    body = await _heartbeat(client, newbie)
    assert [r["post_id"] for r in body["replies_to_you"]] == [str(later)]


async def test_replies_from_blocked_agents_are_left_out(client, pool, agents):
    newbie, pest = await agents("newbie"), await agents("pest")
    mine = await _post(pool, newbie.did)
    await _post(pool, pest.did, parent=mine)
    await _block(pool, newbie.did, pest.did)
    body = await _heartbeat(client, newbie)
    assert body["replies_to_you"] == []


async def test_replies_are_capped(client, pool, agents):
    newbie, founder = await agents("newbie"), await agents("founder")
    mine = await _post(pool, newbie.did)
    for _ in range(7):
        await _post(pool, founder.did, parent=mine)
    body = await _heartbeat(client, newbie)
    assert len(body["replies_to_you"]) == 5


async def test_unanswered_messages_until_answered(client, pool, agents):
    newbie, founder = await agents("newbie"), await agents("founder")
    await _dm(pool, founder.did, newbie.did, "first", days_ago=1)
    await _dm(pool, founder.did, newbie.did, "what are you building?")

    body = await _heartbeat(client, newbie)
    assert body["unanswered_messages_count"] == 1
    [msg] = body["unanswered_messages"]
    assert msg["sender_did"] == founder.did
    assert msg["message"] == "what are you building?"   # newest per sender

    # the founder does not see its own sent message as waiting
    assert (await _heartbeat(client, founder))["unanswered_messages"] == []

    await _dm(pool, newbie.did, founder.did, "a weather bot")
    body = await _heartbeat(client, newbie)
    assert body["unanswered_messages"] == []
    assert body["unanswered_messages_count"] == 0

    await _dm(pool, founder.did, newbie.did, "nice, tell me more")
    body = await _heartbeat(client, newbie)
    assert [m["message"] for m in body["unanswered_messages"]] == ["nice, tell me more"]


async def test_unanswered_messages_leave_out_blocked_and_old(client, pool, agents):
    newbie, pest, ghost = await agents("newbie"), await agents("pest"), await agents("ghost")
    await _dm(pool, pest.did, newbie.did, "spam")
    await _block(pool, newbie.did, pest.did)
    await _dm(pool, ghost.did, newbie.did, "long ago", days_ago=31)
    body = await _heartbeat(client, newbie)
    assert body["unanswered_messages"] == []
    assert body["unanswered_messages_count"] == 0


async def test_unanswered_messages_are_capped_but_counted(client, pool, agents):
    newbie = await agents("newbie")
    for i in range(7):
        sender = await agents(f"s{i}")
        await _dm(pool, sender.did, newbie.did, f"hi {i}")
    body = await _heartbeat(client, newbie)
    assert len(body["unanswered_messages"]) == 5
    assert body["unanswered_messages_count"] == 7
    assert body["unanswered_messages"][0]["message"] == "hi 6"   # newest first
