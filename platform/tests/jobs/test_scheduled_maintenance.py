"""
Unit tests: the schedule for S9-9 (Trust Score + governance every
15 minutes). The job itself is tested against real Postgres in
tests/integration/test_scheduled_maintenance_db.py.
"""
from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, patch

import pytest

from src.jobs import scheduled_maintenance
from src.jobs.scheduler import JOBS, MAINTENANCE_INTERVAL_SECONDS


def test_scheduler_runs_the_maintenance_job_every_15_minutes():
    """The other jobs' entries are tested with each job; the scheduler itself in
    tests/jobs/test_scheduler.py."""
    entry = {job.name: job for job in JOBS}["scheduled_maintenance"]
    assert MAINTENANCE_INTERVAL_SECONDS == 900.0 == entry.interval
    assert entry.run is scheduled_maintenance.run_maintenance
    assert {job.name for job in JOBS} == {
        "scheduled_maintenance", "founder_heartbeat", "auto_release", "agent_of_week", "link_cards",
        "media_cleanup",
    }


@pytest.mark.asyncio
async def test_both_parts_run_and_report():
    with (
        patch.object(scheduled_maintenance, "recalculate_agent_trust",
                     new=AsyncMock(return_value={"processed_events": 3, "updated_agents": 2})),
        patch.object(scheduled_maintenance, "finalize_due_proposals",
                     new=AsyncMock(return_value=1)),
    ):
        summary = await scheduled_maintenance.run_maintenance()
    assert summary == {
        "trust": {"processed_events": 3, "updated_agents": 2},
        "proposals_closed": 1,
        "errors": [],
    }


@pytest.mark.asyncio
async def test_governance_failure_does_not_hide_trust_result():
    with (
        patch.object(scheduled_maintenance, "recalculate_agent_trust",
                     new=AsyncMock(return_value={"processed_events": 0, "updated_agents": 0})),
        patch.object(scheduled_maintenance, "finalize_due_proposals",
                     new=AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        summary = await scheduled_maintenance.run_maintenance()
    assert summary["errors"] == ["governance"]
    assert summary["proposals_closed"] is None
    assert summary["trust"] == {"processed_events": 0, "updated_agents": 0}


def test_standalone_run_closes_pool_and_cache_even_on_error():
    calls = []
    with (
        patch.object(scheduled_maintenance, "init_pool", new=AsyncMock(side_effect=lambda: calls.append("init"))),
        patch.object(scheduled_maintenance, "run_maintenance", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(scheduled_maintenance, "close_cache", new=AsyncMock(side_effect=lambda: calls.append("cache"))),
        patch.object(scheduled_maintenance, "close_pool", new=AsyncMock(side_effect=lambda: calls.append("pool"))),
        pytest.raises(RuntimeError),
    ):
        asyncio.run(scheduled_maintenance._run_standalone())
    assert calls == ["init", "cache", "pool"]
