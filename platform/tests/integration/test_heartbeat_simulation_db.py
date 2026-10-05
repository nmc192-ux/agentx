"""
Integration test: the local 7-day founder heartbeat simulation
(scripts/simulate_heartbeat.py) on REAL local Postgres. Sprint 10, S10-10.

The real tick runs every 5 simulated minutes for 7 days (template text, no
LLM) on its own throwaway database, `agentx_smoke_heartbeat_sim`, and
scripts/heartbeat_report.py then judges the week. Proven:
  • every engine-verifiable acceptance criterion of sprint_10_heartbeat.md
    is PASS: posts every founder-day, distinct cadences, ~30 % replied to,
    rooms shared, DMs answered, paid handoffs, one bounty paid, one proposal
    with ≥ 3 founder votes, within the post limits, trust spread and moved
    only through counted events
  • no tick was skipped, refused a founder, or failed
  • every founder's trust moved over the week

Takes about a minute. Run:
    cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

_spec = importlib.util.spec_from_file_location(
    "simulate_heartbeat",
    Path(__file__).resolve().parents[2] / "scripts" / "simulate_heartbeat.py",
)
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)


async def test_seven_simulated_days_pass_every_criterion():
    out = await sim.run(None, days=7, step=5, set_env=False)

    assert out["start"].weekday() == 0 and out["simulation"]["totals"]["ticks"] == 7 * 288
    assert out["simulation"]["problems"] == {}, out["simulation"]["problems"]

    verdicts = out["report"]["verdicts"]
    assert len(verdicts) == 11
    failed = [v for v in verdicts if v["verdict"] != "PASS"]
    assert not failed, out["rendered"]

    trust = out["report"]["data"]["trust"]
    assert all(t["events"] >= 1 and t["end"] != t["start"] for t in trust.values()), trust


def test_pick_start_fits_the_weeks_bounty_and_proposal():
    from datetime import date, timedelta

    from src.founders.civics import BOUNTY_JUDGE_AFTER, plan_bounty, plan_proposal, week_of

    start = sim.pick_start(date(2026, 10, 3))
    end = start + timedelta(days=7)
    assert start.weekday() == 0 and start.date() > date(2026, 10, 3)
    b, p = plan_bounty(week_of(start)), plan_proposal(week_of(start))
    assert start <= b.at and b.at + BOUNTY_JUDGE_AFTER < end
    assert start <= p.at and p.at + timedelta(hours=48) < end
    assert sim.pick_start(date(2026, 10, 3), days=1).weekday() == 0
