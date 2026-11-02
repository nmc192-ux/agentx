"""
Integration test: the local 7-day founder heartbeat simulation
(scripts/simulate_heartbeat.py) on REAL local Postgres. Sprint 10, S10-10;
truthful founders rehearsal, TF-9.

The real tick runs every 5 simulated minutes for 7 days (template text, no
LLM) on its own throwaway database, `agentx_smoke_heartbeat_sim`, and
scripts/heartbeat_report.py then judges the week. Proven:
  • every engine-verifiable acceptance criterion of sprint_10_heartbeat.md
    (as amended by TF-9) is PASS: every post states a recorded fact (a
    founder with nothing true to say stays quiet; it no longer posts every
    day), every newcomer welcomed once, distinct cadences, ~30 % replied to,
    rooms shared, DMs answered, paid handoffs, one bounty paid, one proposal
    with ≥ 3 founder votes, within the post limits, trust spread and moved
    only through counted events
  • no tick was skipped, refused a founder, or failed
  • every founder's trust moved over the week
  • the TF-9 rehearsal: every text a founder wrote passes the claim checker
    against the facts it was given, counts about other agents leave the
    founders out (they are MEMBERs by role in production), founders never given a fact posted
    nothing, every newcomer was welcomed once
  • one day with a scripted stand-in for Claude behind the real generator
    and daily budget: its invented numbers and claims of work never reach a
    text, its good answers do, and the calls stay within the cap

Takes about a minute and a half. Run:
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
    assert len(verdicts) == 12
    failed = [v for v in verdicts + out["rehearsal"] if v["verdict"] != "PASS"]
    assert not failed, out["rendered"]
    assert len(out["rehearsal"]) == 5
    assert out["simulation"]["totals"]["welcomed"] == 7 * sim.NEWCOMERS_PER_DAY
    assert out["simulation"]["totals"]["quiet_no_facts"] > 0      # someone had nothing to say

    trust = out["report"]["data"]["trust"]
    assert all(t["events"] >= 1 and t["end"] != t["start"] for t in trust.values()), trust


async def test_one_day_with_a_scripted_model_keeps_every_text_truthful():
    out = await sim.run(None, days=1, step=5, set_env=False, llm="fake")

    assert out["simulation"]["problems"] == {}, out["simulation"]["problems"]
    checks = {c["criterion"]: c for c in out["rehearsal"]}
    assert len(checks) == 6
    failed = [c for c in checks.values() if c["verdict"] != "PASS"]
    assert not failed, out["rendered"]
    truth = out["truth"]
    assert truth["problems"] == [] and sum(truth["checked"].values()) > 0
    # the report's per-window criteria that a single day can meet
    verdict = {v["criterion"]: v["verdict"] for v in out["report"]["verdicts"]}
    for name in ("every founder post states a recorded fact", "every newcomer welcomed once",
                 "no founder exceeds the post limits", "trust moves only through counted events"):
        assert verdict[name] == "PASS", out["rendered"]


async def test_fake_claude_answers_in_turn_and_never_from_outside_the_facts():
    c = sim.FakeClaude()
    post_system = "You write one short social post for a founding agent"
    prompt = {"content": "Persona: X\n<facts>\n- 3 agents joined in the last 24 hours\n</facts>"}
    texts = [(await c.create(model="m", max_tokens=1, system=post_system, messages=[prompt]))
             .content[0].text for _ in range(5)]
    assert texts[0] == texts[1] == ("TITLE: A note from the platform\n"
                                    "3 agents joined in the last 24 hours. What would you ask about that?")
    assert texts[2] == "SKIP" and "4242" in texts[3] and "tested" in texts[4]
    assert c.calls == 5 and c.by_answer == {"good": 2, "skip": 1, "invented": 1, "claim": 1}


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


def test_pick_start_hands_every_founder_paid_work_whatever_the_date():
    """The default start follows the real calendar; whichever day the suite
    runs on, the week picked gives every founder a handoff it can finish
    (else that founder's trust cannot move and the week test fails)."""
    from datetime import date, timedelta

    from src.founders.personas import FOUNDER_NAMES, get_persona
    from src.founders.tasks import plan_task

    for after in (date(2026, 10, 3), date(2026, 11, 2), date(2027, 3, 15), date(2027, 8, 1)):
        start = sim.pick_start(after)
        end = start + timedelta(days=7)
        peers = {p.peer for n in FOUNDER_NAMES for k in range(7)
                 if (p := plan_task(get_persona(n), (start + timedelta(days=k)).date())).wants
                 and start <= p.at < end - timedelta(hours=8)}
        assert peers == set(FOUNDER_NAMES), (after, start, set(FOUNDER_NAMES) - peers)
