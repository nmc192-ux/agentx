"""
Unit tests: who sends a direct message to which founder, when, and whether
the peer answers (src/founders/messages.py, Sprint 10, S10-5). The writing
side is proven against real Postgres in
tests/integration/test_founder_messages_db.py.

What is proven here:
  • the dice are fixed per (seed, founder, day) and (seed, founder, message):
    the same answer every time, a different pattern for a different seed
  • over many days each founder opens on about DM_DAILY_CHANCE of them,
    never to itself, at a moment inside its own active hours, about one of
    the peer's topics
  • answers come at about DM_ANSWER_CHANCE, with a delay in its window
  • the text: inside the limit, names the other founder and the topic
  • the message limits are read from POST /messages/send's own limiter
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from uuid import uuid4

import pytest

from src.founders import messages as fm
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.jobs import founder_heartbeat as fh

DAY = date(2026, 10, 5)


def test_plans_are_fixed_per_seed_founder_and_day():
    gia = PERSONAS["gia"]
    assert fm.plan_dm(gia, DAY, "s") == fm.plan_dm(gia, DAY, "s")
    plans = {fm.plan_dm(gia, DAY + timedelta(days=i), "s") for i in range(30)}
    assert len(plans) == 30
    assert [fm.plan_dm(gia, DAY + timedelta(days=i), "s") for i in range(30)] != \
        [fm.plan_dm(gia, DAY + timedelta(days=i), "t") for i in range(30)]
    mid = uuid4()
    assert fm.plan_answer(gia, mid, "s") == fm.plan_answer(gia, mid, "s")


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_openings_follow_the_rules(name):
    persona = PERSONAS[name]
    days = [DAY + timedelta(days=i) for i in range(4000)]
    plans = [fm.plan_dm(persona, d, "rate") for d in days]
    share = sum(p.wants for p in plans) / len(plans)
    assert share == pytest.approx(fm.DM_DAILY_CHANCE, abs=0.03)
    for d, p in zip(days, plans):
        assert p.peer != name and p.peer in PERSONAS
        assert p.at.date() == d and not persona.is_quiet(p.at)
        assert p.topic in PERSONAS[p.peer].topics
    assert {p.peer for p in plans} == set(FOUNDER_NAMES) - {name}


def test_answers_come_at_their_rate_and_within_their_delay():
    quinn = PERSONAS["quinn"]
    plans = [fm.plan_answer(quinn, uuid4(), "rate") for _ in range(5000)]
    share = sum(p.wants for p in plans) / len(plans)
    assert share == pytest.approx(fm.DM_ANSWER_CHANCE, abs=0.02)
    low, high = fm.DM_ANSWER_DELAY_MINUTES
    assert all(low <= p.delay_minutes <= high for p in plans)
    assert timedelta(minutes=high) < fm.DM_ANSWER_WINDOW


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_the_text_names_the_other_founder_and_the_topic(name):
    persona = PERSONAS[name]
    opening = fm.compose_opening(persona, "ATLAS", "the roadmap")
    assert "ATLAS" in opening and "the roadmap" in opening
    answer = fm.compose_answer(persona, "GIA", "community norms", random.Random(1))
    assert "GIA" in answer and "community norms" in answer
    assert fm.compose_answer(persona, "GIA", None, random.Random(1))   # topic missing: own topic
    assert max(len(opening), len(answer)) <= fm.DM_MAX_CHARS


def test_the_message_limits_come_from_the_route():
    assert [label for _c, _w, label in fh.MESSAGE_LIMITS] == ["30/minute", "500/day"]


def test_an_opening_late_in_the_day_is_still_due_after_midnight():
    nova = PERSONAS["nova"]   # quiet 02–08 UTC: active at 23:00
    seed = next(
        f"m{i}" for i in range(50_000)
        if (p := fm.plan_dm(nova, DAY, f"m{i}")).wants and p.at.hour == 23
    )
    plan = fm.plan_dm(nova, DAY, seed)
    assert fm.due_openings(nova, plan.at - timedelta(seconds=1), seed) == [
        q for q in [fm.plan_dm(nova, DAY - timedelta(days=1), seed)]
        if q.wants and q.at <= plan.at - timedelta(seconds=1) < q.at + fm.DM_OPEN_GRACE
    ]
    assert plan in fm.due_openings(nova, plan.at, seed)
    after_midnight = plan.at.replace(hour=0, minute=30) + timedelta(days=1)
    assert plan in fm.due_openings(nova, after_midnight, seed)
    assert plan not in fm.due_openings(nova, plan.at + fm.DM_OPEN_GRACE, seed)
