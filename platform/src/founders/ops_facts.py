"""
AgentX Platform — Ops and health facts (Truthful founders, TF-3)
═════════════════════════════════════════════════════════════════
What BRUNO and QUINN may say about how the platform is run, read this tick
from records that real runs left behind — never from a guess:

  BRUNO   the commit this process runs (`settings.git_commit`) and when it
          went live (deploy.json, written by deploy/vps/deploy.sh), how the
          scheduled jobs ended in the last 24 hours (`scheduler_job_runs`),
          the newest nightly backup (backup.json) and restore drill
          (restore_test.json), both written by deploy/vps/db_move.sh.
  QUINN   the newest smoke run (smoke.json, deploy/vps/smoke.sh with
          SMOKE_STATUS_DIR set) and CI for the live commit (ci.json, written
          by .github/workflows/deploy-vps.yml after a release).

The JSON records live in `settings.founder_status_dir` (the VPS folder
/opt/agentx/status, mounted read-only into the scheduler). Rules:
  - A record that is missing, not a small JSON object, has the wrong field
    types, is dated in the future or is older than 7 days is no fact.
  - A release or CI record for another commit than the one this process
    runs is no fact (it describes code that is not live).
  - CI with checks still running, or no checks, is no fact.
  - Every `Fact.text` passes the TF-1 claim checker against itself.

Nothing here writes anything.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..config import get_settings
from .facts import Fact, _duration, _plural, _row

logger = logging.getLogger("agentx.founders.ops_facts")

__all__ = ["MAX_AGE", "read_status", "bruno_facts", "quinn_facts"]

MAX_AGE = timedelta(days=7)
_MAX_BYTES = 64 * 1024
_SKEW = timedelta(minutes=5)          # a clock slightly ahead is not "the future"
_SHA = re.compile(r"[0-9a-f]{40}")
_JOB = re.compile(r"[a-z_]{1,60}")    # job names are words: no digits to trip the checker


def _status_dir(status_dir: Optional[str]) -> Path:
    return Path(status_dir if status_dir is not None else get_settings().founder_status_dir)


def _when(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%d %b at %H:%M UTC")


def read_status(name: str, now: datetime, status_dir: Optional[str] = None,
                time_key: str = "finished_at") -> Optional[dict]:
    """The record *name*.json as a dict with its moment parsed into
    ``_at``, or None when it is missing, unreadable, too big, not a JSON
    object, undated, dated in the future or older than `MAX_AGE`."""
    path = _status_dir(status_dir) / f"{name}.json"
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("status record %s unreadable: %s", name, type(exc).__name__)
        return None
    if not isinstance(data, dict):
        return None
    moment = _when(data.get(time_key))
    if moment is None or moment > now + _SKEW or now - moment > MAX_AGE:
        return None
    return {**data, "_at": moment}


def _count(data: dict, key: str) -> Optional[int]:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _live_commit() -> Optional[str]:
    commit = (get_settings().git_commit or "").strip().lower()
    return commit if _SHA.fullmatch(commit) else None


# ── BRUNO: release, scheduled jobs, backups ──────────────────────────────────

async def bruno_facts(conn, now: datetime, status_dir: Optional[str] = None) -> list[Fact]:
    facts: list[Fact] = []
    commit = _live_commit()

    release = read_status("deploy", now, status_dir)
    if commit and release and release.get("commit") == commit:
        since = (now - release["_at"]).total_seconds()
        facts.append(Fact(
            "bruno.release",
            f"The platform runs commit {commit[:7]}, live since a release on "
            f"{_stamp(release['_at'])}, about {_duration(since)} ago.",
            since, "file:deploy.json", now,
        ))
    elif commit:
        facts.append(Fact("bruno.commit", f"The platform runs commit {commit[:7]}.",
                          0, "code:settings.git_commit", now))

    row = await _row(conn, """
        /* fact:bruno.jobs */
        SELECT COUNT(*) FILTER (WHERE last_status = 'ok')     AS ok,
               COUNT(*) FILTER (WHERE last_status = 'failed') AS failed,
               COALESCE(array_agg(job_name ORDER BY job_name)
                        FILTER (WHERE last_status = 'failed'), '{}') AS failed_names
        FROM scheduler_job_runs
        WHERE last_started_at > $1::timestamptz - INTERVAL '24 hours'
          AND last_started_at <= $1::timestamptz
        """, now)
    if row is not None:
        ok, failed = int(row["ok"] or 0), int(row["failed"] or 0)
        names = [n.replace("_", " ") for n in (row["failed_names"] or []) if _JOB.fullmatch(n or "")]
        total = ok + failed
        if total and not failed:
            facts.append(Fact(
                "bruno.jobs_24h",
                f"All {_plural(total, 'scheduled job')} that ran in the last 24 hours "
                f"ended without an error on their last run.",
                total, "db:scheduler_job_runs", now,
            ))
        elif failed:
            text = (f"Of {_plural(total, 'scheduled job')} that ran in the last 24 hours, "
                    f"{failed} ended in an error on {'its' if failed == 1 else 'their'} last run")
            text += f": {', '.join(names)}." if names and len(names) == failed else "."
            facts.append(Fact("bruno.jobs_24h", text, failed, "db:scheduler_job_runs", now))

    backup = read_status("backup", now, status_dir)
    if backup and backup.get("ok") is True:
        facts.append(Fact(
            "bruno.backup",
            f"The newest nightly database backup finished on {_stamp(backup['_at'])}.",
            (now - backup["_at"]).total_seconds(), "file:backup.json", now,
        ))

    drill = read_status("restore_test", now, status_dir)
    if drill and isinstance(drill.get("ok"), bool):
        if drill["ok"]:
            text = (f"The newest restore drill loaded the latest backup into a throwaway "
                    f"database and its tables matched, on {_stamp(drill['_at'])}.")
        else:
            text = (f"The newest restore drill, on {_stamp(drill['_at'])}, could not load "
                    f"the latest backup into a throwaway database.")
        facts.append(Fact("bruno.restore_drill", text, 1 if drill["ok"] else 0,
                          "file:restore_test.json", now))
    return facts


# ── QUINN: smoke runs and CI ─────────────────────────────────────────────────

async def quinn_facts(conn, now: datetime, status_dir: Optional[str] = None) -> list[Fact]:
    facts: list[Fact] = []

    smoke = read_status("smoke", now, status_dir)
    if smoke:
        passed, failed, skipped = (_count(smoke, k) for k in ("passed", "failed", "skipped"))
        if None not in (passed, failed, skipped) and passed + failed:
            text = (f"The newest smoke run against the live API, on {_stamp(smoke['_at'])}, "
                    f"passed {passed} of {passed + failed + skipped} checks")
            extra = []
            if failed:
                extra.append(f"{failed} failed")
            if skipped:
                extra.append(f"{skipped} skipped")
            text += f" ({', '.join(extra)})." if extra else "."
            facts.append(Fact("quinn.smoke", text, passed, "file:smoke.json", now))

    commit = _live_commit()
    ci = read_status("ci", now, status_dir, time_key="checked_at")
    if commit and ci and ci.get("commit") == commit:
        total, failed, pending = (_count(ci, k) for k in ("total", "failed", "pending"))
        if None not in (total, failed, pending) and total and not pending and failed <= total:
            if failed:
                text = (f"CI for the live commit {commit[:7]}: {failed} of "
                        f"{_plural(total, 'check')} did not pass.")
            else:
                text = f"CI for the live commit {commit[:7]}: all {_plural(total, 'check')} passed."
            facts.append(Fact("quinn.ci", text, total - failed, "file:ci.json", now))
    return facts
