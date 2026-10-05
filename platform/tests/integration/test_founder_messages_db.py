"""
Integration tests: direct messages between founders in the heartbeat tick
(src/jobs/founder_heartbeat.py + src/founders/messages.py) against REAL
local Postgres. Sprint 10, S10-5.

What is proven:
  • one planned conversation: the opening comes at its planned moment, not
    before, from the sender to the peer, marked as a heartbeat message and
    announced; the peer answers on a later tick, after its delay, and that
    answer is one `message_replied` trust event for the peer, keyed on the
    opening, with the opener as counterparty; nothing is sent twice
  • a second conversation between the same two founders on the same day is
    answered but adds no trust (one per pair per day)
  • over three simulated days: at most one opening per founder per day, every
    answer answers a founder's opening once, nobody messages itself, some
    conversations happen and are answered
  • an outside agent's message is never answered; a founder the guard refuses
    is never messaged; a block is honoured; quiet hours and the route's
    30-a-minute limit hold

The eight seeded `-001` founders are used (made 30 days old for the tests, so
the trust rules count them as established); every test cleans up messages,
trust events, posts and events it made. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import messages as fm
from src.founders.generation import GeneratedPost
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh

pytestmark = pytest.mark.integration   # skipped unless --db is given

DAY_START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
OUTSIDER = "did:agentx:outsider-518"


class SilentGenerator:
    """No top-level posts (so no replies either): only messages are written."""
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUTSIDER]
    created = {r["agent_did"]: r["created_at"] for r in await pool.fetch(
        "SELECT agent_did, created_at FROM agents WHERE agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS),
    )}

    async def wipe():
        await pool.execute(
            "DELETE FROM messages WHERE sender_agent_did = ANY($1::text[]) "
            "OR receiver_agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "DELETE FROM agent_blocks WHERE blocker_did = ANY($1::text[])", everyone,
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute(
            "UPDATE agents SET posts_count = 0, last_seen_at = NULL WHERE agent_did = ANY($1::text[])",
            list(FOUNDER_DIDS),
        )
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", OUTSIDER)

    await wipe()
    await pool.execute(
        "UPDATE agents SET created_at = CURRENT_TIMESTAMP - INTERVAL '30 days' "
        "WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Outsider')", OUTSIDER,
    )
    yield
    await wipe()
    for did, at in created.items():
        await pool.execute("UPDATE agents SET created_at = $2 WHERE agent_did = $1", did, at)


ANSWER_DELAY = 30.0


@pytest.fixture
def always_answer(monkeypatch):
    """The answer dice say yes, after ANSWER_DELAY minutes (the rate itself is
    proven in tests/founders/test_messages.py)."""
    monkeypatch.setattr(fh, "plan_answer", lambda *_a, **_k: fm.AnswerPlan(True, ANSWER_DELAY))


async def tick(now: datetime, seed: str, **kw) -> dict:
    kw.setdefault("roster", DEV)
    summary = await fh.run_tick(
        now=now, settings=ON, generator=SilentGenerator(), rng=random.Random(5),
        dm_seed=seed, **kw,
    )
    assert summary["dm_errors"] == {}, summary
    return summary


async def messages(pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT message_id, sender_agent_did, receiver_agent_did, message, metadata, created_at "
        "FROM messages WHERE sender_agent_did = ANY($1::text[]) "
        "OR receiver_agent_did = ANY($1::text[]) ORDER BY created_at, message_id",
        list(FOUNDER_DIDS) + [OUTSIDER],
    )
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        out.append(d)
    return out


async def replied_events(pool) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT agent_did, counterparty_did, dedupe_key FROM trust_events "
        "WHERE event_type = 'message_replied' AND agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS),
    )]


def find_seed(sender: str, *, only: bool = True, day=DAY_START) -> str:
    """A DM seed under which *sender* opens a conversation on *day*, the peer
    is awake for ANSWER_DELAY + 5 minutes after it, and — if *only* — nobody
    else opens one that day."""
    for i in range(50_000):
        seed = f"d{i}"
        plan = fm.plan_dm(PERSONAS[sender], day.date(), seed)
        if not plan.wants:
            continue
        peer = PERSONAS[plan.peer]
        if any(peer.is_quiet(plan.at + timedelta(minutes=m)) for m in (0, ANSWER_DELAY + 5)):
            continue
        if only and any(fm.plan_dm(PERSONAS[o], day.date(), seed).wants
                        for o in FOUNDER_NAMES if o != sender):
            continue
        return seed
    raise AssertionError("no seed found")


# ── One conversation ──────────────────────────────────────────────────────────

async def test_one_opening_and_its_answer_make_one_trust_event(pool, clean, always_answer):
    seed = find_seed("atlas")
    plan = fm.plan_dm(PERSONAS["atlas"], DAY_START.date(), seed)
    atlas, peer = DEV["atlas"], DEV[plan.peer]

    early = await tick(plan.at - timedelta(minutes=1), seed)
    assert early["dm_opened"] == {} and await messages(pool) == []

    opened = await tick(plan.at + timedelta(minutes=1), seed)
    assert opened["dm_opened"] == {"atlas": plan.peer}
    (opening,) = await messages(pool)
    assert opening["sender_agent_did"] == atlas and opening["receiver_agent_did"] == peer
    assert opening["metadata"] == {"heartbeat": {
        "kind": fm.KIND_OPEN, "topic": plan.topic, "day": DAY_START.date().isoformat()}}
    assert opening["created_at"] == plan.at + timedelta(minutes=1)
    assert plan.topic in opening["message"]
    assert str(opening["message_id"]) == opened["dm_ids"]["atlas"]
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'MESSAGE_SENT' AND agent_did = $1 "
        "AND payload->>'message_id' = $2", atlas, str(opening["message_id"]),
    ) == 1

    answer_at = opening["created_at"] + timedelta(minutes=ANSWER_DELAY)
    before = await tick(answer_at - timedelta(minutes=1), seed)
    assert before["dm_answered"] == {}

    answered = await tick(answer_at, seed)
    assert answered["dm_answered"] == {plan.peer: str(opening["message_id"])}
    assert answered["dm_trust"] == {plan.peer: "recorded"}
    rows = await messages(pool)
    assert len(rows) == 2
    answer = rows[1]
    assert answer["sender_agent_did"] == peer and answer["receiver_agent_did"] == atlas
    assert answer["metadata"]["heartbeat"]["kind"] == fm.KIND_ANSWER
    assert answer["metadata"]["heartbeat"]["answers"] == str(opening["message_id"])
    assert await replied_events(pool) == [{
        "agent_did": peer, "counterparty_did": atlas,
        "dedupe_key": f"message_replied:{opening['message_id']}",
    }]

    # Later ticks the same day: no second opening, no second answer.
    for minutes in (5, 60, 180):
        later = await tick(answer_at + timedelta(minutes=minutes), seed)
        assert later["dm_opened"] == {} and later["dm_answered"] == {}
    assert len(await messages(pool)) == 2


async def test_a_second_answer_the_same_day_adds_no_trust(pool, clean, always_answer):
    atlas, gia = DEV["atlas"], DEV["gia"]
    seed = next(
        f"p{i}" for i in range(50_000)
        if not any(fm.plan_dm(PERSONAS[o], DAY_START.date(), f"p{i}").wants for o in FOUNDER_NAMES)
    )

    async def opening(at: datetime) -> UUID:
        return await pool.fetchval(
            "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, metadata, "
            "created_at) VALUES ($1, $2, 'GIA, a question.', $3::jsonb, $4) RETURNING message_id",
            atlas, gia, json.dumps({"heartbeat": {"kind": fm.KIND_OPEN, "topic": "the roadmap"}}),
            at,
        )

    first_at = DAY_START.replace(hour=10)
    first = await opening(first_at)
    t1 = first_at + timedelta(minutes=ANSWER_DELAY + 1)
    s1 = await tick(t1, seed)
    assert s1["dm_answered"] == {"gia": str(first)} and s1["dm_trust"] == {"gia": "recorded"}

    second_at = t1 + timedelta(minutes=10)
    second = await opening(second_at)
    s2 = await tick(second_at + timedelta(minutes=ANSWER_DELAY + 1), seed)
    assert s2["dm_answered"] == {"gia": str(second)}
    assert s2["dm_trust"] == {"gia": "pair_cap"}
    assert len(await replied_events(pool)) == 1


# ── Three simulated days ──────────────────────────────────────────────────────

async def test_three_days_of_ticks_keep_every_rule(pool, clean):
    seed = "three-days"
    for step in range(3 * 24 * 4):   # every 15 minutes
        await tick(DAY_START + timedelta(minutes=15 * step), seed)

    rows = await messages(pool)
    openings = [r for r in rows if r["metadata"]["heartbeat"]["kind"] == fm.KIND_OPEN]
    answers = [r for r in rows if r["metadata"]["heartbeat"]["kind"] == fm.KIND_ANSWER]
    assert openings and answers
    assert all(r["sender_agent_did"] != r["receiver_agent_did"] for r in rows)
    assert all(r["sender_agent_did"] in FOUNDER_DIDS and r["receiver_agent_did"] in FOUNDER_DIDS
               for r in rows)

    # The plans say exactly which openings must exist (all founders always available here).
    expected = {
        (DEV[n], DEV[fm.plan_dm(PERSONAS[n], (DAY_START + timedelta(days=d)).date(), seed).peer],
         (DAY_START + timedelta(days=d)).date())
        for n in FOUNDER_NAMES for d in range(3)
        if fm.plan_dm(PERSONAS[n], (DAY_START + timedelta(days=d)).date(), seed).wants
    }
    got = [(r["sender_agent_did"], r["receiver_agent_did"],
            date.fromisoformat(r["metadata"]["heartbeat"]["day"])) for r in openings]
    assert len(got) == len(set(got)) and set(got) == expected

    by_id = {r["message_id"]: r for r in openings}
    answered = [UUID(r["metadata"]["heartbeat"]["answers"]) for r in answers]
    assert len(answered) == len(set(answered))
    for r in answers:
        o = by_id[UUID(r["metadata"]["heartbeat"]["answers"])]
        assert (r["sender_agent_did"], r["receiver_agent_did"]) == \
            (o["receiver_agent_did"], o["sender_agent_did"])
        assert r["created_at"] > o["created_at"]

    events = await replied_events(pool)
    assert 1 <= len(events) <= len(answers)
    assert len({e["dedupe_key"] for e in events}) == len(events)


# ── Outsiders, the guard, blocks, quiet hours, limits ─────────────────────────

async def test_an_outsiders_message_is_never_answered(pool, clean, always_answer):
    gia = DEV["gia"]
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, metadata, created_at) "
        "VALUES ($1, $2, 'Hi GIA', $3::jsonb, $4)",
        OUTSIDER, gia, json.dumps({"heartbeat": {"kind": fm.KIND_OPEN, "topic": "x"}}),
        DAY_START.replace(hour=10),
    )
    for i in range(12):
        await tick(DAY_START.replace(hour=12) + timedelta(minutes=30 * i), f"o{i}")
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM messages WHERE receiver_agent_did = $1", OUTSIDER,
    ) == 0


async def test_a_refused_founder_is_never_messaged(pool, clean):
    # The roster gives THEA the outsider's address: the guard refuses it, so
    # THEA neither sends nor receives, whatever the plans say.
    roster = {**DEV, "thea": OUTSIDER}
    seed = next(
        f"r{i}" for i in range(50_000)
        if any(fm.plan_dm(PERSONAS[n], DAY_START.date(), f"r{i}").wants
               and fm.plan_dm(PERSONAS[n], DAY_START.date(), f"r{i}").peer == "thea"
               for n in FOUNDER_NAMES if n != "thea")
    )
    for step in range(24 * 2):
        summary = await tick(DAY_START + timedelta(minutes=30 * step), seed, roster=roster)
        assert summary["refused"]["thea"] == "did_mismatch"
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM messages WHERE sender_agent_did = $1 OR receiver_agent_did = $1",
        OUTSIDER,
    ) == 0


async def test_a_block_is_honoured(pool, clean):
    seed = find_seed("atlas")
    plan = fm.plan_dm(PERSONAS["atlas"], DAY_START.date(), seed)
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
        DEV[plan.peer], DEV["atlas"],
    )
    summary = await tick(plan.at + timedelta(minutes=1), seed)
    assert summary["dm_blocked"] == {"atlas": plan.peer} and summary["dm_opened"] == {}
    assert await messages(pool) == []


async def test_quiet_hours_and_the_minute_limit_hold(pool, clean):
    # GIA is quiet 03:00–09:00 UTC: an opening due then waits for 09:00.
    seed = next(
        f"q{i}" for i in range(50_000)
        if (p := fm.plan_dm(PERSONAS["gia"], DAY_START.date(), f"q{i}")).wants and p.at.hour == 9
        and not any(fm.plan_dm(PERSONAS[o], DAY_START.date(), f"q{i}").wants
                    for o in FOUNDER_NAMES if o != "gia")
    )
    plan = fm.plan_dm(PERSONAS["gia"], DAY_START.date(), seed)
    assert (await tick(DAY_START.replace(hour=8, minute=59), seed))["dm_opened"] == {}

    # At the 30-a-minute limit (route figure) GIA sends nothing.
    gia, atlas = DEV["gia"], DEV["atlas"]
    now = plan.at + timedelta(minutes=1)
    for i in range(30):
        await pool.execute(
            "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, created_at) "
            "VALUES ($1, $2, $3, $4)", gia, atlas, f"note {i}", now - timedelta(seconds=30 - i),
        )
    limited = await tick(now, seed)
    assert limited["dm_limited"] == {"gia": "30/minute"} and limited["dm_opened"] == {}

    later = await tick(now + timedelta(minutes=2), seed)
    assert later["dm_opened"] == {"gia": plan.peer}
