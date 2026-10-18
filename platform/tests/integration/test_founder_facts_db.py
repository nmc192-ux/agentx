"""
Integration tests: founder facts (src/founders/facts.py, Truthful founders TF-2)
against REAL local Postgres.

What is proven:
  • every reader's SQL runs on the real schema and gives the exact numbers
    for a small seeded world: newcomers (with and without posts, bios and
    rooms), posts and replies, room joins, trust scores, hidden posts, tasks,
    trust events and follows
  • founders' own rows and founder-to-founder tasks are not counted; hidden
    and private posts are not counted as activity; rows outside the window
    (older than 7 days / 24 hours, or later than `now`) are not counted
  • a broken query inside the caller's transaction leaves the transaction
    usable (savepoint)

Isolation: the shared throwaway database holds rows from other tests, all
dated around the real clock. These tests read at NOW = 15 Jan 2031 and date
every seeded row relative to it, so nothing else falls in the windows. Every
row made here is removed afterwards.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_founder_facts_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from src.founders import facts as F
from src.founders.truth import claim_problems

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOW = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)
PREFIX = "did:agentx:tf2fact-"
H = timedelta(hours=1)
D = timedelta(days=1)


def _did(n: int) -> str:
    return f"{PREFIX}{uuid4().hex[:6]}-{n:03d}"


@pytest_asyncio.fixture
async def world(pool):
    """A small world dated around NOW; returns the DIDs by name."""
    async def wipe():
        dids = [r["agent_did"] for r in await pool.fetch(
            "SELECT agent_did FROM agents WHERE agent_did LIKE $1", PREFIX + "%")]
        if not dids:
            return
        await pool.execute("DELETE FROM follows WHERE follower_did = ANY($1::text[]) "
                           "OR following_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM tasks WHERE requester_agent_did = ANY($1::text[]) "
                           "OR executor_agent_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM room_participants WHERE agent_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM rooms WHERE creator_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[]) "
                           "AND parent_post_id IS NOT NULL", dids)
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", dids)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", dids)
        for table in ("agent_reputation_history", "trust_scores"):
            await pool.execute(
                f"DELETE FROM {table} WHERE agent_id IN "
                "(SELECT agent_id FROM agents WHERE agent_did = ANY($1::text[]))", dids)
        await pool.execute("DELETE FROM agents WHERE agent_did = ANY($1::text[])", dids)

    async def agent(n, joined, *, founder=False, bio=None, trust=0.5, status="ACTIVE"):
        did = _did(n)
        await pool.execute(
            "INSERT INTO agents (agent_did, display_name, governance_role, created_at, bio, "
            "trust_score, status) VALUES ($1, $2, $3::governance_role, $4, $5, $6, "
            "$7::agent_status)",
            did, f"tf2-{n}", "FOUNDER" if founder else "MEMBER", joined, bio, trust, status,
        )
        return did

    async def post(did, at, *, parent=None, hidden=None, reason=None, by=None,
                   visibility="PUBLIC"):
        agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
        return await pool.fetchval(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, "
            "parent_post_id, created_at, visibility, hidden_at, hidden_reason, hidden_by) "
            "VALUES ($1, $2, 'UPDATE', 't', 'c', $3, $4, $5::post_visibility, $6, $7, $8) "
            "RETURNING post_id",
            agent_id, did, parent, at, visibility, hidden, reason, by,
        )

    async def room(creator, status="OPEN"):
        return await pool.fetchval(
            "INSERT INTO rooms (name, room_type, status, creator_did, created_at) "
            "VALUES ($1, 'BRAINSTORM', $2, $3, $4) RETURNING room_id",
            f"tf2 room {uuid4().hex[:6]}", status, creator, NOW - 10 * D,
        )

    async def join(room_id, did, at):
        await pool.execute(
            "INSERT INTO room_participants (room_id, agent_did, role, joined_at) "
            "VALUES ($1, $2, 'PARTICIPANT', $3)", room_id, did, at)

    async def task(req, ex, at, status="PENDING"):
        await pool.execute(
            "INSERT INTO tasks (requester_agent_did, executor_agent_did, task_type, payload, "
            "status, created_at) VALUES ($1, $2, 'generic', '{}'::jsonb, $3, $4)",
            req, ex, status, at)

    async def trust_event(did, at):
        await pool.execute(
            "INSERT INTO trust_events (agent_did, event_type, event_weight, event_value, "
            "created_at) VALUES ($1, 'task_completed', 1, 1, $2)", did, at)

    async def follow(a, b, at):
        await pool.execute(
            "INSERT INTO follows (follower_did, following_did, created_at) VALUES ($1, $2, $3)",
            a, b, at)

    await wipe()
    w = {}
    # Founders (never counted) and an old member.
    w["founder"] = await agent(1, NOW - 2 * H, founder=True, trust=0.9)
    w["founder2"] = await agent(2, NOW - 30 * D, founder=True)
    w["old"] = await agent(3, NOW - 30 * D, bio="old hand", trust=0.8)
    # Newcomers: two in the last 24h, two more in the last 7 days.
    w["n1"] = await agent(4, NOW - 3 * H, trust=0.2)                # no bio, posts after 1h
    w["n2"] = await agent(5, NOW - 10 * H, bio="  ", trust=0.4)     # blank bio, no post
    w["n3"] = await agent(6, NOW - 3 * D, bio="I summarise papers", trust=0.5)  # posts after 3h
    w["n4"] = await agent(7, NOW - 6 * D, bio="hi", trust=0.75)     # no post, in a room
    # Not counted: suspended, joined 8 days ago, joined after NOW.
    await agent(8, NOW - 1 * H, status="SUSPENDED", trust=0.1)
    await agent(9, NOW - 8 * D, bio="x", trust=0.5)
    await agent(10, NOW + 1 * H, trust=0.5)

    # Posts in the last 24h: 2 visible top-level, 1 reply (by outsiders).
    p1 = await post(w["n1"], NOW - 2 * H)
    await post(w["old"], NOW - 5 * H)
    await post(w["old"], NOW - 1 * H, parent=p1)
    # Not activity: founder post, hidden, private, 2 days old, after NOW.
    await post(w["founder"], NOW - 1 * H)
    await post(w["old"], NOW - 4 * H, hidden=NOW - 3 * H, reason="auto_hold:solicitation")
    await post(w["old"], NOW - 4 * H, visibility="PRIVATE")
    await post(w["n3"], NOW - 3 * D + 3 * H)                         # n3's first post
    # n2 posted, but it is hidden: n2 still counts as "not posted yet".
    await post(w["n2"], NOW - 9 * H, hidden=NOW - 8 * H, reason="withdrawn")
    await post(w["old"], NOW + 1 * H)
    # Moderation in the last 7 days: 1 held (above), 2 by flags, 1 by a moderator;
    # one moderator hide 9 days ago is outside.
    await post(w["old"], NOW - 3 * D, hidden=NOW - 2 * D, reason="flags")
    await post(w["old"], NOW - 3 * D, hidden=NOW - 2 * D, reason="flags")
    await post(w["old"], NOW - 3 * D, hidden=NOW - 1 * D, reason="off topic", by=w["founder"])
    await post(w["old"], NOW - 10 * D, hidden=NOW - 9 * D, reason="spam", by=w["founder"])

    # Rooms: two open, one closed. Joins in the last 7 days by outsiders: 3 in 2 open rooms.
    r1, r2, r3 = await room(w["founder"]), await room(w["old"]), await room(w["old"], "CLOSED")
    await join(r1, w["n4"], NOW - 5 * D)
    await join(r1, w["old"], NOW - 2 * D)
    await join(r2, w["n1"], NOW - 1 * H)
    await join(r1, w["founder"], NOW - 1 * D)          # founder: not counted
    await join(r3, w["old"], NOW - 1 * D)              # closed room: not counted
    await join(r2, w["old"], NOW - 9 * D)              # too old

    # Tasks in the last 7 days: 3 counted (2 taken, 1 completed); founder-to-founder not.
    await task(w["old"], w["n3"], NOW - 2 * D, "COMPLETED")
    await task(w["n1"], None, NOW - 1 * H)
    await task(w["founder"], w["n4"], NOW - 1 * D)
    await task(w["founder"], w["founder2"], NOW - 1 * D, "COMPLETED")
    await task(w["old"], None, NOW - 8 * D)

    # Trust events: 3 for 2 outsiders in 7 days; a founder's and an old one are not.
    await trust_event(w["n3"], NOW - 2 * D)
    await trust_event(w["n3"], NOW - 1 * D)
    await trust_event(w["old"], NOW - 1 * H)
    await trust_event(w["founder"], NOW - 1 * H)
    await trust_event(w["old"], NOW - 10 * D)

    # Follows: 2 by outsiders in 7 days; a founder's and an old one are not.
    await follow(w["n1"], w["old"], NOW - 1 * H)
    await follow(w["n3"], w["old"], NOW - 2 * D)
    await follow(w["founder"], w["old"], NOW - 1 * H)
    await follow(w["old"], w["n3"], NOW - 9 * D)
    yield w
    await wipe()


def _texts(facts):
    for f in facts:
        assert claim_problems(f.text, facts=[f.text]) == [], f.text
    return {f.key: f.text for f in facts}


async def test_thea_exact_numbers(pool, world):
    # The trust spread covers every active agent, so other tests' agents count too:
    # ours are added to what is there already.
    base = await pool.fetchrow(
        "SELECT COUNT(*) AS t, COUNT(*) FILTER (WHERE trust_score < 0.3) AS l, "
        "COUNT(*) FILTER (WHERE trust_score >= 0.3 AND trust_score < 0.7) AS m, "
        "COUNT(*) FILTER (WHERE trust_score >= 0.7) AS h FROM agents "
        "WHERE status::text = 'ACTIVE' AND governance_role::text <> 'FOUNDER' "
        "AND trust_score IS NOT NULL AND agent_did NOT LIKE $1", PREFIX + "%")
    async with pool.acquire() as conn:
        by = _texts(await F.thea_facts(conn, NOW))
    # Ours: old, n1..n4 and the 8-day one → 6 (trust 0.8, 0.2, 0.4, 0.5, 0.75, 0.5);
    # the suspended one and the future one are out.
    t, lo, m, h = base["t"] + 6, base["l"] + 1, base["m"] + 3, base["h"] + 2
    assert by == {
        "thea.new_agents": "4 new agents joined in the last 7 days, 2 of them in the last 24 hours.",
        "thea.posts_24h": ("Agents other than the founders wrote 2 new posts and 1 reply "
                           "in the last 24 hours."),
        "thea.room_joins_7d": ("3 room joins by agents other than the founders in the last "
                               "7 days, across 2 open rooms."),
        "thea.trust_spread": (f"Trust scores of the {t} active agents other than the founders: "
                              f"{lo} under 0.3, {m} from 0.3 to 0.7, {h} at 0.7 or more."),
    }


async def test_marcus_moderation_exact(pool, world):
    async with pool.acquire() as conn:
        by = _texts(await F.marcus_facts(conn, NOW))
    assert by["marcus.moderation_7d"] == (
        "Moderation in the last 7 days: 1 post held by the solicitation filter, "
        "2 posts hidden after flags and 1 post hidden by a moderator.")


async def test_daria_exact(pool, world):
    async with pool.acquire() as conn:
        by = _texts(await F.daria_facts(conn, NOW))
    lead = "Of the 4 agents who joined in the last 7 days"
    assert by == {
        "daria.no_post": f"{lead}, 2 have not posted yet.",
        "daria.no_bio": f"{lead}, 2 have no bio on their profile.",
        "daria.no_room": f"{lead}, 2 have not joined a room.",
        # n1 after 1 hour, n3 after 3 hours → middle 2 hours.
        "daria.time_to_first_post": ("For agents who joined in the last 7 days and posted, the "
                                     "middle time from sign-up to first post is 2 hours."),
    }


async def test_nova_exact(pool, world):
    async with pool.acquire() as conn:
        by = _texts(await F.nova_facts(conn, NOW))
    assert by == {
        "nova.tasks_7d": ("3 tasks posted in the last 7 days, not counting the founders' own "
                          "handoffs: 2 with an agent assigned and 1 completed."),
        "nova.trust_events_7d": ("3 trust events recorded in the last 7 days for 2 agents "
                                 "other than the founders."),
        "nova.follows_7d": "Agents other than the founders started 2 follows in the last 7 days.",
    }


async def test_roster_founders_are_left_out_whatever_their_role(pool, world):
    """TF-9: in production the founders are MEMBERs, known by FOUNDER_DIDS.
    Treat "old" and "n4" (both MEMBERs) as roster founders: their posts,
    joins, trust events and their handoff to each other's kind drop out."""
    roster = [world["old"], world["n4"]]
    async with pool.acquire() as conn:
        thea = _texts(await F.thea_facts(conn, NOW, founder_dids=roster))
        nova = _texts(await F.nova_facts(conn, NOW, founder_dids=roster))
        daria = _texts(await F.daria_facts(conn, NOW, founder_dids=roster))
    assert thea["thea.new_agents"] == (
        "3 new agents joined in the last 7 days, 2 of them in the last 24 hours.")
    assert thea["thea.posts_24h"] == (
        "Agents other than the founders wrote 1 new post in the last 24 hours.")
    assert thea["thea.room_joins_7d"] == (
        "1 room join by agents other than the founders in the last 7 days, across 1 open room.")
    # founder (role) → n4 (roster) is a founders' handoff now; old → n3 is not
    assert nova["nova.tasks_7d"] == ("2 tasks posted in the last 7 days, not counting the "
                                     "founders' own handoffs: 1 with an agent assigned and 1 completed.")
    assert nova["nova.trust_events_7d"] == (
        "2 trust events recorded in the last 7 days for 1 agent other than the founders.")
    assert daria["daria.no_post"].startswith("Of the 3 agents who joined in the last 7 days")


async def test_quiet_world_has_no_db_facts(pool):
    """A moment with nothing around it: no DB fact at all, only MARCUS's
    configuration facts."""
    quiet = datetime(2040, 6, 1, 12, 0, tzinfo=timezone.utc)
    async with pool.acquire() as conn:
        # The trust spread is a standing number, not a window.
        assert {f.key for f in await F.thea_facts(conn, quiet)} <= {"thea.trust_spread"}
        assert await F.daria_facts(conn, quiet) == []
        assert await F.nova_facts(conn, quiet) == []
        keys = {f.key for f in await F.marcus_facts(conn, quiet)}
        assert "marcus.moderation_7d" not in keys


async def test_failed_query_keeps_caller_transaction_usable(pool, world):
    async with pool.acquire() as conn:
        async with conn.transaction():
            assert await F._row(conn, "/* fact:x */ SELECT * FROM no_such_table") is None
            assert await conn.fetchval("SELECT 1") == 1
            assert {f.key for f in await F.nova_facts(conn, NOW)} == {
                "nova.tasks_7d", "nova.trust_events_7d", "nova.follows_7d"}
