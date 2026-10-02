"""
Unit tests: the founder heartbeat tick (Sprint 10, S10-3), the parts that
need no database. The tick itself is proven against real Postgres in
tests/integration/test_founder_heartbeat_db.py.

What is proven here:
  • the flag: only 1/true/yes (any case) switch the tick on; a typo means off
  • with the flag off `run_tick` returns before touching the database, and
    the Celery entry point opens neither pool nor cache
  • an unusable FOUNDER_DIDS stops the tick before the database
  • the S9-8a limits are read from the route's own limiter callables
  • the cadence: never posted → due at once (outside the quiet window); the
    gap is inside the persona's mean ± jitter, the same for the same last
    post on every call, and different for different founders / posts
  • the beat schedule runs the heartbeat every 5 minutes next to maintenance
  • the standalone runner closes pool and cache even when the tick fails
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.config import Settings
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.jobs import founder_heartbeat as fh
from src.jobs.celery_app import FOUNDER_HEARTBEAT_INTERVAL_SECONDS, celery_app

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)   # no founder is quiet at 12:00 UTC


def _settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


# ── The flag ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", " yes "])
def test_flag_on_values(value):
    assert fh.heartbeat_enabled(_settings(founder_heartbeat_enabled=value)) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "ture", "on", "enabled", "y", None])
def test_flag_off_values(value):
    assert fh.heartbeat_enabled(_settings(founder_heartbeat_enabled=value or "")) is False


def test_flag_defaults_off_and_a_bad_value_cannot_stop_boot(monkeypatch):
    assert _settings().founder_heartbeat_enabled == ""
    monkeypatch.setenv("FOUNDER_HEARTBEAT_ENABLED", "definitely")
    assert fh.heartbeat_enabled(Settings(_env_file=None)) is False


@pytest.mark.asyncio
async def test_run_tick_does_nothing_when_off(monkeypatch):
    def no_db(*a, **kw):   # pragma: no cover - the point is it is not called
        raise AssertionError("run_tick opened a transaction with the flag off")

    monkeypatch.setattr(fh, "transaction", no_db)
    monkeypatch.setattr(fh, "founder_roster", no_db)
    summary = await fh.run_tick(settings=_settings(founder_heartbeat_enabled="false"))
    assert summary["enabled"] is False
    assert summary["skipped"] == "disabled"
    assert summary["posted"] == [] and summary["post_ids"] == {}


@pytest.mark.asyncio
async def test_run_tick_stops_before_the_database_on_a_bad_roster(monkeypatch):
    def no_db(*a, **kw):   # pragma: no cover
        raise AssertionError("run_tick opened a transaction with a bad roster")

    monkeypatch.setattr(fh, "transaction", no_db)
    monkeypatch.setattr(fh, "founder_roster", lambda: (_ for _ in ()).throw(
        fh.RosterConfigError("bad")))
    summary = await fh.run_tick(settings=_settings(founder_heartbeat_enabled="true"))
    assert summary["enabled"] is True
    assert summary["skipped"] == "roster"


@pytest.mark.asyncio
async def test_run_tick_needs_an_aware_clock():
    with pytest.raises(ValueError):
        await fh.run_tick(now=datetime(2026, 10, 5, 12, 0), roster={},
                          settings=_settings(founder_heartbeat_enabled="true"))


# ── Limits ────────────────────────────────────────────────────────────────────

def test_post_limits_are_the_routes_base_limits():
    assert fh.POST_LIMITS == (
        (2, timedelta(minutes=1), "2/minute"),
        (10, timedelta(hours=1), "10/hour"),
        (30, timedelta(days=1), "30/day"),
    )


# ── Cadence ───────────────────────────────────────────────────────────────────

def test_never_posted_means_due_now_unless_quiet():
    atlas = PERSONAS["atlas"]                 # quiet 22:00–05:00 UTC
    assert fh.next_post_due(atlas, None) is None
    assert fh.is_due(atlas, None, NOON) is True
    assert fh.is_due(atlas, None, NOON.replace(hour=23)) is False


def test_gap_is_inside_the_persona_range_and_deterministic():
    post_id = uuid4()
    for name in FOUNDER_NAMES:
        persona = PERSONAS[name]
        first = fh.next_post_due(persona, (post_id, NOON))
        again = fh.next_post_due(persona, (post_id, NOON))
        assert first == again
        gap = (first - NOON).total_seconds() / 60
        low = persona.mean_post_minutes * (1 - persona.jitter)
        high = persona.mean_post_minutes * (1 + persona.jitter)
        assert low <= gap <= high, name


def test_different_founders_and_posts_draw_different_gaps():
    post_id = uuid4()
    gaps = {fh.next_post_due(PERSONAS[n], (post_id, NOON)) for n in FOUNDER_NAMES}
    assert len(gaps) == len(FOUNDER_NAMES)
    quinn = PERSONAS["quinn"]
    assert fh.next_post_due(quinn, (uuid4(), NOON)) != fh.next_post_due(quinn, (uuid4(), NOON))


def test_due_once_the_gap_has_passed():
    quinn = PERSONAS["quinn"]                 # mean 120 min ± 50 %, quiet 20:00–03:00
    last = (uuid4(), NOON)
    due_at = fh.next_post_due(quinn, last)
    assert fh.is_due(quinn, last, NOON) is False
    assert fh.is_due(quinn, last, due_at - timedelta(seconds=1)) is False
    assert fh.is_due(quinn, last, due_at) is True
    assert fh.is_due(quinn, last, due_at + timedelta(hours=1)) is True


# ── Celery wiring ─────────────────────────────────────────────────────────────

def test_beat_runs_the_heartbeat_every_5_minutes():
    assert FOUNDER_HEARTBEAT_INTERVAL_SECONDS == 300.0 == fh.HEARTBEAT_INTERVAL_SECONDS
    assert celery_app.conf.beat_schedule["founder-heartbeat"] == {
        "task": "jobs.founder_heartbeat",
        "schedule": 300.0,
    }
    assert "jobs.founder_heartbeat" in celery_app.tasks


def test_lock_key_is_not_the_trust_replay_key():
    from src.services.reputation import TRUST_REPLAY_LOCK_KEY
    assert fh.HEARTBEAT_LOCK_KEY != TRUST_REPLAY_LOCK_KEY


def test_standalone_run_opens_nothing_when_off():
    calls = []
    with (
        patch.object(fh, "heartbeat_enabled", return_value=False),
        patch.object(fh, "init_pool", new=AsyncMock(side_effect=lambda: calls.append("init"))),
        patch.object(fh, "run_tick", new=AsyncMock(side_effect=lambda: calls.append("tick"))),
    ):
        summary = fh.founder_heartbeat()
    assert calls == []
    assert summary["skipped"] == "disabled" and summary["enabled"] is False


def test_standalone_run_closes_pool_and_cache_even_on_error():
    calls = []
    with (
        patch.object(fh, "heartbeat_enabled", return_value=True),
        patch.object(fh, "init_pool", new=AsyncMock(side_effect=lambda: calls.append("init"))),
        patch.object(fh, "run_tick", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(fh, "close_cache", new=AsyncMock(side_effect=lambda: calls.append("cache"))),
        patch.object(fh, "close_pool", new=AsyncMock(side_effect=lambda: calls.append("pool"))),
        pytest.raises(RuntimeError),
    ):
        fh.founder_heartbeat()
    assert calls == ["init", "cache", "pool"]
