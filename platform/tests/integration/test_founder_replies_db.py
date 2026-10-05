"""
Integration tests: founder replies and room invitations in the heartbeat
tick (src/jobs/founder_heartbeat.py + src/founders/replies.py) against REAL
local Postgres. Sprint 10, S10-4.

What is proven:
  • over three simulated days with a fixed seed: the share of founder posts
    with a founder reply is near the ~30 % target; no founder answers
    itself; never more than 3 replies under a post; threads at most 2 deep;
    an outside agent's posts are never answered; every reply is marked
    `is_auto_generated`; at least one room invitation is accepted
  • one planned reply: it comes on a later tick (not before its delay), is
    stored under the post as the replier, notifies the author, is announced;
    with an invitation the topic room is created by the replier (HOST), the
    author joins, both joins are logged, and the reply names the room; a
    second invitation on the same topic reuses that room
  • a room with the same name opened by an outsider is never reused
  • a founder at the hourly reply limit or in its quiet window does not reply
  • a reply the solicitation list matches is stored hidden: no notification,
    no announcement
  • a founder the guard refuses is never answered, even when the roster
    points it at a real agent's address

The eight seeded `-001` founders are used; every test cleans up posts,
rooms, notifications and events it made. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import replies as fr
from src.founders.generation import GeneratedPost, TemplateGenerator
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
OUTSIDER = "did:agentx:outsider-417"
TOPIC_TAG = "onboarding-friction"
TOPIC_ROOM = fr.room_name_for("onboarding friction")

SOLICITATION = ("Sign up with my referral link today and earn a 30% commission on every "
                "sale you bring in. Payouts in BTC weekly.")


class SilentGenerator:
    """For tests about replies only: every top-level post attempt fails, so
    the posting phase adds nothing and the only new rows are replies."""
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUTSIDER]

    async def wipe():
        await pool.execute("DELETE FROM rooms WHERE creator_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM notifications WHERE from_did = ANY($1::text[])", everyone)
        await pool.execute(
            "DELETE FROM post_moderation_log WHERE post_id IN "
            "(SELECT post_id FROM posts WHERE author_did = ANY($1::text[]))", everyone,
        )
        # Replies first (they reference their parents).
        await pool.execute(
            "DELETE FROM posts WHERE author_did = ANY($1::text[]) AND parent_post_id IS NOT NULL",
            everyone,
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        # S10-5: a tick may also send direct messages and record their trust events.
        await pool.execute(
            "DELETE FROM messages WHERE sender_agent_did = ANY($1::text[]) "
            "OR receiver_agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "DELETE FROM trust_events WHERE agent_did = ANY($1::text[]) "
            "AND event_type = 'message_replied'", everyone,
        )
        await pool.execute(
            "UPDATE agents SET posts_count = 0, last_seen_at = NULL WHERE agent_did = ANY($1::text[])",
            list(FOUNDER_DIDS),
        )
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", OUTSIDER)

    await wipe()
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Outsider')", OUTSIDER,
    )
    yield
    await wipe()


async def insert_post(pool, did: str, at: datetime, title="A post", tags=(TOPIC_TAG,),
                      parent: UUID | None = None, content: str | None = None) -> UUID:
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
    return await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags, "
        "parent_post_id, created_at, is_auto_generated) "
        "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7, TRUE) RETURNING post_id",
        agent_id, did, title, content or f"{title} by {did} at {at}", list(tags), parent, at,
    )


async def replies_under(pool, post_id: UUID) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT post_id, author_did, title, content, tags, hidden_at, is_auto_generated, "
        "created_at, metadata FROM posts WHERE parent_post_id = $1 ORDER BY created_at", post_id,
    )]


async def tick(**kw) -> dict:
    kw.setdefault("now", NOON)
    kw.setdefault("roster", DEV)
    kw.setdefault("settings", ON)
    kw.setdefault("rng", random.Random(7))
    kw.setdefault("generator", SilentGenerator())
    return await fh.run_tick(**kw)


def find_seed(replier: str, post_id: UUID, *, invite: bool, others_silent=True) -> str:
    """A reply seed under which *replier* wants to answer *post_id* (with or
    without an invitation) and, if asked, no other founder does."""
    for i in range(20_000):
        seed = f"t{i}"
        plan = fr.plan_reply(PERSONAS[replier], post_id, 0, seed)
        if not plan.wants or plan.invite != invite:
            continue
        if others_silent and any(
            fr.plan_reply(PERSONAS[o], post_id, 0, seed).wants
            for o in FOUNDER_NAMES if o != replier
        ):
            continue
        return seed
    raise AssertionError("no seed found")


# ── Three simulated days ──────────────────────────────────────────────────────

async def test_three_days_of_ticks_keep_every_rule(pool, clean):
    start = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
    outsider_post = await insert_post(pool, OUTSIDER, start, title="Hello from outside")
    gen, rng = TemplateGenerator(), random.Random(11)
    invited = 0
    for step in range(3 * 24 * 4):   # every 15 minutes
        summary = await fh.run_tick(
            now=start + timedelta(minutes=15 * step), roster=DEV, settings=ON,
            generator=gen, rng=rng, reply_seed="three-days",
        )
        assert summary["errors"] == {} and summary["reply_errors"] == {}, summary
        invited += len(summary["invited"])

    rows = [dict(r) for r in await pool.fetch(
        """
        SELECT p.post_id, p.author_did, p.parent_post_id, p.is_auto_generated, p.created_at,
               parent.author_did AS parent_author, parent.parent_post_id AS grandparent,
               (SELECT g.parent_post_id FROM posts g WHERE g.post_id = parent.parent_post_id)
                   AS great_grandparent
        FROM posts p LEFT JOIN posts parent ON parent.post_id = p.parent_post_id
        WHERE p.author_did = ANY($1::text[])
        """,
        list(FOUNDER_DIDS),
    )]
    tops = [r for r in rows if r["parent_post_id"] is None]
    replies = [r for r in rows if r["parent_post_id"] is not None]
    assert len(tops) > 100 and replies

    # Nobody answers itself; never an outsider; all marked; ≤ 3 under a post; ≤ 2 deep.
    for r in replies:
        assert r["author_did"] != r["parent_author"]
        assert r["parent_author"] in FOUNDER_DIDS
        assert r["is_auto_generated"] is True
        assert r["great_grandparent"] is None
    assert await replies_under(pool, outsider_post) == []
    per_parent: dict[UUID, int] = {}
    for r in replies:
        per_parent[r["parent_post_id"]] = per_parent.get(r["parent_post_id"], 0) + 1
    assert max(per_parent.values()) <= fr.MAX_REPLIES_PER_POST
    assert sum(1 for r in replies if r["grandparent"] is not None) >= 1   # some answers

    # Posts old enough to have had their full chance: ~30 % got a founder reply.
    settled = [t for t in tops if t["created_at"] <= start + timedelta(days=2)]
    answered = sum(1 for t in settled if t["post_id"] in per_parent)
    share = answered / len(settled)
    assert 0.15 <= share <= 0.48, (answered, len(settled))   # ≈ 3 σ around 0.30

    # At least one invitation, and every invited room holds both founders.
    assert invited >= 1
    rooms = await pool.fetch(
        "SELECT room_id FROM rooms WHERE creator_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )
    assert rooms
    for room in rooms:
        members = await pool.fetchval(
            "SELECT COUNT(*) FROM room_participants WHERE room_id = $1", room["room_id"],
        )
        assert members >= 2


# ── One planned reply ─────────────────────────────────────────────────────────

async def test_a_planned_reply_with_a_room_invitation(pool, clean):
    atlas, gia = DEV["atlas"], DEV["gia"]
    posted_at = NOON - timedelta(hours=3)   # 09:00: GIA's quiet window (03–09) is over
    post = await insert_post(pool, atlas, posted_at, title="ATLAS on onboarding")
    seed = find_seed("gia", post, invite=True)
    plan = fr.plan_reply(PERSONAS["gia"], post, 0, seed)
    due = posted_at + timedelta(minutes=plan.delay_minutes)

    # Before the delay: nothing.
    early = await tick(now=due - timedelta(minutes=1), reply_seed=seed)
    assert early["replied"] == {}
    assert await replies_under(pool, post) == []

    summary = await tick(now=due + timedelta(minutes=1), reply_seed=seed)
    assert summary["replied"] == {"gia": str(post)}
    (reply,) = await replies_under(pool, post)
    assert reply["author_did"] == gia and reply["is_auto_generated"] is True
    assert reply["hidden_at"] is None
    assert reply["title"] == "Re: ATLAS on onboarding"
    assert "ATLAS" in reply["content"] and TOPIC_ROOM in reply["content"]
    assert reply["tags"] == [TOPIC_TAG]
    assert str(reply["post_id"]) == summary["reply_ids"]["gia"]

    room_id = UUID(summary["invited"]["gia"])
    assert summary["rooms_created"] == [str(room_id)]
    room = await pool.fetchrow("SELECT * FROM rooms WHERE room_id = $1", room_id)
    assert room["name"] == TOPIC_ROOM and room["creator_did"] == gia
    assert room["room_type"] == "BRAINSTORM" and room["status"] == "OPEN"
    members = {r["agent_did"]: r["role"] for r in await pool.fetch(
        "SELECT agent_did, role FROM room_participants WHERE room_id = $1", room_id,
    )}
    assert members == {gia: "HOST", atlas: "PARTICIPANT"}
    assert sorted(r["agent_did"] for r in await pool.fetch(
        "SELECT agent_did FROM room_activity WHERE room_id = $1 AND action = 'joined'", room_id,
    )) == sorted([gia, atlas])

    # The author is notified; the reply is announced; posts_count unchanged (replies do not count).
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE to_did = $1 AND from_did = $2 "
        "AND notif_type = 'REPLY' AND ref_post_id = $3", atlas, gia, post,
    ) == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'POST_CREATED' AND agent_did = $1 "
        "AND payload->>'parent_post_id' = $2", gia, str(post),
    ) == 1
    assert await pool.fetchval("SELECT posts_count FROM agents WHERE agent_did = $1", gia) == 0

    # Once per post: later ticks add nothing from GIA here.
    again = await tick(now=due + timedelta(hours=1), reply_seed=seed)
    assert "gia" not in again["replied"] or again["replied"]["gia"] != str(post)
    assert len([r for r in await replies_under(pool, post) if r["author_did"] == gia]) == 1

    # A second invitation on the same topic reuses the room.
    second_at = due + timedelta(hours=2)
    post2 = await insert_post(pool, DEV["nova"], second_at, title="NOVA on onboarding")
    seed2 = find_seed("gia", post2, invite=True)
    plan2 = fr.plan_reply(PERSONAS["gia"], post2, 0, seed2)
    later = await tick(now=second_at + timedelta(minutes=plan2.delay_minutes + 1), reply_seed=seed2)
    assert later["replied"].get("gia") == str(post2)
    assert later["invited"]["gia"] == str(room_id) and later["rooms_created"] == []
    members = {r["agent_did"] for r in await pool.fetch(
        "SELECT agent_did FROM room_participants WHERE room_id = $1", room_id,
    )}
    assert {gia, atlas, DEV["nova"]} <= members


async def test_a_room_an_outsider_named_the_same_is_not_reused(pool, clean):
    outsider_room = await pool.fetchval(
        "INSERT INTO rooms (name, creator_did) VALUES ($1, $2) RETURNING room_id",
        TOPIC_ROOM, OUTSIDER,
    )
    post = await insert_post(pool, DEV["atlas"], NOON - timedelta(hours=4))
    seed = find_seed("gia", post, invite=True)
    summary = await tick(reply_seed=seed)
    assert summary["replied"].get("gia") == str(post)
    assert summary["invited"]["gia"] != str(outsider_room)
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM room_participants WHERE room_id = $1", outsider_room,
    ) == 0


async def test_an_answer_from_the_author_stays_within_two_levels(pool, clean):
    atlas, gia = DEV["atlas"], DEV["gia"]
    post = await insert_post(pool, atlas, NOON - timedelta(hours=6))
    reply = await insert_post(pool, gia, NOON - timedelta(hours=5), title="Re: A post", parent=post)
    # Find a seed where ATLAS answers GIA's reply; nobody else may (rules), whatever the dice.
    seed = next(
        f"a{i}" for i in range(10_000)
        if fr.plan_reply(PERSONAS["atlas"], reply, 1, f"a{i}").wants
        and not any(fr.plan_reply(PERSONAS[o], post, 0, f"a{i}").wants
                    for o in FOUNDER_NAMES if o not in ("atlas", "gia"))
    )
    summary = await tick(reply_seed=seed)
    assert summary["replied"].get("atlas") == str(reply)
    (answer,) = await replies_under(pool, reply)
    assert answer["author_did"] == atlas and "GIA" in answer["content"]
    # Nothing ever goes under the answer (depth 2), whatever the seed.
    for i in range(5):
        await tick(now=NOON + timedelta(hours=1 + i), reply_seed=f"z{i}")
    assert await replies_under(pool, answer["post_id"]) == []


# ── Limits, quiet hours, moderation, the guard ────────────────────────────────

async def test_a_founder_at_the_hourly_reply_limit_does_not_reply(pool, clean):
    gia = DEV["gia"]
    post = await insert_post(pool, DEV["atlas"], NOON - timedelta(hours=4))
    seed = find_seed("gia", post, invite=False)
    other = await insert_post(pool, DEV["nova"], NOON - timedelta(hours=10), title="other")
    for i in range(60):
        await insert_post(pool, gia, NOON - timedelta(minutes=55) + timedelta(seconds=i),
                          title="Re", parent=other, content=f"reply {i}")
    summary = await tick(reply_seed=seed)
    assert summary["reply_limited"] == {"gia": "60/hour"}
    assert await replies_under(pool, post) == []


async def test_a_quiet_founder_does_not_reply(pool, clean):
    # GIA is quiet 03:00–09:00 UTC.
    at = NOON.replace(hour=5)
    post = await insert_post(pool, DEV["atlas"], at - timedelta(hours=4))
    seed = find_seed("gia", post, invite=False)
    summary = await tick(now=at, reply_seed=seed)
    assert "gia" not in summary["replied"]
    assert await replies_under(pool, post) == []


async def test_a_held_reply_is_hidden_and_not_announced(pool, clean, monkeypatch):
    atlas, gia = DEV["atlas"], DEV["gia"]
    post = await insert_post(pool, atlas, NOON - timedelta(hours=4))
    seed = find_seed("gia", post, invite=False)
    monkeypatch.setattr(
        fh, "compose_reply",
        lambda *a, **k: GeneratedPost("Re: A post", SOLICITATION, "template", ()),
    )
    summary = await tick(reply_seed=seed)
    assert summary["reply_held"] == ["gia"]
    (reply,) = await replies_under(pool, post)
    assert reply["hidden_at"] is not None
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE from_did = $1", gia,
    ) == 0
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'POST_CREATED' AND agent_did = $1", gia,
    ) == 0


async def test_a_refused_founder_is_never_answered(pool, clean):
    # The roster offers the outsider's address as THEA's: the guard refuses it,
    # so the outsider's post is not a founder post and nobody answers it.
    post = await insert_post(pool, OUTSIDER, NOON - timedelta(hours=4))
    roster = {**DEV, "thea": OUTSIDER}
    for i in range(30):
        summary = await tick(roster=roster, reply_seed=f"r{i}")
        assert summary["refused"]["thea"] == "did_mismatch"
    assert await replies_under(pool, post) == []
