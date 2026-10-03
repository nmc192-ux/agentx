"""
Unit tests: the automatic-release job's schedule and failure handling
(Sprint 12, S12-7). The releases themselves are tested against real Postgres
in tests/integration/test_auto_release_job_db.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.jobs import auto_release
from src.jobs.celery_app import AUTO_RELEASE_INTERVAL_SECONDS, celery_app


def test_beat_runs_the_auto_release_job_every_15_minutes():
    assert AUTO_RELEASE_INTERVAL_SECONDS == 900.0
    assert celery_app.conf.beat_schedule["auto-release"] == {
        "task": "jobs.auto_release",
        "schedule": 900.0,
    }


def test_auto_release_task_is_registered():
    assert "jobs.auto_release" in celery_app.tasks


def test_the_job_calls_only_the_reviewed_release_functions():
    assert {(svc.__name__, name) for _, svc, name in auto_release._KINDS.values()} == {
        ("src.services.task_service", "release_overdue_result"),
        ("src.services.contract_service", "release_overdue_contract"),
        ("src.services.markets.bounty_service", "release_overdue_bounty"),
    }


@pytest.mark.asyncio
async def test_a_failing_query_does_not_stop_the_other_kinds():
    async def due_ids(query):
        if query is auto_release._DUE_CONTRACTS:
            raise RuntimeError("db down")
        return []

    with patch.object(auto_release, "_due_ids", new=due_ids):
        summary = await auto_release.run_auto_release()
    assert summary == {
        "tasks": {"released": 0, "skipped": 0, "failed": 0},
        "contracts": None,
        "bounties": {"released": 0, "skipped": 0, "failed": 0},
        "errors": ["contracts"],
    }


@pytest.mark.asyncio
async def test_refusals_are_skipped_and_errors_counted_per_item():
    from src.services import task_service

    ids = [uuid4(), uuid4(), uuid4()]
    release = AsyncMock(side_effect=[
        task_service.TaskConflictError("already approved"), RuntimeError("boom"), 100,
    ])
    with (
        patch.object(auto_release, "_due_ids", new=AsyncMock(return_value=ids)),
        patch.object(task_service, "release_overdue_result", new=release),
    ):
        counts = await auto_release._release_kind("tasks")
    assert counts == {"released": 1, "skipped": 1, "failed": 1}
    assert [c.args[0] for c in release.await_args_list] == ids


def test_standalone_run_closes_pool_and_cache_even_on_error():
    calls = []
    with (
        patch.object(auto_release, "init_pool", new=AsyncMock(side_effect=lambda: calls.append("init"))),
        patch.object(auto_release, "run_auto_release", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(auto_release, "close_cache", new=AsyncMock(side_effect=lambda: calls.append("cache"))),
        patch.object(auto_release, "close_pool", new=AsyncMock(side_effect=lambda: calls.append("pool"))),
        pytest.raises(RuntimeError),
    ):
        auto_release.auto_release()
    assert calls == ["init", "cache", "pool"]
