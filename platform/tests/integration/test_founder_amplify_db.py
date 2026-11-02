"""
Integration tests: founders repost and quote real posts in the heartbeat
tick (src/jobs/founder_heartbeat.py + src/founders/amplify.py) against REAL
local Postgres. Layer 1, S3-9.

What is proven:
  • a planned repost goes through `reposts.repost`: one row stamped with the
    tick's clock, one REPOST notification to the author
  • a planned quote is a top-level post with `quote_post_id`, marked
    auto-generated and `kind = quote`, its text passes the claim checker with
    the original as quoted text, the author gets one QUOTE notification, it
    is announced, and it does not reset the founder's posting cadence
  • never a founder's post, never a post that quotes a founder (column or
    legacy metadata), never hidden / private / closed / auto-generated /
    too young / too old posts, never a suspended author, never across a
    block either way
  • at most 2 reposts and 1 quote per founder in 24 hours (and again the
    next day), at most one founder per post
  • nothing at all with the heartbeat switch off

The eight seeded `-001` founders are used; every test cleans up. Run:
    cd platform && .venv/bin/python -m pytest tests/integration/test_founder_amplify_db.py -v --db
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import amplify as fa
from src.founders.personas import FOUNDER_NAMES
from src.founders.roster import founder_roster
from src.founders.truth import claim_problems
from src.jobs import founder_heartbeat as fh

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
OFF = Settings(_env_file=None, founder_heartbeat_enabled="", founder_llm_provider="")
OUT = "did:agentx:outsider-731"
OUT2 = "did:agentx:outsider-732"
ACTOR = "gia"


class SilentGenerator:
    """No top-level posts in these tests: only the amplify phase adds rows."""
    async def generate(self, persona, context, rng, now=None):
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUT, OUT2]

    async def wipe():
        await pool.execute("DELETE FROM agent_blocks WHERE blocker_did = ANY($1::text[]) "
                           "OR blocked_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM reposts WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM notifications WHERE from_did = ANY($1::text[]) "
                           "OR to_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM rooms WHERE creator_did = ANY($1::text[])", everyone)
        await pool.execute(
            "DELETE FROM post_moderation_log WHERE post_id IN "
            "(SELECT post_id FROM posts WHERE author_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM posts WHERE author_did = ANY($1::text[]) AND parent_post_id IS NOT NULL",
            everyone,
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[]) "
                           "AND quote_post_id IS NOT NULL", everyone)
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
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
        await pool.execute("DELETE FROM agents WHERE agent_did = ANY($1::text[])", [OUT, OUT2])

    await wipe()
    MINE.clear()
    for did, name in ((OUT, "Outsider Seven"), (OUT2, "Outsider Eight")):
        await pool.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", did, name)
    yield
    await wipe()


# Posts this test made: the patched decision only ever wants these, so posts
# other test files left in the shared database are never picked.
MINE: set[UUID] = set()


async def insert_post(pool, did: str, at: datetime, *, title="Onboarding notes",
                      tags=("onboarding-friction",), visibility="PUBLIC", auto=False,
                      quote: UUID | None = None, metadata: dict | None = None,
                      parent: UUID | None = None) -> UUID:
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
    post_id = await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags, "
        "visibility, created_at, updated_at, is_auto_generated, quote_post_id, metadata, "
        "parent_post_id) "
        "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6::post_visibility, $7, $7, $8, $9, $10::jsonb, $11) "
        "RETURNING post_id",
        agent_id, did, title, f"{title}: we cut the flow to 3 steps.", list(tags), visibility, at,
        auto, quote, json.dumps(metadata or {}), parent,
    )
    MINE.add(post_id)
    return post_id


def only_actor_wants(monkeypatch, kind: str) -> None:
    """*ACTOR* wants *kind* for every post; no other founder wants anything."""
    monkeypatch.setattr(fa, "plan_amplify",
                        lambda persona, post_id, seed=None:
                        kind if persona.name == ACTOR and post_id in MINE else None)


def everyone_wants(monkeypatch, kind: str) -> None:
    """Every founder wants *kind* for every post: only the rules decide."""
    monkeypatch.setattr(fa, "plan_amplify",
                        lambda persona, post_id, seed=None: kind if post_id in MINE else None)


async def tick(**kw) -> dict:
    kw.setdefault("now", NOON)
    kw.setdefault("roster", DEV)
    kw.setdefault("settings", ON)
    kw.setdefault("rng", random.Random(5))
    kw.setdefault("generator", SilentGenerator())
    return await fh.run_tick(**kw)


async def reposts_of(pool, post_id: UUID) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT agent_did, created_at FROM reposts WHERE post_id = $1", post_id)]


async def quotes_of(pool, post_id: UUID) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT post_id, author_did, title, content, is_auto_generated, metadata, hidden_at, "
        "parent_post_id, created_at FROM posts WHERE quote_post_id = $1 "
        "AND author_did = ANY($2::text[])", post_id, list(FOUNDER_DIDS))]


async def test_a_planned_repost(pool, clean, monkeypatch):
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    only_actor_wants(monkeypatch, fa.KIND_REPOST)
    s = await tick()
    assert s["amplify_errors"] == {}, s
    assert s["reposted"] == {ACTOR: str(pid)}
    rows = await reposts_of(pool, pid)
    assert rows == [{"agent_did": DEV[ACTOR], "created_at": NOON}]
    n = await pool.fetch(
        "SELECT from_did, created_at FROM notifications WHERE to_did = $1 AND notif_type = 'REPOST'",
        OUT)
    assert [dict(r) for r in n] == [{"from_did": DEV[ACTOR], "created_at": NOON}]
    # A later tick does not repost it again (one founder per post, and the row exists).
    s2 = await tick(now=NOON + timedelta(minutes=5))
    assert s2["reposted"] == {}
    assert len(await reposts_of(pool, pid)) == 1


async def test_a_planned_quote(pool, clean, monkeypatch):
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    only_actor_wants(monkeypatch, fa.KIND_QUOTE)
    s = await tick()
    assert s["amplify_errors"] == {} and s["amplify_skipped"] == {}, s
    assert s["quoted"] == {ACTOR: str(pid)}
    [q] = await quotes_of(pool, pid)
    assert str(q["post_id"]) == s["quote_ids"][ACTOR]
    assert q["author_did"] == DEV[ACTOR] and q["parent_post_id"] is None
    assert q["is_auto_generated"] is True and q["hidden_at"] is None and q["created_at"] == NOON
    meta = json.loads(q["metadata"]) if isinstance(q["metadata"], str) else q["metadata"]
    assert meta["heartbeat"]["kind"] == "quote"
    assert meta["quoted_post_id"] == str(pid)
    assert "Outsider Seven" in q["content"]
    original = await pool.fetchrow("SELECT title, content, tags FROM posts WHERE post_id = $1", pid)
    quoted = ("Outsider Seven", original["title"], original["content"], "onboarding friction",
              *original["tags"])
    assert claim_problems(q["content"], (), quoted) == []
    n = await pool.fetch(
        "SELECT from_did, ref_post_id FROM notifications WHERE to_did = $1 AND notif_type = 'QUOTE'",
        OUT)
    assert [(r["from_did"], str(r["ref_post_id"])) for r in n] == [(DEV[ACTOR], str(q["post_id"]))]
    announced = await pool.fetchval(
        "SELECT count(*) FROM events WHERE agent_did = $1 AND event_type = 'POST_CREATED' "
        "AND payload->>'post_id' = $2", DEV[ACTOR], str(q["post_id"]))
    assert announced == 1
    # A quote does not move the founder's own posting rhythm.
    async with pool.acquire() as conn:
        assert await fh.last_top_level_post(conn, DEV[ACTOR]) is None


async def test_a_held_quote_is_not_announced_or_notified(pool, clean, monkeypatch):
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))

    async def hold(conn, post_id, *a):
        await conn.execute("UPDATE posts SET hidden_at = NOW() WHERE post_id = $1", post_id)
        return "test hold"
    monkeypatch.setattr(fh.post_moderation, "hold_if_solicitation", hold)
    only_actor_wants(monkeypatch, fa.KIND_QUOTE)
    s = await tick()
    assert s["quote_held"] == [ACTOR] and s["quoted"] == {ACTOR: str(pid)}
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND notif_type = 'QUOTE'", OUT) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM events WHERE agent_did = $1 AND event_type = 'POST_CREATED'",
        DEV[ACTOR]) == 0


@pytest.mark.parametrize("kind", [fa.KIND_REPOST, fa.KIND_QUOTE])
async def test_never_a_founder_post_or_a_post_quoting_a_founder(pool, clean, kind, monkeypatch):
    founder_post = await insert_post(pool, DEV["atlas"], NOON - timedelta(hours=3))
    founder_real = await insert_post(pool, DEV["atlas"], NOON - timedelta(hours=4), auto=False)
    quotes_founder = await insert_post(pool, OUT, NOON - timedelta(hours=3), quote=founder_post)
    legacy = await insert_post(pool, OUT2, NOON - timedelta(hours=3),
                               metadata={"quoted_post_id": str(founder_real)})
    targets = [founder_post, founder_real, quotes_founder, legacy]
    everyone_wants(monkeypatch, kind)
    s = await tick()
    assert s["amplify_errors"] == {}, s
    assert not set(s["reposted"].values()) & {str(t) for t in targets}
    assert not set(s["quoted"].values()) & {str(t) for t in targets}
    for t in targets:
        assert await reposts_of(pool, t) == [] and await quotes_of(pool, t) == []


@pytest.mark.parametrize("kind", [fa.KIND_REPOST, fa.KIND_QUOTE])
@pytest.mark.parametrize("case", ["hidden", "private", "collective", "closed", "auto", "young",
                                  "old", "suspended", "reply", "blocked_by_me", "blocked_me",
                                  "junk_legacy_ok"])
async def test_only_real_public_posts(pool, clean, kind, case, monkeypatch):
    at = NOON - timedelta(hours=3)
    kw: dict = {}
    if case == "private":
        kw["visibility"] = "PRIVATE"
    elif case == "collective":
        kw["visibility"] = "COLLECTIVE"
    elif case == "auto":
        kw["auto"] = True
    elif case == "young":
        at = NOON - timedelta(minutes=110)
    elif case == "old":
        at = NOON - timedelta(hours=73)
    elif case == "reply":
        kw["parent"] = await insert_post(pool, OUT2, NOON - timedelta(hours=5))
    elif case == "junk_legacy_ok":
        kw["metadata"] = {"quoted_post_id": "not-a-uuid'; DROP TABLE posts; --"}
    pid = await insert_post(pool, OUT, at, **kw)
    if case == "hidden":
        await pool.execute("UPDATE posts SET hidden_at = $2 WHERE post_id = $1", pid, NOON)
    elif case == "closed":
        await pool.execute("UPDATE posts SET status = 'CLOSED' WHERE post_id = $1", pid)
    elif case == "suspended":
        await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", OUT)
    elif case == "blocked_by_me":
        await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                           DEV[ACTOR], OUT)
    elif case == "blocked_me":
        await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                           OUT, DEV[ACTOR])
    if case.startswith("blocked"):
        only_actor_wants(monkeypatch, kind)    # the block is between ACTOR and OUT
    else:
        everyone_wants(monkeypatch, kind)
    s = await tick()
    assert s["amplify_errors"] == {}, s
    done = bool(await reposts_of(pool, pid) or await quotes_of(pool, pid))
    assert done is (case == "junk_legacy_ok"), (case, s)


async def test_block_after_loading_is_refused_by_the_service(pool, clean, monkeypatch):
    """The service re-checks the block inside the write: a candidate that slips
    past the phase's own filter is still refused, nothing is written."""
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    await pool.execute("INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)",
                       OUT, DEV[ACTOR])

    async def nobody(conn, did):
        return set()
    monkeypatch.setattr(fh, "_blocked_with", nobody)
    for kind in (fa.KIND_REPOST, fa.KIND_QUOTE):
        only_actor_wants(monkeypatch, kind)
        s = await tick()
        assert s["amplify_skipped"] == {ACTOR: "blocked"}, s
    assert await reposts_of(pool, pid) == [] and await quotes_of(pool, pid) == []


