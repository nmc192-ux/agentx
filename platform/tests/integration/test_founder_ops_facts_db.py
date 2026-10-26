"""
Integration test: BRUNO's scheduled-job fact (src/founders/ops_facts.py, TF-3)
against REAL local Postgres.

What is proven:
  • the `scheduler_job_runs` query runs on the real schema and counts the
    last runs started in the 24 hours before `now`: ok and failed, failed
    ones named; 'running' rows and rows outside the window are not counted
  • with no runs in the window there is no job fact

Isolation: everything happens inside one transaction that is rolled back,
read at NOW = 15 Jan 2031 so rows written by other tests (dated around the
real clock) fall outside the window.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_founder_ops_facts_db.py -v --db
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.founders import ops_facts as O

pytestmark = pytest.mark.integration   # skipped unless --db is given

NOW = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


async def _seed(conn, rows):
    for name, started, status in rows:
        await conn.execute(
            "INSERT INTO scheduler_job_runs (job_name, last_started_at, last_finished_at, "
            "last_status) VALUES ($1, $2, $2, $3)", name, started, status)


async def test_jobs_fact_exact(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(O.get_settings(), "founder_status_dir", str(tmp_path))
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await _seed(conn, [
                ("tfx_ok_a", NOW - 2 * H, "ok"),
                ("tfx_ok_b", NOW - 23 * H, "ok"),
                ("tfx_broken", NOW - 1 * H, "failed"),
                ("tfx_running", NOW - 1 * H, "running"),
                ("tfx_old", NOW - 25 * H, "failed"),
                ("tfx_later", NOW + 1 * H, "failed"),
            ])
            facts = {f.key: f.text for f in await O.bruno_facts(conn, NOW)}
            assert facts["bruno.jobs_24h"] == (
                "Of 3 scheduled jobs that ran in the last 24 hours, 1 ended in an error "
                "on its last run: tfx broken.")
        finally:
            await tx.rollback()


async def test_no_runs_no_fact(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(O.get_settings(), "founder_status_dir", str(tmp_path))
    async with pool.acquire() as conn:
        facts = await O.bruno_facts(conn, NOW + timedelta(days=3650))
    assert "bruno.jobs_24h" not in {f.key for f in facts}
