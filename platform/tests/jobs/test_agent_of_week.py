"""
Unit tests: the Agent of the week job (Sprint 17, S17-3), the parts that need
no database. The job against real Postgres is in
tests/integration/test_spotlight_db.py.

What is proven here:
  • the flag: only 1/true/yes (any case) switch the job on; a typo means off
  • with the flag off nothing touches the database, and a run by hand
    opens neither pool nor cache
  • with the flag on the job picks for the current ISO week (UTC), through
    `pick_for_week`, with the founder roster
  • an unusable FOUNDER_DIDS stops the job before the database
  • the scheduler runs it every hour, behind its flag
"""
from __future__ import annotations

import asyncio

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.config import Settings
from src.founders.roster import RosterConfigError
from src.jobs import agent_of_week as job
from src.jobs.scheduler import AGENT_OF_WEEK_INTERVAL_SECONDS, JOBS


def _settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


ON = dict(agent_of_week_enabled="true")


def _no_db(*a, **kw):   # pragma: no cover - the point is it is not called
    raise AssertionError("the job touched the database")


# ── The flag ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", " yes "])
def test_flag_on_values(value):
    assert job.agent_of_week_enabled(_settings(agent_of_week_enabled=value)) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "ture", "on", "enabled", "y"])
def test_flag_off_values(value):
    assert job.agent_of_week_enabled(_settings(agent_of_week_enabled=value)) is False


def test_flag_defaults_off_and_a_bad_value_cannot_stop_boot(monkeypatch):
    assert _settings().agent_of_week_enabled == ""
    monkeypatch.setenv("AGENT_OF_WEEK_ENABLED", "definitely")
    assert job.agent_of_week_enabled(Settings(_env_file=None)) is False


@pytest.mark.asyncio
async def test_flag_off_touches_nothing(monkeypatch):
    monkeypatch.setattr(job, "transaction", _no_db)
    monkeypatch.setattr(job, "founder_roster", _no_db)
    monkeypatch.setattr(job.spotlight_service, "pick_for_week", _no_db)
    summary = await job.run_agent_of_week(settings=_settings())
    assert summary == {"enabled": False, "week_start": None, "skipped": "disabled", "picked": None}


def test_standalone_run_with_flag_off_opens_no_pool(monkeypatch):
    monkeypatch.delenv("AGENT_OF_WEEK_ENABLED", raising=False)
    monkeypatch.setattr(job, "get_settings", lambda: _settings())
    monkeypatch.setattr(job, "init_pool", _no_db)
    monkeypatch.setattr(job, "close_pool", _no_db)
    monkeypatch.setattr(job, "close_cache", _no_db)
    assert asyncio.run(job._run_standalone())["skipped"] == "disabled"


# ── Flag on ───────────────────────────────────────────────────────────────────

def _fake_transaction(conn):
    @asynccontextmanager
    async def transaction(agent_did=None):
        assert agent_did is None   # system job: no RLS identity
        yield conn
    return transaction


@pytest.mark.asyncio
@pytest.mark.parametrize("now, week", [
    (datetime(2026, 10, 12, 0, 10, tzinfo=timezone.utc), date(2026, 10, 12)),   # Monday 00:10
    (datetime(2026, 10, 18, 23, 10, tzinfo=timezone.utc), date(2026, 10, 12)),  # Sunday night
    # 03:10 on Monday in Karachi is still Sunday in UTC: the week is UTC's.
    (datetime(2026, 10, 12, 3, 10, tzinfo=timezone(timedelta(hours=5))), date(2026, 10, 5)),
])
async def test_flag_on_picks_the_current_utc_week(monkeypatch, now, week):
    conn = object()
    roster = {"Founder": "did:agentx:founder"}
    pick = AsyncMock(return_value={"agent_did": "did:agentx:alice", "score": Decimal("28.0")})
    monkeypatch.setattr(job, "transaction", _fake_transaction(conn))
    monkeypatch.setattr(job, "founder_roster", lambda: roster)
    monkeypatch.setattr(job.spotlight_service, "pick_for_week", pick)

    summary = await job.run_agent_of_week(settings=_settings(**ON), now=now)

    pick.assert_awaited_once_with(conn, week, roster=roster)
    assert summary == {
        "enabled": True, "week_start": week.isoformat(), "skipped": None,
        "picked": {"agent_did": "did:agentx:alice", "score": "28.0"},
    }


@pytest.mark.asyncio
async def test_week_already_settled_reports_no_pick(monkeypatch):
    monkeypatch.setattr(job, "transaction", _fake_transaction(object()))
    monkeypatch.setattr(job, "founder_roster", lambda: {})
    monkeypatch.setattr(job.spotlight_service, "pick_for_week", AsyncMock(return_value=None))
    summary = await job.run_agent_of_week(settings=_settings(**ON))
    assert summary["enabled"] is True and summary["picked"] is None
    assert summary["skipped"] is None


@pytest.mark.asyncio
async def test_bad_roster_stops_before_the_database(monkeypatch):
    def bad_roster():
        raise RosterConfigError("FOUNDER_DIDS is not valid JSON")

    monkeypatch.setattr(job, "transaction", _no_db)
    monkeypatch.setattr(job, "founder_roster", bad_roster)
    monkeypatch.setattr(job.spotlight_service, "pick_for_week", _no_db)
    summary = await job.run_agent_of_week(settings=_settings(**ON))
    assert summary["skipped"] == "roster" and summary["picked"] is None


@pytest.mark.asyncio
async def test_a_failing_pick_raises_and_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(job, "transaction", _fake_transaction(object()))
    monkeypatch.setattr(job, "founder_roster", lambda: {})
    monkeypatch.setattr(job.spotlight_service, "pick_for_week",
                        AsyncMock(side_effect=RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        await job.run_agent_of_week(settings=_settings(**ON))


# ── Registration and schedule ─────────────────────────────────────────────────

def test_scheduler_runs_the_job_every_hour_behind_its_flag():
    entry = {j.name: j for j in JOBS}["agent_of_week"]
    assert AGENT_OF_WEEK_INTERVAL_SECONDS == 3600.0 == entry.interval
    assert entry.run is job.run_agent_of_week
    assert entry.enabled is job.agent_of_week_enabled