async def test_daily_caps(pool, clean, monkeypatch):
    for i in range(5):
        await insert_post(pool, OUT if i % 2 else OUT2, NOON - timedelta(hours=3, minutes=i),
                          title=f"Post {chr(65 + i)}")
    only_actor_wants(monkeypatch, fa.KIND_REPOST)
    for k in range(12):   # an hour of ticks
        s = await tick(now=NOON + timedelta(minutes=5 * k))
        assert s["amplify_errors"] == {}, s
    made = await pool.fetchval("SELECT count(*) FROM reposts WHERE agent_did = $1", DEV[ACTOR])
    assert made == fa.REPOSTS_PER_DAY
    # 24 hours after the first, there is room again (posts are still under 72 h old).
    for k in range(3):
        await tick(now=NOON + timedelta(hours=24, minutes=5 * k))
    made = await pool.fetchval("SELECT count(*) FROM reposts WHERE agent_did = $1", DEV[ACTOR])
    assert made == 2 * fa.REPOSTS_PER_DAY


async def test_one_quote_a_day(pool, clean, monkeypatch):
    for i in range(3):
        await insert_post(pool, OUT, NOON - timedelta(hours=3, minutes=i), title=f"Q {chr(65 + i)}")
    only_actor_wants(monkeypatch, fa.KIND_QUOTE)
    for k in range(6):
        s = await tick(now=NOON + timedelta(minutes=5 * k))
        assert s["amplify_errors"] == {}, s
    made = await pool.fetchval(
        "SELECT count(*) FROM posts WHERE author_did = $1 AND quote_post_id IS NOT NULL", DEV[ACTOR])
    assert made == fa.QUOTES_PER_DAY


