"""
Unit tests: the broker-free scheduler (src/jobs/scheduler.py), which replaced
Celery + Redis after the 9 Oct 2026 outage. No database: the connection is a
stand-in that records what it was asked. The real Postgres lock and run
records are proven in tests/integration/test_scheduler_db.py.

What is proven here:
  • the four jobs and their intervals; nothing imports Celery any more
  • a job whose flag is off is skipped without touching the database
  • lock held elsewhere → "locked", the job does not run
  • ran recently (in any process) → "recent", the job does not run
  • otherwise the start is recorded, the job runs, the end is recorded, all
    inside one transaction that holds the lock
  • a failing job is recorded as failed and never raised; a database error
    is reported as "error"; an unreadable flag means off
  • the loop runs every job at start, then again only when its interval is
    over, and stops when asked
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from src.jobs import scheduler as sch
from src.jobs.scheduler import Job

PLATFORM = Path(__file__).resolve().parents[2]


class FakeConn:
    def __init__(self, *, locked=False, recent=False, fail_on=None):
        self.locked, self.recent, self.fail_on = locked, recent, fail_on
        self.log: list[tuple] = []
        self.in_tx = False

    @asynccontextmanager
    async def transaction(self):
        self.in_tx = True
        self.log.append(("BEGIN",))
        try:
            yield
        finally:
            self.in_tx = False
            self.log.append(("END",))

    def _check(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise ConnectionError("database down")
        assert self.in_tx, "every scheduler statement must run inside the transaction"

    async def fetchval(self, sql, *args):
        self._check(sql)
        self.log.append(("fetchval", sql, args))
        if "pg_try_advisory_xact_lock" in sql:
            return not self.locked
        if "last_started_at >" in sql:
            return True if self.recent else None
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self._check(sql)
        self.log.append(("execute", sql, args))


def fake_db(conn):
    @asynccontextmanager
    async def db():
        yield conn
    return db


def _no_db():   # pragma: no cover - the point is it is not called
    raise AssertionError("the scheduler touched the database")


def job(name="j", *, result=None, error=None, enabled=True, calls=None, interval=60.0):
    calls = [] if calls is None else calls

    async def run():
        calls.append(name)
        if error is not None:
            raise error
        return result if result is not None else {"done": True}

    return Job(name, interval, run, (lambda: enabled) if not callable(enabled) else enabled), calls


def _statements(conn):
    return [entry[1] for entry in conn.log if entry[0] in ("fetchval", "execute")]


# ── The schedule ─────────────────────────────────────────────────────────────

def test_the_four_jobs_and_their_intervals():
    assert [(j.name, j.interval) for j in sch.JOBS] == [
        ("scheduled_maintenance", 900.0),
        ("auto_release", 900.0),
        ("founder_heartbeat", 300.0),
        ("agent_of_week", 3600.0),
    ]


def test_celery_is_gone():
    assert importlib.util.find_spec("src.jobs.celery_app") is None
    requirements = (PLATFORM / "requirements.txt").read_text().lower()
    assert "celery" not in requirements
    pattern = re.compile(r"^\s*(import celery|from celery)\b", re.MULTILINE)
    for path in (PLATFORM / "src").rglob("*.py"):
        assert not pattern.search(path.read_text()), path


# ── One run ──────────────────────────────────────────────────────────────────

async def test_disabled_job_touches_nothing():
    j, calls = job(enabled=False)
    assert await sch.run_job_once(j, db=_no_db) == "disabled"
    assert calls == []


async def test_unreadable_flag_means_off():
    def broken():
        raise ValueError("bad flag")
    j, calls = job(enabled=broken)
    assert await sch.run_job_once(j, db=_no_db) == "disabled"
    assert calls == []


async def test_lock_held_elsewhere_skips_the_run():
    conn = FakeConn(locked=True)
    j, calls = job("maint")
    assert await sch.run_job_once(j, db=fake_db(conn)) == "locked"
    assert calls == []
    lock_sql, = [e for e in conn.log if e[0] == "fetchval"]
    assert "pg_try_advisory_xact_lock" in lock_sql[1] and lock_sql[2] == ("maint",)
    assert not any("INSERT" in s or "UPDATE" in s for s in _statements(conn))


async def test_recent_run_skips_the_run():
    conn = FakeConn(recent=True)
    j, calls = job("maint", interval=900.0)
    assert await sch.run_job_once(j, db=fake_db(conn)) == "recent"
    assert calls == []
    recent, = [e for e in conn.log if e[0] == "fetchval" and "last_started_at" in e[1]]
    assert recent[2] == ("maint", 900.0 * sch.RECENT_SHARE)
    assert not any("INSERT" in s or "UPDATE" in s for s in _statements(conn))


async def test_due_job_runs_and_is_recorded_inside_the_lock():
    conn = FakeConn()
    j, calls = job("maint", result={"trust": 3})
    assert await sch.run_job_once(j, db=fake_db(conn)) == "ok"
    assert calls == ["maint"]
    statements = _statements(conn)
    assert "idle_in_transaction_session_timeout" in statements[0]
    assert "pg_try_advisory_xact_lock" in statements[1]
    assert "last_started_at >" in statements[2]
    assert "INSERT INTO scheduler_job_runs" in statements[3]
    assert "UPDATE scheduler_job_runs" in statements[4]
    finish = conn.log[-2]
    assert finish[2][:2] == ("maint", "ok") and json.loads(finish[2][2]) == {"trust": 3}
    assert conn.log[0] == ("BEGIN",) and conn.log[-1] == ("END",)


async def test_failing_job_is_recorded_not_raised():
    conn = FakeConn()
    j, calls = job("maint", error=RuntimeError("boom"))
    assert await sch.run_job_once(j, db=fake_db(conn)) == "failed"
    finish = conn.log[-2]
    assert finish[2][:2] == ("maint", "failed")
    assert json.loads(finish[2][2]) == {"error": "RuntimeError"}


async def test_database_error_is_reported_not_raised():
    for fail_on in ("pg_try_advisory_xact_lock", "INSERT INTO scheduler_job_runs"):
        conn = FakeConn(fail_on=fail_on)
        j, calls = job()
        assert await sch.run_job_once(j, db=fake_db(conn)) == "error"
        assert calls == []


async def test_unserialisable_summary_still_records():
    conn = FakeConn()
    j, _ = job(result={"when": object()})
    assert await sch.run_job_once(j, db=fake_db(conn)) == "ok"
    assert "when" in json.loads(conn.log[-2][2][2])


# ── The loop ─────────────────────────────────────────────────────────────────

async def test_loop_runs_each_job_when_due_and_stops(monkeypatch):
    now = [0.0]
    ran: list[str] = []
    stop = asyncio.Event()

    async def fake_once(j, *, db=None):
        ran.append(j.name)
        if len(ran) >= 5:
            stop.set()
        return "ok"

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        if stop.is_set():
            return
        now[0] += timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr(sch, "run_job_once", fake_once)
    monkeypatch.setattr(sch.asyncio, "wait_for", fake_wait_for)
    fast, _ = job("fast", interval=300.0)
    slow, _ = job("slow", interval=900.0)
    await sch.run_forever((fast, slow), stop, clock=lambda: now[0])
    # t=0 both, t=300 fast, t=600 fast, t=900 fast (then stop before slow).
    assert ran == ["fast", "slow", "fast", "fast", "fast"]
    assert now[0] == 900.0


# ── RF-2 (T1 review): a hung job cannot stop the others ──────────────────────

async def test_hung_job_is_cancelled_recorded_failed_and_the_loop_goes_on(monkeypatch):
    monkeypatch.setattr(sch, "JOB_TIMEOUT_SECONDS", 0.05)
    conn = FakeConn()
    cancelled = []

    async def hang():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    hung = Job("hung", 60.0, hang)
    assert await sch.run_job_once(hung, db=fake_db(conn)) == "failed"
    assert cancelled == [True]
    finish = conn.log[-2]
    assert finish[2][:2] == ("hung", "failed")
    assert json.loads(finish[2][2])["error"] == "TimeoutError"
    assert conn.log[-1] == ("END",)             # the lock transaction ended

    # The next job still runs on the same connection.
    nxt, calls = job("next")
    assert await sch.run_job_once(nxt, db=fake_db(conn)) == "ok"
    assert calls == ["next"]


def test_job_timeout_is_generous_but_bounded():
    """Long enough for a real backlog (a 15-minute job must get its whole
    window), short enough that a hung job cannot stop the others for more
    than an hour."""
    assert 900.0 <= sch.JOB_TIMEOUT_SECONDS <= 3600.0
