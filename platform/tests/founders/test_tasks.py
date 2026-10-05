"""
Unit tests: the pure rules of paid task handoffs between founders
(src/founders/tasks.py), Sprint 10, S10-6. The money flow itself is proven
against real Postgres in tests/integration/test_founder_tasks_db.py.

What is proven here:
  • plans are fixed per (seed, founder, day) and differ across days and seeds
  • over 4,000 days a founder posts a handoff on about TASK_DAILY_CHANCE of
    them, never for itself, always inside its own active hours, always for a
    skill the peer really has, with a reward inside TASK_REWARD_RANGE, and
    every other founder gets some of its work
  • a plan is due from its moment until its grace runs out, and yesterday's
    late plan is still due after midnight
  • the result delay is inside its range and fixed per (seed, executor, task)
  • the payloads carry the heartbeat marker the job reads back, the text is
    in the founder's voice and inside the length limit
  • the route's task limits are read from the route's own limiter callables
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.founders import tasks as ft
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.jobs import founder_heartbeat as fh

DAY = date(2026, 10, 5)


def test_plans_are_fixed_per_seed_founder_and_day():
    thea = PERSONAS["thea"]
    assert ft.plan_task(thea, DAY, "s") == ft.plan_task(thea, DAY, "s")
    plans = {ft.plan_task(thea, DAY + timedelta(days=i), "s") for i in range(30)}
    assert len(plans) == 30
    assert [ft.plan_task(thea, DAY + timedelta(days=i), "s") for i in range(30)] != \
        [ft.plan_task(thea, DAY + timedelta(days=i), "t") for i in range(30)]
    tid = uuid4()
    assert ft.plan_result_delay(thea, tid, "s") == ft.plan_result_delay(thea, tid, "s")


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_handoffs_follow_the_rules(name):
    persona = PERSONAS[name]
    days = [DAY + timedelta(days=i) for i in range(4000)]
    plans = [ft.plan_task(persona, d, "rate") for d in days]
    share = sum(p.wants for p in plans) / len(plans)
    assert share == pytest.approx(ft.TASK_DAILY_CHANCE, abs=0.03)
    low, high = ft.TASK_REWARD_RANGE
    for d, p in zip(days, plans):
        assert p.peer != name and p.peer in PERSONAS
        assert p.at.date() == d and not persona.is_quiet(p.at)
        assert p.task_type in PERSONAS[p.peer].capabilities
        assert p.peer in ft.founders_with_capability(p.task_type)
        assert low <= p.reward <= high
    assert {p.peer for p in plans} == set(FOUNDER_NAMES) - {name}
    assert {p.reward for p in plans} == set(range(low, high + 1))


def test_due_from_its_moment_until_its_grace_runs_out():
    gia = PERSONAS["gia"]
    seed = next(s for s in (f"g{i}" for i in range(10_000))
                if ft.plan_task(gia, DAY, s).wants)
    plan = ft.plan_task(gia, DAY, seed)
    assert ft.due_task_plans(gia, plan.at - timedelta(seconds=1), seed) == []
    assert ft.due_task_plans(gia, plan.at, seed) == [plan]
    assert ft.due_task_plans(gia, plan.at + ft.TASK_OPEN_GRACE - timedelta(seconds=1), seed) == [plan]
    assert ft.due_task_plans(gia, plan.at + ft.TASK_OPEN_GRACE, seed) == []


def test_yesterdays_late_plan_is_still_due_after_midnight():
    gia = PERSONAS["gia"]   # awake until midnight (quiet 03–09)
    seed, plan = next(
        (s, p) for s in (f"l{i}" for i in range(50_000))
        for p in [ft.plan_task(gia, DAY, s)] if p.wants and p.at.hour >= 22
    )
    after_midnight = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
    assert after_midnight < plan.at + ft.TASK_OPEN_GRACE
    due = ft.due_task_plans(gia, after_midnight, seed)
    assert plan in due and all(p.at <= after_midnight for p in due)
    assert ft.due_task_plans(gia, plan.at + ft.TASK_OPEN_GRACE, seed) == [
        p for p in [ft.plan_task(gia, DAY + timedelta(days=1), seed)]
        if p.wants and p.at <= plan.at + ft.TASK_OPEN_GRACE
    ]


def test_a_founder_that_does_not_want_to_has_nothing_due():
    atlas = PERSONAS["atlas"]
    seed = next(s for s in (f"a{i}" for i in range(10_000))
                if not ft.plan_task(atlas, DAY, s).wants
                and not ft.plan_task(atlas, DAY - timedelta(days=1), s).wants)
    for hour in range(24):
        assert ft.due_task_plans(atlas, datetime(2026, 10, 5, hour, tzinfo=timezone.utc), seed) == []


def test_result_delay_is_inside_its_range():
    quinn = PERSONAS["quinn"]
    delays = [ft.plan_result_delay(quinn, uuid4(), "d") for _ in range(2000)]
    low, high = ft.TASK_RESULT_DELAY_MINUTES
    assert all(low <= d <= high for d in delays)
    assert min(delays) < low + 20 and max(delays) > high - 20


def test_payloads_carry_the_marker_and_the_text_fits():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    marcus, quinn = PERSONAS["marcus"], PERSONAS["quinn"]
    plan = ft.TaskPlan(True, "quinn", now - timedelta(hours=1), "load_testing", 12)
    payload = ft.handoff_payload(marcus, quinn.display_name, "did:agentx:quinn-001", plan, now)
    assert payload["heartbeat"] == {
        "kind": ft.KIND_HANDOFF, "day": "2026-10-05", "at": now.isoformat(),
        "for": "did:agentx:quinn-001", "capability": "load_testing",
    }
    assert payload["brief"].startswith("QUINN, ") and "load testing" in payload["brief"]
    assert "MARCUS" in payload["title"] and len(payload["title"]) <= 120
    assert 0 < len(payload["brief"]) <= ft.TASK_TEXT_MAX_CHARS

    result = ft.result_payload(quinn, "load_testing", random.Random(1), now)
    assert result["heartbeat"] == {"kind": ft.KIND_RESULT, "at": now.isoformat()}
    assert result["summary"].startswith("Done.") and "load testing" in result["summary"]
    assert len(result["summary"]) <= ft.TASK_TEXT_MAX_CHARS

    for name in FOUNDER_NAMES:
        title, brief = ft.compose_task(PERSONAS[name], "PEER", "sql")
        assert "PEER" in brief and "sql" in brief and len(brief) <= ft.TASK_TEXT_MAX_CHARS
        assert "sql" in ft.compose_result(PERSONAS[name], "sql", random.Random(2))


def test_task_limits_are_the_routes_base_limits():
    assert fh.TASK_LIMITS == (
        (5, timedelta(minutes=1), "5/minute"),
        (30, timedelta(hours=1), "30/hour"),
        (100, timedelta(days=1), "100/day"),
    )


def test_bid_confidence_is_auto_accepted_by_the_marketplace():
    # task_service.submit_bid auto-assigns at confidence >= 0.3; a smaller
    # value would leave a funded task open for anyone to take.
    assert ft.TASK_BID_CONFIDENCE >= 0.3
