"""
Integration tests: the broker-free scheduler and the founder LLM budget
against REAL local Postgres (migration 049; replaces Celery + Redis after the
9 Oct 2026 outage).

What is proven:
  • a job runs once, its run is recorded, and a second call within 90 % of
    its interval (from any process) is skipped as "recent"
  • while one process is running a job (lock held, mid-run), another gets
    "locked" and the job does not start twice
  • a run whose process dies (transaction rolled back) leaves no record, so
    the next tick runs it again
  • a failing job is recorded as failed and the lock is released
  • the founder LLM budget counts in Postgres: exactly *limit* calls a UTC day
    succeed, even when 20 are asked for at once; the next day starts afresh
  • `python -m src.jobs.scheduler --once` runs end to end with
    REDIS_URL=memory:// (no Redis anywhere)

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest

from src.founders.generation import DailyCallBudget
from src.jobs import scheduler as sch
from src.jobs.scheduler import Job

from .conftest import DB_NAME, PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration   # skipped unless --db is given

PLATFORM = Path(__file__).resolve().parents[2]


def _name(tag: str) -> str:
    return f"test_{tag}_{os.getpid()}"


@pytest.fixture
async def clean(pool):
    await pool.execute("DELETE FROM scheduler_job_runs WHERE job_name LIKE 'test_%'")
    await pool.execute("DELETE FROM founder_llm_calls WHERE day < '2000-01-01'")
    yield pool
    await pool.execute("DELETE FROM scheduler_job_runs WHERE job_name LIKE 'test_%'")
    await pool.execute("DELETE FROM founder_llm_calls WHERE day < '2000-01-01'")


def _db(pool):
    @asynccontextmanager
    async def db():
        async with pool.acquire() as conn:
            yield conn
    return db


async def _assert_lock_released(pool, name):
    """The lock went with the transaction: another session can take it."""
    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT pg_try_advisory_xact_lock(hashtextextended('agentx.scheduler.' || $1, 0))",
            name)


async def test_runs_once_then_recent(clean):
    calls = []

    async def run():
        calls.append(1)
        return {"n": len(calls)}

    j = Job(_name("once"), 900.0, run)
    assert await sch.run_job_once(j, db=_db(clean)) == "ok"
    assert await sch.run_job_once(j, db=_db(clean)) == "recent"
    assert calls == [1]
    row = await clean.fetchrow("SELECT * FROM scheduler_job_runs WHERE job_name = $1", j.name)
    assert row["last_status"] == "ok" and row["last_finished_at"] >= row["last_started_at"]

    # Once its interval is over (here: the start moved back), it runs again.
    await clean.execute(
        "UPDATE scheduler_job_runs SET last_started_at = NOW() - INTERVAL '901 seconds' "
        "WHERE job_name = $1", j.name)
    assert await sch.run_job_once(j, db=_db(clean)) == "ok"
    assert calls == [1, 1]


async def test_second_process_is_locked_out_mid_run(clean):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def slow():
        calls.append(1)
        started.set()
        await release.wait()
        return {}

    j = Job(_name("lock"), 60.0, slow)
    first = asyncio.create_task(sch.run_job_once(j, db=_db(clean)))
    await asyncio.wait_for(started.wait(), 10)
    # Another "process": its own connection, same job.
    assert await sch.run_job_once(j, db=_db(clean)) == "locked"
    release.set()
    assert await first == "ok"
    assert calls == [1]
    await _assert_lock_released(clean, j.name)


async def test_dead_process_leaves_no_record_and_the_job_runs_again(clean):
    class Killed(BaseException):
        """Stands in for the process dying mid-run (not caught by the job guard)."""

    async def dies():
        raise Killed

    j = Job(_name("dies"), 900.0, dies)
    with pytest.raises(Killed):
        await sch.run_job_once(j, db=_db(clean))
    assert await clean.fetchval(
        "SELECT count(*) FROM scheduler_job_runs WHERE job_name = $1", j.name) == 0

    async def ok():
        return {}
    assert await sch.run_job_once(Job(j.name, 900.0, ok), db=_db(clean)) == "ok"


async def test_failing_job_is_recorded_and_releases_the_lock(clean):
    async def boom():
        raise RuntimeError("boom")

    j = Job(_name("fail"), 900.0, boom)
    assert await sch.run_job_once(j, db=_db(clean)) == "failed"
    row = await clean.fetchrow("SELECT * FROM scheduler_job_runs WHERE job_name = $1", j.name)
    assert row["last_status"] == "failed"
    await _assert_lock_released(clean, j.name)


# ── Founder LLM budget in Postgres ───────────────────────────────────────────

async def test_budget_counts_in_postgres_under_concurrency(clean):
    day = date(1999, 3, 1)
    from datetime import datetime, timezone
    now = datetime(1999, 3, 1, 12, tzinfo=timezone.utc)
    budget = DailyCallBudget(5, _db(clean))
    results = await asyncio.gather(*(budget.try_spend(now) for _ in range(20)))
    assert results.count(True) == 5
    assert await clean.fetchval("SELECT calls FROM founder_llm_calls WHERE day = $1", day) == 5
    assert await budget.try_spend(now) is False
    assert await budget.try_spend(now.replace(day=2)) is True


async def test_budget_uses_the_app_pool_by_default(clean):
    from datetime import datetime, timezone
    now = datetime(1999, 4, 1, 12, tzinfo=timezone.utc)
    budget = DailyCallBudget(1)
    assert await budget.try_spend(now) is True
    assert await budget.try_spend(now) is False


# ── The command, without Redis ───────────────────────────────────────────────

def test_scheduler_once_runs_with_memory_redis_url(escrow_db):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(PLATFORM),
        "APP_ENV": "development",
        "POSTGRES_HOST": smoke.DB_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_DB": DB_NAME,
        "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": "memory://",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
        "SENTRY_DSN": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "src.jobs.scheduler", "--once"],
        cwd=PLATFORM, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    out = result.stdout.strip().splitlines()[-1]
    # Maintenance and auto-release run (or were run moments ago by another
    # test run); the two flagged jobs are off by default.
    for name in ("scheduled_maintenance", "auto_release"):
        assert f"'{name}': 'ok'" in out or f"'{name}': 'recent'" in out, out
    assert "'founder_heartbeat': 'disabled'" in out
    assert "'agent_of_week': 'disabled'" in out
    assert "ConnectionError" not in result.stderr
