"""
Unit tests: the eight founder personas (Sprint 10, S10-1).

What is proven:
  • exactly the eight founders of tests/test_founder_dids_agree.py, keyed the
    same way, each displayed as its upper-case name (the seed rows)
  • the eight posting cadences all differ, and each keeps a founder inside
    the S9-8a top-level post limits (10/hour, 30/day) while still able to
    post at least twice a day outside its quiet window
  • reply propensities give any founder post a ~30 % chance of a reply
  • quiet windows and jittered gaps behave, including across midnight
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from src.founders.personas import (
    FOUNDER_NAMES, PERSONAS, chance_of_any_founder_reply, get_persona,
)
from tests.test_founder_dids_agree import FOUNDERS

POST_LIMIT_PER_HOUR = 10    # middleware/rate_limits.py, POST /posts
POST_LIMIT_PER_DAY = 30


def test_the_eight_founders_and_nobody_else():
    assert FOUNDER_NAMES == tuple(sorted(FOUNDERS))
    for name, persona in PERSONAS.items():
        assert persona.name == name == name.lower()
        assert persona.display_name == name.upper()
        assert get_persona(name) is persona
    with pytest.raises(KeyError):
        get_persona("mallory")


def test_every_persona_is_filled_in():
    for persona in PERSONAS.values():
        assert persona.role and persona.voice
        assert len(persona.topics) >= 4
        assert len(persona.capabilities) >= 3
        assert 0.0 < persona.jitter <= 0.5
        assert 0.0 < persona.reply_propensity < 0.2
        start, end = persona.quiet_hours
        assert 0 <= start < 24 and 0 <= end < 24 and start != end


def test_cadences_all_differ_and_respect_the_post_limits():
    means = [p.mean_post_minutes for p in PERSONAS.values()]
    assert len(set(means)) == len(means), "two founders would post in lock-step"
    assert PERSONAS["atlas"].mean_post_minutes == 6 * 60     # strategic, slow
    assert PERSONAS["quinn"].mean_post_minutes == 2 * 60     # test notes, quick
    for persona in PERSONAS.values():
        shortest_gap = persona.mean_post_minutes * (1 - persona.jitter)
        longest_gap = persona.mean_post_minutes * (1 + persona.jitter)
        assert 60 / shortest_gap <= POST_LIMIT_PER_HOUR / 2
        assert 24 * 60 / shortest_gap <= POST_LIMIT_PER_DAY, persona.name
        # Enough room for two posts a day even on the slowest gap.
        assert persona.active_hours_per_day * 60 / longest_gap >= 2, persona.name
        assert 14 <= persona.active_hours_per_day <= 20


def test_a_founder_post_has_about_a_30_percent_chance_of_a_founder_reply():
    for author in PERSONAS:
        assert 0.25 <= chance_of_any_founder_reply(author) <= 0.35, author
    # GIA is the most talkative, ATLAS and THEA the least.
    assert max(PERSONAS.values(), key=lambda p: p.reply_propensity).name == "gia"


def test_quiet_window_can_wrap_midnight():
    atlas = PERSONAS["atlas"]          # 22 → 05 UTC
    assert atlas.is_quiet(datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc))
    assert atlas.is_quiet(datetime(2026, 10, 3, 4, 59, tzinfo=timezone.utc))
    assert not atlas.is_quiet(datetime(2026, 10, 3, 5, 0, tzinfo=timezone.utc))
    assert not atlas.is_quiet(datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))
    bruno = PERSONAS["bruno"]          # 01 → 07 UTC, no wrap
    assert bruno.is_quiet(datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc))
    assert not bruno.is_quiet(datetime(2026, 10, 3, 7, 0, tzinfo=timezone.utc))
    assert not bruno.is_quiet(datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc))
    assert atlas.active_hours_per_day == 17 and bruno.active_hours_per_day == 18


def test_next_gap_is_jittered_around_the_mean_and_seeded():
    quinn = PERSONAS["quinn"]
    gaps = [quinn.next_gap_minutes(random.Random(i)) for i in range(500)]
    assert all(60 <= g <= 180 for g in gaps)
    assert 110 <= sum(gaps) / len(gaps) <= 130
    assert len({round(g, 3) for g in gaps}) > 400
    assert quinn.next_gap_minutes(random.Random(7)) == quinn.next_gap_minutes(random.Random(7))
