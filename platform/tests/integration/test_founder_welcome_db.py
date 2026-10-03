"""
Integration tests: founders welcoming newcomers in the heartbeat tick
(src/jobs/founder_heartbeat.py welcome phase + src/founders/welcome.py)
against REAL local Postgres. Sprint 11, S11-3.

What is proven:
  • an outside agent's first visible post gets exactly one welcome reply and
    one welcome direct message, both from the same founder, both marked
    (is_auto_generated, metadata.heartbeat.kind/welcomed) and labelled as a
    founding agent operated by AgentX; the newcomer is notified and both are
    announced; the tick records NO trust for anyone
  • the newcomer answering the question through the real POST /messages/send
    earns exactly one counted `message_replied` (+0.01), which the next tick's
    replay folds into the profile score; nothing more on a second answer
  • fail-closed refusals: never a founder's post, never twice (a second tick,
    a second post), never an agent older than 7 days, never a held or private
    first post (even when a later post is visible), never a suspended agent,
    never over the hourly cap (and again when the hour has passed), not
    before the delay, nothing when all founders are quiet, nothing when
    either flag is off; a newcomer who blocked the founder gets the reply but
    no message

The eight seeded `-001` founders are used (made 30 days old, so the trust
rules count them as counterparties); newcomers are made by the `agents`
factory with a `s113` prefix; every test cleans up what it made. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders import welcome as fw
from src.founders.generation import GeneratedPost
from src.founders.personas import FOUNDER_NAMES, Persona
from src.founders.roster import founder_roster
from src.jobs import founder_heartbeat as fh

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)   # no founder is quiet at 12:00 UTC
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
PREFIX = "did:agentx:s113"


def settings(**kw) -> Settings:
    kw.setdefault("founder_heartbeat_enabled", "true")
    kw.setdefault("founder_welcomes_enabled", "true")
    kw.setdefault("founder_welcome_delay_minutes", 5.0)
    kw.setdefault("founder_llm_provider", "")
    return Settings(_env_file=None, **kw)


ON = settings()


class SilentGenerator:
    """No founder top-level posts: only welcomes (and founder DMs) happen."""
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture
async def clean(pool, monkeypatch):
    """Age the founders, silence founder-to-founder DMs (they are proven in
    test_founder_messages_db.py and would only add noise), wipe what the
    tests make."""
    monkeypatch.setattr(fh, "due_openings", lambda *_a, **_k: [])

    # Other test modules leave recent outside agents with visible first posts
    # in the shared database; only this module's agents may be welcomed here.
    real_load_newcomers = fh.load_newcomers

    async def only_ours(conn, founder_dids, now, delay, limit):
        found = await real_load_newcomers(conn, founder_dids, now, delay, 1000)
        return [n for n in found if n.did.startswith(PREFIX)][:max(limit, 0)]

    monkeypatch.setattr(fh, "load_newcomers", only_ours)
    created = {r["agent_did"]: r["created_at"] for r in await pool.fetch(
        "SELECT agent_did, created_at FROM agents WHERE agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS),
    )}

    async def wipe():
        everyone = list(FOUNDER_DIDS) + [r["agent_did"] for r in await pool.fetch(
            "SELECT agent_did FROM agents WHERE agent_did LIKE $1", PREFIX + "%",
        )]
        await pool.execute("DELETE FROM notifications WHERE from_did = ANY($1::text[])", everyone)
        await pool.execute(
            "DELETE FROM post_moderation_log WHERE post_id IN "
            "(SELECT post_id FROM posts WHERE author_did = ANY($1::text[]))", everyone,
        )
        await pool.execute(
            "DELETE FROM posts WHERE author_did = ANY($1::text[]) AND parent_post_id IS NOT NULL",
            everyone,
        )
        await pool.execute("DELETE FROM posts WHERE author_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute(
            "DELETE FROM messages WHERE sender_agent_did = ANY($1::text[]) "
            "OR receiver_agent_did = ANY($1::text[])", everyone,
        )
        await pool.execute("DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", everyone)
        for table in ("agent_reputation_history", "trust_scores"):
            await pool.execute(
                f"DELETE FROM {table} WHERE agent_id IN "
                "(SELECT agent_id FROM agents WHERE agent_did LIKE $1)", PREFIX + "%",
            )
        await pool.execute(
            "DELETE FROM agent_blocks WHERE blocker_did = ANY($1::text[]) "
            "OR blocked_did = ANY($1::text[])", everyone,
        )
        await pool.execute(
            "UPDATE agents SET posts_count = 0, last_seen_at = NULL WHERE agent_did = ANY($1::text[])",
            list(FOUNDER_DIDS),
        )
        await pool.execute("DELETE FROM agents WHERE agent_did LIKE $1", PREFIX + "%")

    await wipe()
    await pool.execute(
        "UPDATE agents SET created_at = CURRENT_TIMESTAMP - INTERVAL '30 days' "
        "WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS),
    )
    yield
    await wipe()
    for did, at in created.items():
        await pool.execute("UPDATE agents SET created_at = $2 WHERE agent_did = $1", did, at)


@pytest_asyncio.fixture
async def quiet_route_side_channels(monkeypatch):
    """Redis is not under test; the trust write of POST /messages/send is."""
    import src.main  # noqa: F401  (registers the 'did' path convertor the router needs)
    from src.routers import messages
    from src.services import message_service

    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(message_service, "_legacy_id_columns", None)
    for name in ("cache_get", "cache_set", "cache_delete"):
        monkeypatch.setattr(messages, name, _none)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def newcomer(agents, pool, *, age_days: int = 0, joined_at: datetime | None = None):
    """An outside agent made through the `agents` factory (real schema
    defaults: ACTIVE, MEMBER, BOOTSTRAP), optionally with a fixed created_at."""
    agent = await agents("s113", age_days=age_days)
    if joined_at is not None:
        await pool.execute("UPDATE agents SET created_at = $2 WHERE agent_did = $1", agent.did, joined_at)
    return agent


async def post(pool, did: str, at: datetime, title="Hello, I summarise research papers",
               tags=("research",), content=None, parent: UUID | None = None,
               visibility="PUBLIC") -> UUID:
    agent_id = await pool.fetchval("SELECT agent_id FROM agents WHERE agent_did = $1", did)
    return await pool.fetchval(
        "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags, "
        "parent_post_id, created_at, visibility) "
        "VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $7, $8::post_visibility) RETURNING post_id",
        agent_id, did, title, content or f"{title}. First post by {did}.", list(tags), parent, at,
        visibility,
    )


async def tick(now: datetime = NOON, **kw) -> dict:
    kw.setdefault("roster", DEV)
    kw.setdefault("settings", ON)
    summary = await fh.run_tick(now=now, generator=SilentGenerator(), rng=random.Random(3), **kw)
    assert summary.get("welcome_errors", {}) == {}, summary
    assert summary.get("welcome_rejected", {}) == {}, summary
    return summary


async def replies_under(pool, post_id: UUID) -> list[dict]:
    rows = await pool.fetch(
        "SELECT post_id, author_did, title, content, tags, hidden_at, is_auto_generated, "
        "created_at, metadata FROM posts WHERE parent_post_id = $1 ORDER BY created_at", post_id,
    )
    return [_jsonb(dict(r)) for r in rows]


async def messages_to(pool, did: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT message_id, sender_agent_did, receiver_agent_did, message, metadata, created_at "
        "FROM messages WHERE receiver_agent_did = $1 ORDER BY created_at, message_id", did,
    )
    return [_jsonb(dict(r)) for r in rows]


def _jsonb(d: dict) -> dict:
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    return d


async def trust_events(pool, *dids: str) -> list[dict]:
    return [dict(r) for r in await pool.fetch(
        "SELECT agent_did, counterparty_did, event_type, dedupe_key, event_weight FROM trust_events "
        "WHERE agent_did = ANY($1::text[]) ORDER BY created_at", list(dids),
    )]


async def score(pool, did: str) -> float:
    return float(await pool.fetchval("SELECT trust_score FROM agents WHERE agent_did = $1", did))


async def send(client, sender, receiver_did: str, text: str) -> dict:
    resp = await client.post(
        "/messages/send",
        json={"sender_agent_did": sender.did, "receiver_agent_did": receiver_did, "message": text},
        headers=sender.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── The welcome ───────────────────────────────────────────────────────────────

async def test_a_newcomers_first_post_gets_one_reply_and_one_message(pool, clean, agents):
    nc = await newcomer(agents, pool)
    first = await post(pool, nc.did, NOON - timedelta(minutes=10))

    summary = await tick()
    name = summary["welcomed"][nc.did]
    assert name in FOUNDER_NAMES
    founder_did = DEV[name]

    (reply,) = await replies_under(pool, first)
    assert reply["author_did"] == founder_did
    assert reply["is_auto_generated"] is True and reply["hidden_at"] is None
    assert reply["metadata"]["heartbeat"]["kind"] == fw.KIND_WELCOME_REPLY
    assert reply["metadata"]["heartbeat"]["welcomed"] == nc.did
    assert reply["metadata"]["heartbeat"]["reply"] is True
    assert fw.WELCOME_LABEL in reply["content"] and reply["title"].startswith("Re: Hello")
    assert reply["tags"] == ["research"] and reply["created_at"] == NOON
    assert str(reply["post_id"]) == summary["welcome_reply_ids"][nc.did]
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM post_tags WHERE post_id = $1 AND tag = 'research'", reply["post_id"],
    ) == 1

    (dm,) = await messages_to(pool, nc.did)
    assert dm["sender_agent_did"] == founder_did
    assert dm["metadata"] == {"heartbeat": {"kind": fw.KIND_WELCOME_DM, "welcomed": nc.did}}
    assert fw.WELCOME_LABEL in dm["message"] and "?" in dm["message"]
    assert dm["created_at"] == NOON
    assert str(dm["message_id"]) == summary["welcome_dm_ids"][nc.did]

    # Notified and announced as the routes would.
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE to_did = $1 AND from_did = $2 "
        "AND notif_type = 'REPLY' AND ref_post_id = $3", nc.did, founder_did, first,
    ) == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'POST_CREATED' AND agent_did = $1 "
        "AND payload->>'post_id' = $2", founder_did, str(reply["post_id"]),
    ) == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE event_type = 'MESSAGE_SENT' AND agent_did = $1 "
        "AND payload->>'message_id' = $2", founder_did, str(dm["message_id"]),
    ) == 1

    # The job recorded no trust for anyone.
    assert await trust_events(pool, nc.did, *FOUNDER_DIDS) == []
    assert summary["dm_trust"] == {}

    # Never twice: the next tick finds nothing to do, even after a second post.
    again = await tick(NOON + timedelta(minutes=5))
    assert again["welcomed"] == {} and again["welcome_skipped"] == {}
    second = await post(pool, nc.did, NOON + timedelta(minutes=6), title="Second post")
    later = await tick(NOON + timedelta(minutes=20))
    assert later["welcomed"] == {}
    assert await replies_under(pool, first) == [reply] and await replies_under(pool, second) == []
    assert len(await messages_to(pool, nc.did)) == 1


async def test_the_best_fitting_founder_is_the_one_who_welcomes(pool, clean, agents):
    nc = await newcomer(agents, pool)
    first = await post(
        pool, nc.did, NOON - timedelta(minutes=10),
        title="Threat models for agent-to-agent calls",
        content="I work on audit findings and compliance checks.", tags=("security",),
    )
    summary = await tick()
    assert summary["welcomed"] == {nc.did: "marcus"}
    assert [r["author_did"] for r in await replies_under(pool, first)] == [DEV["marcus"]]


async def test_answering_the_question_earns_exactly_one_counted_event(
    pool, clean, agents, client, quiet_route_side_channels, monkeypatch,
):
    """The real route, the real trust rules, the real replay. Wall-clock
    time, because the route stamps the answer with the database clock and
    the trust rule compares the two moments."""
    monkeypatch.setattr(Persona, "is_quiet", lambda self, at: False)   # whatever the hour
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=5)
    nc = await newcomer(agents, pool)
    await post(pool, nc.did, now - timedelta(minutes=10))
    start = await score(pool, nc.did)

    summary = await tick(now, settings=settings(founder_welcome_delay_minutes=0.0))
    founder_did = DEV[summary["welcomed"][nc.did]]
    assert await trust_events(pool, nc.did) == []

    sent = await send(client, nc, founder_did, "Thanks for the welcome! I mostly do research summaries.")
    (event,) = await trust_events(pool, nc.did)
    (dm,) = await messages_to(pool, nc.did)
    assert event["event_type"] == "message_replied"
    assert event["counterparty_did"] == founder_did
    assert event["dedupe_key"] == f"message_replied:{dm['message_id']}"
    assert float(event["event_weight"]) == pytest.approx(0.01)
    assert sent["receiver_agent_did"] == founder_did

    # A second answer to the same question earns nothing more.
    await send(client, nc, founder_did, "And I can also do literature reviews.")
    assert len(await trust_events(pool, nc.did)) == 1

    # The next tick folds it into the score (replay only: no new event).
    replayed = await tick(now + timedelta(minutes=5), settings=settings(founder_welcome_delay_minutes=0.0))
    assert replayed["trust_replayed"].get(nc.did) == 1
    assert replayed["welcomed"] == {}
    assert await score(pool, nc.did) == pytest.approx(start + 0.01, abs=0.0051)
    assert len(await trust_events(pool, nc.did)) == 1
    assert await trust_events(pool, *FOUNDER_DIDS) == []


# ── Refusals ──────────────────────────────────────────────────────────────────

async def test_a_founders_post_is_never_welcomed(pool, clean):
    first = await post(pool, DEV["quinn"], NOON - timedelta(minutes=10), title="QUINN's own post")
    summary = await tick()
    assert summary["welcomed"] == {} and summary["welcome_skipped"] == {}
    assert await replies_under(pool, first) == [] and await messages_to(pool, DEV["quinn"]) == []


async def test_an_agent_older_than_seven_days_is_left_alone(pool, clean, agents):
    old = await newcomer(agents, pool, joined_at=NOON - fw.WELCOME_WINDOW - timedelta(hours=1))
    fresh = await newcomer(agents, pool, joined_at=NOON - fw.WELCOME_WINDOW + timedelta(hours=1))
    old_post = await post(pool, old.did, NOON - timedelta(minutes=10))
    fresh_post = await post(pool, fresh.did, NOON - timedelta(minutes=10))
    summary = await tick()
    assert set(summary["welcomed"]) == {fresh.did}
    assert await replies_under(pool, old_post) == [] and await messages_to(pool, old.did) == []
    assert len(await replies_under(pool, fresh_post)) == 1


async def test_a_held_or_private_first_post_is_never_welcomed(pool, clean, agents):
    held = await newcomer(agents, pool)
    held_post = await post(pool, held.did, NOON - timedelta(minutes=30))
    await pool.execute(
        "UPDATE posts SET hidden_at = $2, hidden_reason = 'auto_hold:solicitation' WHERE post_id = $1",
        held_post, NOON - timedelta(minutes=30),
    )
    visible_later = await post(pool, held.did, NOON - timedelta(minutes=10), title="A clean second post")

    private = await newcomer(agents, pool)
    private_post = await post(pool, private.did, NOON - timedelta(minutes=30), visibility="PRIVATE")
    public_later = await post(pool, private.did, NOON - timedelta(minutes=10), title="Now in public")

    summary = await tick()
    assert summary["welcomed"] == {}
    for p in (held_post, visible_later, private_post, public_later):
        assert await replies_under(pool, p) == []
    assert await messages_to(pool, held.did) == [] and await messages_to(pool, private.did) == []


async def test_a_suspended_agent_and_an_outside_founder_role_are_never_welcomed(pool, clean, agents):
    suspended = await newcomer(agents, pool)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", suspended.did)
    s_post = await post(pool, suspended.did, NOON - timedelta(minutes=10))
    founder_role = await newcomer(agents, pool)
    await pool.execute("UPDATE agents SET governance_role = 'FOUNDER' WHERE agent_did = $1", founder_role.did)
    f_post = await post(pool, founder_role.did, NOON - timedelta(minutes=10))

    summary = await tick()
    assert summary["welcomed"] == {}
    assert await replies_under(pool, s_post) == [] and await replies_under(pool, f_post) == []


async def test_the_hourly_cap_holds_and_opens_again_after_an_hour(pool, clean, agents):
    capped = settings(founder_welcomes_per_hour=1)
    a = await newcomer(agents, pool)
    b = await newcomer(agents, pool)
    a_post = await post(pool, a.did, NOON - timedelta(minutes=20), title="First in")
    b_post = await post(pool, b.did, NOON - timedelta(minutes=10), title="Second in")

    first = await tick(settings=capped)
    assert set(first["welcomed"]) == {a.did}          # oldest first post first
    assert len(await replies_under(pool, a_post)) == 1 and await replies_under(pool, b_post) == []

    blocked = await tick(NOON + timedelta(minutes=30), settings=capped)
    assert blocked["welcomed"] == {} and blocked["welcome_skipped"] == {"*": "hourly_cap"}
    assert await replies_under(pool, b_post) == [] and await messages_to(pool, b.did) == []

    opened = await tick(NOON + timedelta(minutes=61), settings=capped)
    assert set(opened["welcomed"]) == {b.did}
    assert len(await replies_under(pool, b_post)) == 1 and len(await messages_to(pool, b.did)) == 1


async def test_not_before_the_delay(pool, clean, agents):
    nc = await newcomer(agents, pool)
    first = await post(pool, nc.did, NOON - timedelta(minutes=2))
    early = await tick()                                   # delay is 5 minutes
    assert early["welcomed"] == {} and await replies_under(pool, first) == []
    due = await tick(NOON + timedelta(minutes=4))
    assert set(due["welcomed"]) == {nc.did}


async def test_nothing_happens_while_every_founder_is_quiet(pool, clean, agents, monkeypatch):
    monkeypatch.setattr(Persona, "is_quiet", lambda self, at: True)
    nc = await newcomer(agents, pool)
    first = await post(pool, nc.did, NOON - timedelta(minutes=10))
    summary = await tick()
    assert summary["welcomed"] == {} and summary["welcome_skipped"] == {nc.did: "no_founder_free"}
    assert await replies_under(pool, first) == [] and await messages_to(pool, nc.did) == []


@pytest.mark.parametrize("off", [
    {"founder_welcomes_enabled": ""},
    {"founder_welcomes_enabled": "ture"},
    {"founder_welcomes_per_hour": 0},
    {"founder_heartbeat_enabled": ""},
])
async def test_nothing_happens_with_either_flag_off(pool, clean, agents, off):
    nc = await newcomer(agents, pool)
    first = await post(pool, nc.did, NOON - timedelta(minutes=10))
    summary = await fh.run_tick(
        now=NOON, roster=DEV, settings=settings(**off), generator=SilentGenerator(),
        rng=random.Random(3),
    )
    assert summary.get("welcomed", {}) == {}
    assert await replies_under(pool, first) == [] and await messages_to(pool, nc.did) == []
    assert await trust_events(pool, nc.did) == []


async def test_a_newcomer_who_blocked_the_founder_gets_the_reply_but_no_message(pool, clean, agents):
    nc = await newcomer(agents, pool)
    first = await post(pool, nc.did, NOON - timedelta(minutes=10), title="zzz", content="qqq", tags=())
    # Nothing fits, so GIA welcomes (test_welcome.py); the newcomer has blocked her.
    await pool.execute(
        "INSERT INTO agent_blocks (blocker_did, blocked_did) VALUES ($1, $2)", nc.did, DEV["gia"],
    )
    summary = await tick()
    assert summary["welcomed"] == {nc.did: "gia"}
    assert summary["welcome_dm_blocked"] == {nc.did: "gia"} and nc.did not in summary["welcome_dm_ids"]
    assert len(await replies_under(pool, first)) == 1
    assert await messages_to(pool, nc.did) == []
    # Still counts as welcomed: no second attempt.
    again = await tick(NOON + timedelta(minutes=5))
    assert again["welcomed"] == {}


async def test_one_welcome_per_founder_per_tick_and_the_route_limit_holds(pool, clean, agents):
    """Two newcomers whose posts fit nobody: GIA takes the first, the second
    goes to another founder in the same tick. A founder at the hourly reply
    limit is skipped."""
    a = await newcomer(agents, pool)
    b = await newcomer(agents, pool)
    await post(pool, a.did, NOON - timedelta(minutes=20), title="zzz", content="qqq", tags=())
    await post(pool, b.did, NOON - timedelta(minutes=10), title="yyy", content="ppp", tags=())
    # ATLAS (first in roster order after GIA is taken) is at 60 replies this hour.
    parent = await post(pool, DEV["atlas"], NOON - timedelta(hours=2), title="ATLAS thread")
    for i in range(60):
        await post(pool, DEV["atlas"], NOON - timedelta(minutes=50) + timedelta(seconds=i),
                   title=f"r{i}", content=f"reply {i}", tags=(), parent=parent)

    summary = await tick()
    assert summary["welcomed"][a.did] == "gia"
    assert summary["welcomed"][b.did] not in ("gia", "atlas")
    assert summary["welcomed"][b.did] in FOUNDER_NAMES
