"""
Integration tests: one trust number everywhere (Sprint 9, S9-9c), against REAL
local Postgres.

agents.trust_score is replayed from trust_events by the scheduled job
(services/reputation.py) and is what leaderboards, search ordering and vote
weight read. The profile and directory used to show the factor-breakdown
composite instead, which nothing feeds after sign-up: a flat 0.44 for every
agent, whatever the job had worked out. (Sign-up's breakdown row also sets the
starting agents.trust_score to 0.44, via the trg_trust_score_update trigger;
the job moves it from there.)

What is proven (HTTP → router → service → Postgres):
  • after one job run, the profile (`GET /agents/{did}/trust`) shows the
    replayed score, at the top and as the breakdown composite; the factors
    are still there as detail
  • directory search shows the same number it filters and orders by
  • agents that did different things show different numbers (not all 0.44)
  • recalculating the factor breakdown does not reset the replayed score

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from .test_scheduled_maintenance_db import _recorded, _score

pytestmark = pytest.mark.integration   # skipped unless --db is given

_FLAT = 0.44   # the factor composite every agent shows after sign-up


@pytest_asyncio.fixture(autouse=True)
async def no_trust_cache(monkeypatch):
    """Redis is not under test: always read the breakdown from Postgres."""
    import src.main  # noqa: F401  (registers the 'did' path convertor the router needs)
    from src.services import trust_score

    async def _none(*_a, **_k):
        return None

    for name in ("cache_get", "cache_set", "cache_delete"):
        monkeypatch.setattr(trust_score, name, _none)


async def _signed_up(agents, pool, name: str, skill: str):
    """An agent as sign-up leaves it: bootstrap factor breakdown, whose insert
    trigger sets agents.trust_score to the flat composite."""
    agent = await agents(name, 1_000)
    await pool.execute(
        "UPDATE agents SET specialization = $1 WHERE agent_id = $2", skill, agent.agent_id,
    )
    await pool.execute(
        """
        INSERT INTO agent_trust_breakdown (
            agent_did, execution_success, sla_compliance,
            peer_endorsements, audit_transparency, security_record
        ) VALUES ($1, 0.50, 0.50, 0.00, 0.50, 1.00)
        ON CONFLICT (agent_did) DO NOTHING
        """,
        agent.did,
    )
    assert await _score(pool, agent) == pytest.approx(_FLAT)
    return agent


@pytest_asyncio.fixture
async def scored(agents, pool):
    """Three agents with different histories, after one run of the job."""
    from src.jobs.scheduled_maintenance import run_maintenance

    skill = f"s99c-{uuid4().hex[:8]}"
    worker = await _signed_up(agents, pool, "worker", skill)
    flaky = await _signed_up(agents, pool, "flaky", skill)
    quiet = await _signed_up(agents, pool, "quiet", skill)
    for _ in range(3):
        await _recorded(pool, worker, "task_completed")
    await _recorded(pool, flaky, "task_failed")

    result = await run_maintenance()
    assert result["errors"] == []
    return skill, worker, flaky, quiet


async def test_profile_shows_the_replayed_score(client, pool, scored):
    _, worker, flaky, quiet = scored

    shown = {}
    for agent in (worker, flaky, quiet):
        resp = await client.get(f"/agents/{agent.did}/trust")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        replayed = await _score(pool, agent)
        assert body["trust_score"] == pytest.approx(replayed)
        assert body["trust_breakdown"]["composite"] == pytest.approx(replayed)
        # The factors stay, as detail.
        assert body["trust_breakdown"]["execution_success"] == pytest.approx(0.5)
        assert body["trust_breakdown"]["security_record"] == pytest.approx(1.0)
        shown[agent.did] = body["trust_score"]

    assert shown[worker.did] == pytest.approx(_FLAT + 0.15)
    assert shown[flaky.did] == pytest.approx(_FLAT - 0.10)
    assert shown[quiet.did] == pytest.approx(_FLAT)
    assert len({round(v, 4) for v in shown.values()}) == 3


async def test_search_shows_what_it_filters_and_orders_by(client, pool, scored):
    skill, worker, flaky, quiet = scored

    resp = await client.get("/agents/search", params={"skill": skill})
    assert resp.status_code == 200, resp.text
    found = [(a["agent_did"], a["trust_score"]) for a in resp.json()]
    assert [did for did, _ in found] == [worker.did, quiet.did, flaky.did]
    assert [s for _, s in found] == [
        pytest.approx(_FLAT + 0.15), pytest.approx(_FLAT), pytest.approx(_FLAT - 0.10),
    ]

    # Filtering by reputation keeps exactly the agents whose shown score passes.
    resp = await client.get(
        "/agents/search", params={"skill": skill, "min_reputation": 0.5},
    )
    assert resp.status_code == 200, resp.text
    assert [(a["agent_did"], a["trust_score"]) for a in resp.json()] == [
        (worker.did, pytest.approx(_FLAT + 0.15)),
    ]


async def test_a_breakdown_recalc_leaves_the_replayed_score_alone(pool, scored):
    from src.services.trust_score import recalculate_trust_score

    _, worker, _, _ = scored
    before = await _score(pool, worker)

    breakdown = await recalculate_trust_score(worker.did)

    assert breakdown.composite == pytest.approx(_FLAT)
    assert before == pytest.approx(_FLAT + 0.15)
    assert await _score(pool, worker) == pytest.approx(before)
