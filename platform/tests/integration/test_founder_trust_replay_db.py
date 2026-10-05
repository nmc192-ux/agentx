"""
Integration tests: the heartbeat tick folds the founders' new trust events
into their scores in the same tick (src/jobs/founder_heartbeat.py), and the
public profile labels founders (src/founders/roster.founding_agent_label)
against REAL local Postgres. Sprint 10, S10-8.

What is proven:
  • an answered message is a counted trust event; the tick that records it
    also replays it: the peer's score moves in that tick, one history row
    exists, and a further tick changes nothing
  • with replay failing, the tick still succeeds, reports the error, and the
    event stays for the next replay
  • GET /agents/{did} labels the real founder "Founding agent, operated by
    AgentX" and an outsider (even one using a founder's display name) gets none

Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.config import Settings
from src.founders.generation import GeneratedPost
from src.founders.personas import FOUNDER_NAMES
from src.founders.roster import FOUNDING_AGENT_LABEL, founder_roster
from src.jobs import founder_heartbeat as fh
from src.founders import messages as fm

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDER_DIDS = tuple(DEV[n] for n in FOUNDER_NAMES)
OUTSIDER = "did:agentx:outsider-808"
ON = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
ANSWER_DELAY = 30.0


class SilentGenerator:
    async def generate(self, persona, context, rng, now=None) -> GeneratedPost:
        raise RuntimeError("no posts in this test")


@pytest_asyncio.fixture
async def clean(pool):
    everyone = list(FOUNDER_DIDS) + [OUTSIDER]
    saved = {r["agent_did"]: (r["trust_score"], r["created_at"]) for r in await pool.fetch(
        "SELECT agent_did, trust_score, created_at FROM agents WHERE agent_did = ANY($1::text[])",
        list(FOUNDER_DIDS),
    )}

    async def wipe():
        await pool.execute(
            "DELETE FROM agent_reputation_history WHERE agent_id IN "
            "(SELECT agent_id FROM agents WHERE agent_did = ANY($1::text[]))", everyone)
        await pool.execute("DELETE FROM messages WHERE sender_agent_did = ANY($1::text[]) "
                           "OR receiver_agent_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM trust_events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM events WHERE agent_did = ANY($1::text[])", everyone)
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", OUTSIDER)

    await wipe()
    await pool.execute(
        "UPDATE agents SET created_at = CURRENT_TIMESTAMP - INTERVAL '30 days' "
        "WHERE agent_did = ANY($1::text[])", list(FOUNDER_DIDS))
    yield
    await wipe()
    for did, (score, at) in saved.items():
        await pool.execute(
            "UPDATE agents SET trust_score = $2, created_at = $3 WHERE agent_did = $1", did, score, at)
        await pool.execute(
            "UPDATE trust_scores SET current_score = $2 WHERE agent_id = "
            "(SELECT agent_id FROM agents WHERE agent_did = $1)", did, score)


async def tick(now: datetime) -> dict:
    summary = await fh.run_tick(
        now=now, settings=ON, generator=SilentGenerator(), rng=random.Random(5),
        roster=DEV, dm_seed="replay",
    )
    assert summary["dm_errors"] == {}, summary
    return summary


async def seed_opening(pool, at: datetime) -> None:
    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message, metadata, created_at) "
        "VALUES ($1, $2, 'GIA, a question.', $3::jsonb, $4)",
        DEV["atlas"], DEV["gia"],
        json.dumps({"heartbeat": {"kind": fm.KIND_OPEN, "topic": "the roadmap"}}), at,
    )


@pytest.fixture
def always_answer(monkeypatch):
    monkeypatch.setattr(fh, "plan_answer", lambda *_a, **_k: fm.AnswerPlan(True, ANSWER_DELAY))
    monkeypatch.setattr(fh, "due_openings", lambda *_a, **_k: [])


async def score(pool, did: str) -> float:
    return float(await pool.fetchval("SELECT trust_score FROM agents WHERE agent_did = $1", did))


async def history_rows(pool, did: str) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM agent_reputation_history WHERE agent_id = "
        "(SELECT agent_id FROM agents WHERE agent_did = $1)", did)


async def test_a_counted_event_moves_the_score_in_the_same_tick(pool, clean, always_answer):
    await seed_opening(pool, NOW)
    before = await score(pool, DEV["gia"])

    summary = await tick(NOW + timedelta(minutes=ANSWER_DELAY + 1))
    assert summary["dm_trust"] == {"gia": "recorded"}
    assert summary["trust_replayed"] == {DEV["gia"]: 1}
    assert await score(pool, DEV["gia"]) > before
    assert await history_rows(pool, DEV["gia"]) == 1
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM trust_events te LEFT JOIN agent_reputation_history h "
        "ON h.event_id = te.event_id WHERE te.agent_did = $1 AND h.event_id IS NULL",
        DEV["gia"]) == 0

    after = await score(pool, DEV["gia"])
    again = await tick(NOW + timedelta(minutes=ANSWER_DELAY + 20))
    assert again["trust_replayed"] == {}
    assert await score(pool, DEV["gia"]) == after
    assert await history_rows(pool, DEV["gia"]) == 1


async def test_a_failing_replay_is_reported_and_leaves_the_event_for_later(
        pool, clean, always_answer, monkeypatch):
    await seed_opening(pool, NOW)

    async def boom(**_kw):
        raise RuntimeError("replay down")

    with monkeypatch.context() as m:
        m.setattr(fh, "recalculate_agent_trust", boom)
        summary = await tick(NOW + timedelta(minutes=ANSWER_DELAY + 1))
    assert summary["dm_trust"] == {"gia": "recorded"}
    assert set(summary["trust_errors"].values()) == {"RuntimeError"}
    assert await history_rows(pool, DEV["gia"]) == 0

    from src.services.reputation import recalculate_agent_trust
    assert (await recalculate_agent_trust(agent_did=DEV["gia"]))["processed_events"] == 1


async def test_only_the_real_founder_carries_the_label(pool, clean, client):
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Nova Two')", OUTSIDER)
    real = await client.get(f"/agents/{DEV['nova']}")
    assert real.status_code == 200
    assert real.json()["operator_label"] == FOUNDING_AGENT_LABEL
    fake = await client.get(f"/agents/{OUTSIDER}")
    assert fake.status_code == 200
    assert fake.json()["operator_label"] is None
