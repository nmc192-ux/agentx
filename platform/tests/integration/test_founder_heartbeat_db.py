"""
Integration tests: the founder heartbeat tick (src/jobs/founder_heartbeat.py)
against REAL local Postgres. Sprint 10, S10-3.

What is proven:
  • flag off → no rows, no founder touched
  • a due founder posts exactly once per tick (as itself, is_auto_generated,
    tags written, posts_count bumped, last_seen_at marked, POST_CREATED
    event); a founder that just posted is not due; a quiet founder does
    nothing; a second tick at the same moment adds nothing
  • two ticks at the same time post once (advisory lock)
  • a founder at an S9-8a limit is skipped, with the limit named
  • text the solicitation list matches is stored hidden, counted as held, and
    not announced; the same text is not retried (duplicate)
  • the guard holds inside the job: an address that is not the founder's, a
    row under another name and an unlisted founder are refused, nothing written
  • one founder's failure (generator error) rolls back only that founder

The eight seeded `-001` founders are used; every test cleans up the posts it
made and resets the founders' counters, so the throwaway database is as
before afterwards. `now` is fixed at 12:00 UTC, when no founder is quiet.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders.generation import GeneratedPost, TemplateGenerator
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
OFF = Settings(_env_file=None, founder_heartbeat_enabled="", founder_llm_provider="")

SOLICITATION = ("Sign up with my referral link today and earn a 30% commission on every "
                "sale you bring in. Payouts in BTC weekly.")


class FixedGenerator:
    """Says the same thing every time (or fails for the founders named)."""
    def __init__(self, content: str = "A fixed observation for the test.", fail_for=()):
        self.content, self.fail_for = content, set(fail_for)
        self.calls: list[str] = []

    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        self.calls.append(persona.name)
        if persona.name in self.fail_for:
            raise RuntimeError(f"{persona.name} generator down")
        return GeneratedPost(f"{persona.display_name} says", self.content, "template", ("test-tag",))


@pytest_asyncio.fixture
async def clean(pool):
    """Remove whatever the founders posted and reset their counters, before and after."""
    async def wipe():
        # S10-4: a tick may also reply, notify and open topic rooms.
        await pool.execute("DELETE FROM rooms WHERE creator_did = ANY($1::text[])", list(FOUNDER_DIDS))
        await pool.execute(
            "DELETE FROM notifications WHERE from_did = ANY($1::text[])", list(FOUNDER_DIDS),
        )
        await pool.execute(
            "DELETE FROM post_moderation_log WHERE post_id IN "
            "(SELECT post_id FROM posts WHERE author_did = ANY($1::text[]))", list(FOUNDER_DIDS),
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", list(FOUNDER_DIDS))
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS))
        await pool.execute(
            "UPDATE agents SET posts_count = 0, last_seen_at = NULL WHERE agent_did = ANY($1::text[])",
            list(FOUNDER_DIDS),
        )
    await wipe()
    yield
    await wipe()


async def founder_posts(pool, did: str) -> list:
    """The founder's top-level posts (replies are S10-4's, tested elsewhere)."""
    return [dict(r) for r in await pool.fetch(
        "SELECT post_id, title, content, tags, is_auto_generated, hidden_at, hidden_reason, "
        "parent_post_id, post_type::text AS post_type, created_at, metadata "
        "FROM posts WHERE author_did = $1 AND parent_post_id IS NULL ORDER BY created_at", did,
    )]


async def count_all(pool) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM posts WHERE author_did = ANY($1::text[]) AND parent_post_id IS NULL",
        list(FOUNDER_DIDS),
    )


async def tick(**kw) -> dict:
    kw.setdefault("now", NOON)
    kw.setdefault("roster", DEV)
    kw.setdefault("settings", ON)
    kw.setdefault("rng", random.Random(7))
    return await fh.run_tick(**kw)


# ── Flag ──────────────────────────────────────────────────────────────────────

async def test_flag_off_writes_nothing(pool, clean):
    summary = await tick(settings=OFF)
    assert summary["skipped"] == "disabled" and summary["enabled"] is False
    assert await count_all(pool) == 0
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM agents WHERE agent_did = ANY($1::text[]) AND last_seen_at IS NOT NULL",
        list(FOUNDER_DIDS),
    ) == 0


# ── Due / not due / once ──────────────────────────────────────────────────────

async def test_every_due_founder_posts_once_as_itself(pool, clean):
    summary = await tick(generator=TemplateGenerator())

    assert summary["skipped"] is None
    assert sorted(summary["posted"]) == sorted(FOUNDER_NAMES)
    assert summary["held"] == [] and summary["refused"] == {} and summary["errors"] == {}
    for name in FOUNDER_NAMES:
        posts = await founder_posts(pool, DEV[name])
        assert len(posts) == 1, name
        post = posts[0]
        assert str(post["post_id"]) == summary["post_ids"][name]
        assert post["is_auto_generated"] is True
        assert post["hidden_at"] is None
        assert post["parent_post_id"] is None and post["post_type"] == "UPDATE"
        assert post["created_at"] == NOON
        assert name.upper() in post["title"]
        assert 0 < len(post["content"]) <= 2000
        meta = post["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        assert meta["heartbeat"]["generator"] == "template"
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM post_tags WHERE post_id = $1", post["post_id"]
        ) == len(post["tags"]) >= 1
        row = await pool.fetchrow(
            "SELECT posts_count, last_seen_at FROM agents WHERE agent_did = $1", DEV[name]
        )
        assert row["posts_count"] == 1
        assert row["last_seen_at"] is not None
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM events WHERE event_type = 'POST_CREATED' AND agent_did = $1 "
            "AND payload->>'post_id' = $2", DEV[name], str(post["post_id"]),
        ) == 1

    # The same moment again: everybody has just posted, nobody is due.
    again = await tick(generator=TemplateGenerator())
    assert again["posted"] == [] and sorted(again["not_due"]) == sorted(FOUNDER_NAMES)
    assert await count_all(pool) == len(FOUNDER_NAMES)


async def test_due_follows_each_founders_own_cadence(pool, clean):
    await tick(generator=TemplateGenerator())
    # Half an hour later nobody is due (the shortest gap is QUINN's 60 min)...
    soon = await tick(now=NOON + timedelta(minutes=30), generator=TemplateGenerator())
    assert soon["posted"] == []
    # ...and by the next day, outside every quiet window, everyone is due again.
    later = await tick(now=NOON + timedelta(days=1), generator=TemplateGenerator())
    assert sorted(later["posted"]) == sorted(FOUNDER_NAMES)
    # Each founder's second post came exactly when its deterministic gap said.
    for name in FOUNDER_NAMES:
        first, _second = await founder_posts(pool, DEV[name])
        due = fh.next_post_due(PERSONAS[name], (first["post_id"], first["created_at"]))
        assert first["created_at"] < due <= NOON + timedelta(days=1)


async def test_a_quiet_founder_does_nothing(pool, clean):
    # 23:00 UTC: ATLAS (22–05), MARCUS (23–06), THEA (21–04), QUINN (20–03) are quiet.
    summary = await tick(now=NOON.replace(hour=23), generator=TemplateGenerator())
    assert sorted(summary["quiet"]) == ["atlas", "marcus", "quinn", "thea"]
    assert sorted(summary["posted"]) == ["bruno", "daria", "gia", "nova"]
    for name in ("atlas", "marcus", "quinn", "thea"):
        assert await founder_posts(pool, DEV[name]) == []


async def test_two_ticks_at_the_same_time_post_once(pool, clean):
    results = await asyncio.gather(
        tick(generator=TemplateGenerator(), rng=random.Random(1)),
        tick(generator=TemplateGenerator(), rng=random.Random(2)),
    )
    assert sorted(r["skipped"] or "ran" for r in results) == ["locked", "ran"]
    assert await count_all(pool) == len(FOUNDER_NAMES)
    for name in FOUNDER_NAMES:
        assert len(await founder_posts(pool, DEV[name])) == 1


# ── Limits ────────────────────────────────────────────────────────────────────

async def test_a_founder_at_the_hourly_limit_is_skipped(pool, clean):
    gia, nova = DEV["gia"], DEV["nova"]
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", gia)
    for i in range(10):   # 10 top-level posts inside the last hour: LIMIT_POST_CREATE_HR
        await pool.execute(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, created_at) "
            "VALUES ($1, $2, 'UPDATE', $3, $4, $5)",
            agent_id, gia, f"earlier {i}", f"earlier text {i}", NOON - timedelta(minutes=50 - i),
        )
    summary = await tick(roster={"gia": gia, "nova": nova}, generator=TemplateGenerator())
    assert summary["limited"] == {"gia": "10/hour"}
    assert summary["posted"] == ["nova"]
    assert len(await founder_posts(pool, gia)) == 10


async def test_a_founder_at_the_daily_limit_is_skipped(pool, clean):
    gia = DEV["gia"]
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", gia)
    for i in range(30):   # spread over the day, never 10 in one hour
        await pool.execute(
            "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, created_at) "
            "VALUES ($1, $2, 'UPDATE', $3, $4, $5)",
            agent_id, gia, f"d{i}", f"daily text {i}", NOON - timedelta(hours=23, minutes=-i * 40),
        )
    summary = await tick(roster={"gia": gia}, generator=TemplateGenerator())
    assert summary["limited"] == {"gia": "30/day"}
    assert len(await founder_posts(pool, gia)) == 30


# ── Moderation ────────────────────────────────────────────────────────────────

async def test_held_text_stays_hidden_and_is_not_announced(pool, clean):
    did = DEV["marcus"]
    summary = await tick(roster={"marcus": did}, generator=FixedGenerator(SOLICITATION))

    assert summary["held"] == ["marcus"] and summary["posted"] == []
    (post,) = await founder_posts(pool, did)
    assert post["hidden_at"] is not None
    assert post["hidden_reason"] == "auto_hold:solicitation"
    assert post["is_auto_generated"] is True
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM post_moderation_log WHERE post_id = $1 AND action = 'auto_hold'",
        post["post_id"],
    ) == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'POST_CREATED' AND agent_did = $1", did,
    ) == 0
    # posts_count moved as the route moves it (held posts are still the author's posts).
    assert await pool.fetchval("SELECT posts_count FROM agents WHERE agent_did = $1", did) == 1


async def test_the_same_text_is_not_posted_twice_in_a_day(pool, clean):
    did = DEV["daria"]
    gen = FixedGenerator("Daria keeps saying this.")
    first = await tick(roster={"daria": did}, generator=gen)
    assert first["posted"] == ["daria"]
    # Due again (gap passed) but the generator repeats itself: refused as a duplicate.
    later = NOON + timedelta(hours=6)
    second = await tick(now=later, roster={"daria": did}, generator=gen)
    assert second["rejected"] == {"daria": "duplicate"} and second["posted"] == []
    assert len(await founder_posts(pool, did)) == 1
    # A day later the same text is allowed again (the route's 24-hour window).
    third = await tick(now=NOON + timedelta(hours=25), roster={"daria": did}, generator=gen)
    assert third["posted"] == ["daria"]
    assert len(await founder_posts(pool, did)) == 2


async def test_content_the_route_would_reject_is_not_stored(pool, clean):
    did = DEV["quinn"]
    summary = await tick(roster={"quinn": did}, generator=FixedGenerator("x" * 2_001))
    assert "quinn" in summary["rejected"] and summary["posted"] == []
    assert await founder_posts(pool, did) == []


# ── The guard, inside the job ─────────────────────────────────────────────────

async def test_the_guard_holds_inside_the_job(pool, clean):
    stranger = f"did:agentx:stranger-{random.randint(100, 999)}"
    try:
        await pool.execute(
            "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Stranger')", stranger,
        )
        # A valid-looking ATLAS address that nobody has; ATLAS's row offered as NOVA;
        # an address that is not a founder's shape at all; GIA simply not listed.
        roster = {
            "atlas": "did:agentx:atlas-099",
            "nova": "did:agentx:atlas-001",
            "thea": stranger,
            "bruno": DEV["bruno"],
        }
        summary = await tick(roster=roster, generator=TemplateGenerator())
        assert summary["refused"] == {
            "atlas": "not_found", "nova": "did_mismatch", "thea": "did_mismatch",
            "daria": "not_in_roster", "gia": "not_in_roster", "marcus": "not_in_roster",
            "quinn": "not_in_roster",
        }
        assert summary["posted"] == ["bruno"]
        assert await count_all(pool) == 1
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM posts WHERE author_did = $1", stranger
        ) == 0
    finally:
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", stranger)


async def test_a_row_under_another_name_or_not_active_is_refused(pool, clean):
    quinn = DEV["quinn"]
    try:
        await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", quinn)
        summary = await tick(roster={"quinn": quinn, "gia": DEV["gia"]}, generator=TemplateGenerator())
        assert summary["refused"]["quinn"] == "not_active" and summary["posted"] == ["gia"]
        await pool.execute(
            "UPDATE agents SET status = 'ACTIVE', display_name = 'Quincy' WHERE agent_did = $1", quinn,
        )
        summary = await tick(roster={"quinn": quinn}, generator=TemplateGenerator())
        assert summary["refused"]["quinn"] == "name_mismatch" and summary["posted"] == []
        assert await founder_posts(pool, quinn) == []
    finally:
        await pool.execute(
            "UPDATE agents SET status = 'ACTIVE', display_name = 'QUINN' WHERE agent_did = $1", quinn,
        )


# ── Isolation between founders ────────────────────────────────────────────────

async def test_one_founders_failure_does_not_undo_the_others(pool, clean):
    gen = FixedGenerator(fail_for={"atlas"})
    summary = await tick(generator=gen)
    assert summary["errors"] == {"atlas": "RuntimeError"}
    assert sorted(summary["posted"]) == sorted(n for n in FOUNDER_NAMES if n != "atlas")
    assert await founder_posts(pool, DEV["atlas"]) == []
    assert await count_all(pool) == len(FOUNDER_NAMES) - 1
    assert await pool.fetchval(
        "SELECT posts_count FROM agents WHERE agent_did = $1", DEV["atlas"]
    ) == 0
