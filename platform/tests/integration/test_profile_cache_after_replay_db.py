"""
Integration tests: the profile shows a new trust score at once (Sprint 12,
S12-1 / F1), against REAL local Postgres.

GET /agents/{did} caches the whole profile, trust_score included, for
TTL_AGENT_PROFILE seconds. The trust replay (services/reputation.py) used to
clear only the trust cache, so a profile read just before a replay showed the
old score for up to five minutes. It now clears the profile too, but only for
agents whose score actually moved.

Redis is replaced by an in-memory dict (the local cache is disabled), so the
router's real cache_get / cache_set and the replay's cache_delete all meet in
one place.

What is proven (HTTP → router → cache; replay → Postgres → cache):
  • profile read, replay changes the score → the next read shows the new score
  • replay of an event that leaves the score where it was keeps the cached
    profile; an agent with no events is not touched either

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from .test_scheduled_maintenance_db import _recorded, _score

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def cache(monkeypatch):
    """One in-memory cache shared by the profile router and the replay."""
    import src.main  # noqa: F401  (registers the 'did' path convertor the router needs)
    from src.routers import agents as agents_router
    from src.services import reputation

    store: dict[str, object] = {}
    deleted: list[str] = []

    async def _get(key):
        return store.get(key)

    async def _set(key, value, ttl=None):
        store[key] = value

    async def _delete(key):
        deleted.append(key)
        store.pop(key, None)

    for module in (agents_router, reputation):
        for name, fn in (("cache_get", _get), ("cache_set", _set), ("cache_delete", _delete)):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fn)
    store["_deleted"] = deleted
    return store


async def _profile_score(client, agent) -> float:
    resp = await client.get(f"/agents/{agent.did}")
    assert resp.status_code == 200, resp.text
    return resp.json()["trust_score"]


async def _zero_weight_event(pool, agent) -> None:
    """A counted event that does not move the score."""
    await pool.execute(
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_weight, "
        "event_value, dedupe_key) VALUES ($1, $2, 'message_reply', 0.0, 0.0, $3)",
        agent.agent_id, agent.did, f"test:{uuid4()}",
    )


async def test_replay_that_changes_a_score_clears_the_profile(client, pool, agents, cache):
    from src.cache import agent_key
    from src.services.reputation import recalculate_agent_trust

    worker = await agents("s12-1-worker", 1_000)
    before = await _profile_score(client, worker)
    assert agent_key(worker.did) in cache            # profile is cached

    await _recorded(pool, worker, "task_completed")
    result = await recalculate_agent_trust(agent_did=worker.did)
    assert result["processed_events"] == 1

    replayed = await _score(pool, worker)
    assert replayed != pytest.approx(before)
    assert agent_key(worker.did) not in cache        # cleared by the replay
    assert await _profile_score(client, worker) == pytest.approx(replayed)


async def test_replay_that_leaves_a_score_alone_keeps_the_profile(client, pool, agents, cache):
    from src.cache import agent_key
    from src.services.reputation import recalculate_agent_trust

    steady = await agents("s12-1-steady", 1_000)
    idle = await agents("s12-1-idle", 1_000)
    for agent in (steady, idle):
        await _profile_score(client, agent)
    cached_steady = cache[agent_key(steady.did)]
    cached_idle = cache[agent_key(idle.did)]

    await _zero_weight_event(pool, steady)
    result = await recalculate_agent_trust()
    assert result["processed_events"] >= 1

    assert cache[agent_key(steady.did)] is cached_steady
    assert cache[agent_key(idle.did)] is cached_idle
    assert agent_key(steady.did) not in cache["_deleted"]
    assert agent_key(idle.did) not in cache["_deleted"]