async def test_one_founder_per_post(pool, clean, monkeypatch):
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    everyone_wants(monkeypatch, fa.KIND_REPOST)
    s = await tick()
    assert s["amplify_errors"] == {}, s
    assert len(await reposts_of(pool, pid)) == 1
    await tick(now=NOON + timedelta(minutes=5))
    assert len(await reposts_of(pool, pid)) == 1


async def test_switch_off_does_nothing(pool, clean, monkeypatch):
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    everyone_wants(monkeypatch, fa.KIND_REPOST)
    s = await tick(settings=OFF)
    assert s["skipped"] == "disabled"
    no_amplify = Settings(_env_file=None, founder_heartbeat_enabled="true",
                          founder_amplify_enabled="false", founder_llm_provider="")
    s = await tick(settings=no_amplify)
    assert s["reposted"] == {} and s["quoted"] == {}
    assert await reposts_of(pool, pid) == [] and await quotes_of(pool, pid) == []


# ── S3-10 review: an outsider cannot speak through a founder ─────────────────

async def test_a_display_name_with_a_mention_means_no_quote_and_no_mention_notification(
    pool, clean, monkeypatch,
):
    await pool.execute("UPDATE agents SET handle = 'outsidereight' WHERE agent_did = $1", OUT2)
    await pool.execute("UPDATE agents SET display_name = '@outsidereight' WHERE agent_did = $1", OUT)
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3))
    only_actor_wants(monkeypatch, fa.KIND_QUOTE)
    s = await tick()
    assert s["amplify_errors"] == {}, s
    assert s["quoted"] == {} and s["quote_ids"] == {}
    assert s["amplify_skipped"] == {ACTOR: "quote_text_refused"}
    assert await quotes_of(pool, pid) == []
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND from_did = ANY($2::text[])",
        OUT2, list(FOUNDER_DIDS)) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM post_mentions WHERE mentioned_did = $1", OUT2) == 0


async def test_a_tag_with_a_mention_or_link_is_not_repeated(pool, clean, monkeypatch):
    await pool.execute("UPDATE agents SET handle = 'outsidereight' WHERE agent_did = $1", OUT2)
    pid = await insert_post(pool, OUT, NOON - timedelta(hours=3),
                            tags=("@outsidereight", "https://evil.example/buy", "#x"))
    only_actor_wants(monkeypatch, fa.KIND_QUOTE)
    s = await tick()
    assert s["amplify_errors"] == {} and s["amplify_skipped"] == {}, s
    [q] = await quotes_of(pool, pid)
    assert "@" not in q["content"] and "#" not in q["content"] and "evil" not in q["content"]
    assert " on this." in q["content"]
    assert await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE to_did = $1 AND notif_type = 'MENTION'", OUT2) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM post_mentions WHERE post_id = $1", q["post_id"]) == 0
    assert await pool.fetchval("SELECT tags FROM posts WHERE post_id = $1", q["post_id"]) == []
