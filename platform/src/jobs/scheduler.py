"""
AgentX Platform — Broker-free scheduler
════════════════════════════════════════
One process that runs the recurring jobs on their intervals. It replaced the
Celery worker + beat on 10 Oct 2026: Celery needed a Redis broker, and its
polling used up the Upstash free plan in three days (production outage of
9 Oct). Nothing here touches Redis; the coordination lives in Postgres.

    job                      every    what it does
    scheduled_maintenance    15 min   trust recalculation (replays unapplied
                                      trust events) + closes due proposals
    auto_release             15 min   releases held tokens left unanswered
    founder_heartbeat         5 min   founding agents act (off unless
                                      FOUNDER_HEARTBEAT_ENABLED)
    agent_of_week            60 min   picks the week's agent; idempotent (off
                                      unless AGENT_OF_WEEK_ENABLED)

A job whose flag is off is skipped without opening a database connection.

Never twice — each run of a job happens inside one Postgres transaction that:
  1. takes `pg_try_advisory_xact_lock` on the job's key. If another process
     holds it (a second scheduler during a deploy), this one skips the run;
  2. reads the job's row in `scheduler_job_runs`. If the job started less
     than 90 % of its interval ago (in any process), this one skips the run;
  3. records the start, runs the job, records how it ended, and commits,
     which releases the lock.
If the process dies mid-run, the transaction rolls back: no start is recorded
and the next tick (here or in another process) runs the job again. Every job
is idempotent, so that is safe.

The lock is transaction-level on purpose: Neon's connection pooler runs in
transaction mode, where a session-level lock could be left on a server
connection somebody else gets next.

Inside one process the jobs run one after another, never at the same time.
A failing job is logged and recorded; the others keep their schedule, and the
loop itself never stops on an error. A job still running after
JOB_TIMEOUT_SECONDS (30 min) is cancelled and recorded as failed, so a hung
job cannot stop the others. SIGTERM / SIGINT finish the current job and exit.

Run (production: the `scheduler` process in fly.toml; see HUMAN_ACTIONS.md):
    cd platform && python -m src.jobs.scheduler
Run every job once and exit (local check):
    cd platform && .venv/bin/python -m src.jobs.scheduler --once
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ..database import close_pool, get_db, init_pool
from .agent_of_week import agent_of_week_enabled, run_agent_of_week
from .auto_release import run_auto_release
from .founder_heartbeat import heartbeat_enabled, run_tick
from .scheduled_maintenance import run_maintenance

logger = logging.getLogger(__name__)

MAINTENANCE_INTERVAL_SECONDS = 900.0        # every 15 minutes
AUTO_RELEASE_INTERVAL_SECONDS = 900.0       # every 15 minutes
FOUNDER_HEARTBEAT_INTERVAL_SECONDS = 300.0  # every 5 minutes
AGENT_OF_WEEK_INTERVAL_SECONDS = 3600.0     # every hour (idempotent per week)

# A job counts as "recently run" (and is skipped) if it started less than this
# share of its interval ago, so clock jitter between processes cannot make a
# due job wait a whole extra interval.
RECENT_SHARE = 0.9

# How long to wait before retrying when the database is unreachable at start.
STARTUP_RETRY_SECONDS = 30.0

# A job that has not finished after this long is cancelled and recorded as
# failed (RF-2, T1 review 10 Oct 2026). Jobs run one after another in this
# process, so one hung job (a query waiting on a lock, a stuck HTTP call) would
# otherwise hold its advisory lock and stop EVERY job, including the release
# of held tokens, until someone restarts the machine. Every job's writes are
# their own short transactions, so cancelling mid-way loses nothing: the next
# run picks up what is left.
JOB_TIMEOUT_SECONDS = 1800.0


def _always() -> bool:
    return True


@dataclass(frozen=True)
class Job:
    name: str
    interval: float
    run: Callable[[], Awaitable[Any]]
    enabled: Callable[[], bool] = _always


JOBS: tuple[Job, ...] = (
    Job("scheduled_maintenance", MAINTENANCE_INTERVAL_SECONDS, run_maintenance),
    Job("auto_release", AUTO_RELEASE_INTERVAL_SECONDS, run_auto_release),
    Job("founder_heartbeat", FOUNDER_HEARTBEAT_INTERVAL_SECONDS, run_tick, heartbeat_enabled),
    Job("agent_of_week", AGENT_OF_WEEK_INTERVAL_SECONDS, run_agent_of_week, agent_of_week_enabled),
)

_LOCK = "SELECT pg_try_advisory_xact_lock(hashtextextended('agentx.scheduler.' || $1, 0))"
_RECENT = """
    SELECT last_started_at > CURRENT_TIMESTAMP - make_interval(secs => $2)
      FROM scheduler_job_runs WHERE job_name = $1
