"""
Integration tests: the scheduled maintenance job (src/jobs/scheduled_maintenance.py)
against REAL local Postgres. Sprint 9, S9-9.

What is proven:
  • one run applies the recorded trust events: scores move apart (not all
    the same), each event is written to the history, a second run changes
    nothing
  • several runs at once apply each event exactly once (advisory lock)
  • a proposal whose voting period is over is closed by the run
  • one part failing does not stop the other
  • the job runs end to end as its own process (own pool, own event loop)

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from src.services.reputation import EVENT_WEIGHTS

from .conftest import PG_PORT, PG_USER, smoke
from .test_governance_db import end_voting, propose, proposal_row

pytestmark = pytest.mark.integration   # skipped unless --db is given

_PLATFORM_DIR = Path(__file__).resolve().parents[2]


async def _trusted(agents, pool, name: str, score: float = 0.5):
    agent = await agents(name, 1_000)
    await pool.execute(
        "UPDATE agents SET trust_score = $1 WHERE agent_id = $2", score, agent.agent_id,
    )
    return agent


async def _score(pool, agent) -> float:
    return float(await pool.fetchval(
        "SELECT trust_score FROM agents WHERE agent_id = $1", agent.agent_id,
    ))


async def _history(pool, agent) -> int:
    return await pool.fetchval(
        "SELECT COUNT(*) FROM agent_reputation_history WHERE agent_id = $1", agent.agent_id,
    )


async def _recorded(pool, agent, event_type: str) -> None:
    """One recorded trust event, as services/reputation.record_event stores it.
    Written directly: these tests are about applying events, not about which
    events may be recorded (tests/integration/test_trust_farming_db.py)."""
    weight = EVENT_WEIGHTS[event_type]
    await pool.execute(
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_weight, "
        "event_value, dedupe_key) VALUES ($1, $2, $3, $4, $4, $5)",
        agent.agent_id, agent.did, event_type, weight, f"test:{uuid4()}",
    )


async def test_one_run_moves_scores_apart_and_a_second_run_changes_nothing(pool, agents):
    from src.jobs.scheduled_maintenance import run_maintenance

    worker = await _trusted(agents, pool, "worker")
    flaky = await _trusted(agents, pool, "flaky")
    quiet = await _trusted(agents, pool, "quiet")
    for _ in range(3):
        await _recorded(pool, worker, "task_completed")
    await _recorded(pool, flaky, "task_failed")

    first = await run_maintenance()

    assert first["errors"] == []
    assert first["trust"]["processed_events"] >= 4
    scores = [await _score(pool, a) for a in (worker, flaky, quiet)]
    assert scores == [pytest.approx(0.65), pytest.approx(0.40), pytest.approx(0.5)]
    assert (await _history(pool, worker), await _history(pool, flaky)) == (3, 1)

    second = await run_maintenance()

    assert second["trust"] == {"processed_events": 0, "updated_agents": 0}
    assert [await _score(pool, a) for a in (worker, flaky, quiet)] == scores
    assert (await _history(pool, worker), await _history(pool, flaky)) == (3, 1)


async def test_runs_at_the_same_time_apply_each_event_once(pool, agents):
    from src.services.reputation import recalculate_agent_trust

    busy = await _trusted(agents, pool, "busy")
    for _ in range(5):
        await _recorded(pool, busy, "task_completed")

    results = await asyncio.gather(*[recalculate_agent_trust() for _ in range(4)])

    assert sum(r["processed_events"] for r in results) >= 5
    assert await _score(pool, busy) == pytest.approx(0.75)
    assert await _history(pool, busy) == 5


async def test_a_proposal_past_its_closing_time_is_closed(client, pool, agents):
    from src.jobs.scheduled_maintenance import run_maintenance

    proposer = await _trusted(agents, pool, "proposer")
    proposal_id = await propose(client, proposer)
    await end_voting(pool, proposal_id)

    summary = await run_maintenance()

    assert summary["errors"] == []
    assert summary["proposals_closed"] >= 1
    assert (await proposal_row(pool, proposal_id))["status"] != "active"


async def test_a_failing_part_does_not_stop_the_other(client, pool, agents, monkeypatch):
    from src.jobs import scheduled_maintenance

    async def broken(**_kwargs):
        raise RuntimeError("trust replay down")

    monkeypatch.setattr(scheduled_maintenance, "recalculate_agent_trust", broken)
    proposer = await _trusted(agents, pool, "proposer")
    proposal_id = await propose(client, proposer)
    await end_voting(pool, proposal_id)

    summary = await scheduled_maintenance.run_maintenance()

    assert summary["errors"] == ["trust"]
    assert summary["trust"] is None
    assert (await proposal_row(pool, proposal_id))["status"] != "active"


async def test_job_runs_end_to_end_as_its_own_process(pool, agents, escrow_db):
    solo = await _trusted(agents, pool, "solo")
    await _recorded(pool, solo, "peer_validation")
    env = {
        **{k: v for k, v in os.environ.items()
           if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS"))},
        "APP_ENV": "development",
        "POSTGRES_HOST": smoke.DB_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_DB": escrow_db,
        "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": smoke.SMOKE_REDIS_URL,
        "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
        "SENTRY_DSN": "",
    }

    out = subprocess.run(
        [sys.executable, "-m", "src.jobs.scheduled_maintenance"],
        cwd=_PLATFORM_DIR, env=env, capture_output=True, text=True, timeout=120,
    )

    assert out.returncode == 0, out.stderr
    assert "'errors': []" in out.stdout
    assert await _score(pool, solo) == pytest.approx(0.53)
    assert await _history(pool, solo) == 1

