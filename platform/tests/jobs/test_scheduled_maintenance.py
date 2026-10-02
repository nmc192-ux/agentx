"""
Unit tests: the Celery schedule for S9-9 (Trust Score + governance every
15 minutes). The job itself is tested against real Postgres in
tests/integration/test_scheduled_maintenance_db.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.jobs import scheduled_maintenance
from src.jobs.celery_app import MAINTENANCE_INTERVAL_SECONDS, celery_app


def test_beat_runs_only_the_maintenance_job_every_15_minutes():
    schedule = celery_app.conf.beat_schedule
    assert MAINTENANCE_INTERVAL_SECONDS == 900.0
    assert schedule == {
        "scheduled-maintenance": {
            "task": "jobs.scheduled_maintenance",
            "schedule": 900.0,
        },
    }


def test_maintenance_task_is_registered():
    assert "jobs.scheduled_maintenance" in celery_app.tasks


def test_broker_follows_redis_url(monkeypatch):
    from src.jobs import celery_app as module
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "rediss://:pw@example.test:6380/0")
    assert module._broker_url() == "rediss://:pw@example.test:6380/0"
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker.test:6379/3")
    assert module._broker_url() == "redis://broker.test:6379/3"


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
        scheduled_maintenance.scheduled_maintenance()
    assert calls == ["init", "cache", "pool"]