"""
_START = """
    INSERT INTO scheduler_job_runs (job_name, last_started_at, last_finished_at,
                                    last_status, last_summary)
    VALUES ($1, CURRENT_TIMESTAMP, NULL, 'running', '{}'::jsonb)
    ON CONFLICT (job_name) DO UPDATE
       SET last_started_at = CURRENT_TIMESTAMP, last_finished_at = NULL,
           last_status = 'running', last_summary = '{}'::jsonb
"""
_FINISH = """
    UPDATE scheduler_job_runs
       SET last_finished_at = clock_timestamp(), last_status = $2,
           last_summary = $3::jsonb
     WHERE job_name = $1
"""


def _as_json(summary: Any) -> str:
    try:
        return json.dumps(summary if isinstance(summary, dict) else {"result": summary},
                          default=str)
    except Exception:   # noqa: BLE001 — a summary must never fail the run record
        return json.dumps({"result": repr(summary)})


async def run_job_once(job: Job, *, db: Any = None) -> str:
    """
    Run *job* once if it is on, not running elsewhere and not recently run.

    Returns what happened: "disabled", "locked" (another process is running
    it), "recent" (it ran less than 90 % of its interval ago), "ok", "failed"
    (the job raised; recorded, not re-raised) or "error" (the database could
    not be reached; nothing ran). Never raises.
    """
    db = db or get_db
    try:
        if not job.enabled():
            return "disabled"
    except Exception:   # noqa: BLE001 — an unreadable flag means off
        logger.exception("scheduler: %s flag unreadable; skipped", job.name)
        return "disabled"
    try:
        async with db() as conn:
            async with conn.transaction():
                # The lock is held until commit; the job may take minutes.
                await conn.execute("SET LOCAL idle_in_transaction_session_timeout = 0")
                if not await conn.fetchval(_LOCK, job.name):
                    logger.info("scheduler: %s is running in another process; skipped", job.name)
                    return "locked"
                if await conn.fetchval(_RECENT, job.name, job.interval * RECENT_SHARE):
                    logger.info("scheduler: %s ran recently; skipped", job.name)
                    return "recent"
                await conn.execute(_START, job.name)
                started = time.monotonic()
                try:
                    summary = await asyncio.wait_for(job.run(), timeout=JOB_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    logger.error("scheduler: %s cancelled after %ss (hung); recorded as failed",
                                 job.name, int(JOB_TIMEOUT_SECONDS))
                    status, summary = "failed", {"error": "TimeoutError",
                                                 "after_seconds": JOB_TIMEOUT_SECONDS}
                except Exception as exc:   # noqa: BLE001 — logged and recorded
                    logger.exception("scheduler: %s failed", job.name)
                    status, summary = "failed", {"error": type(exc).__name__}
                else:
                    status = "ok"
                await conn.execute(_FINISH, job.name, status, _as_json(summary))
                logger.info("scheduler: %s %s in %.1fs", job.name, status,
                            time.monotonic() - started)
                return status
    except Exception:   # noqa: BLE001 — database trouble: try again next interval
        logger.exception("scheduler: %s could not run (database)", job.name)
        return "error"


async def run_forever(
    jobs: tuple[Job, ...] = JOBS,
    stop: Optional[asyncio.Event] = None,
    *,
    db: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run every job when due until *stop* is set. Every job is due at start."""
    stop = stop or asyncio.Event()
    next_due = {job.name: clock() for job in jobs}
    while not stop.is_set():
        for job in jobs:
            if stop.is_set():
                break
            if clock() >= next_due[job.name]:
                await run_job_once(job, db=db)
                next_due[job.name] = clock() + job.interval
        wait = max(1.0, min(next_due.values()) - clock())
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass


async def _init_pool_with_retry(stop: asyncio.Event) -> bool:
    while not stop.is_set():
        try:
            await init_pool()
            return True
        except Exception:   # noqa: BLE001 — keep the process up; retry
            logger.exception("scheduler: database unreachable at start; retrying in %ss",
                             STARTUP_RETRY_SECONDS)
            try:
                await asyncio.wait_for(stop.wait(), timeout=STARTUP_RETRY_SECONDS)
            except asyncio.TimeoutError:
                pass
    return False


async def main(once: bool = False) -> dict[str, str]:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # pragma: no cover - non-Unix
            pass
    if not await _init_pool_with_retry(stop):
        return {}
    logger.info("scheduler: started (%s)",
                ", ".join(f"{j.name} every {int(j.interval)}s" for j in JOBS))
    try:
        if once:
            return {job.name: await run_job_once(job) for job in JOBS}
        await run_forever(JOBS, stop)
        return {}
    finally:
        await close_pool()
        logger.info("scheduler: stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentX broker-free scheduler")
    parser.add_argument("--once", action="store_true", help="run every job once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = asyncio.run(main(once=args.once))
    if args.once:
        print(result)
