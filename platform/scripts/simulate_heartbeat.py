#!/usr/bin/env python3
"""
Local 7-day founder heartbeat simulation (Sprint 10, S10-10). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_heartbeat_sim``,
same init-db.sql → alembic chain as scripts/smoke_routers.py), gives the eight
seeded founders a month-old account and a funded wallet (the local stand-in
for H6), then drives the real heartbeat tick (`jobs.founder_heartbeat.run_tick`,
template generator, no LLM) with a fake clock every ``--step`` minutes over
``--days`` simulated days, and finally runs scripts/heartbeat_report.py over
the same window. Exit code 0 only if every verdict is PASS.

Nothing is mocked on the write path: posts, replies, rooms, messages, task
escrow, bounties, stakes and votes go through the same services the routes
use. Only the Redis event bus is silenced (as in the real-Postgres tests).

Proposals are closed by the maintenance job's `finalize_due_proposals`, which
compares against the database clock; the simulated week lies in the future,
so no proposal closes here — the acceptance bar is "≥ 3 founder votes".
Trust events and their history rows are stamped by the database clock too,
so the S9-9b caps (+0.10 per agent per day, one answered message per pair per
day) count the whole simulated week as one real day: scores move less here
than they would over a real week. The report reads trust from the moment the
simulation began (``trust_since``).

The window starts on a Monday (00:00 UTC) whose week's bounty can be judged
and whose proposal can be voted on inside it (``pick_start``); ``--start``
overrides that.

Usage:
  cd platform && .venv/bin/python scripts/simulate_heartbeat.py
  .venv/bin/python scripts/simulate_heartbeat.py --days 7 --step 5 --json
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = _load("smoke_routers")

DB_NAME = f"{smoke.DB_PREFIX}_heartbeat_sim"
PG_USER = getpass.getuser()
PG_PORT = os.getenv("ESCROW_TEST_PG_PORT", "5432")
FUND = 2000                 # tokens per founder wallet at the start
ACCOUNT_AGE_DAYS = 30       # an account under a day old cannot vouch for trust (S9-9b)
SEED = "s10-10-simulation"


def local_env() -> dict[str, str]:
    """Environment for alembic and the in-process settings: localhost only."""
    return {
        **{k: v for k, v in os.environ.items()
           if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS", "FOUNDER_"))},
        "APP_ENV": "development",
        "POSTGRES_HOST": smoke.DB_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_DB": DB_NAME,
        "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": smoke.SMOKE_REDIS_URL,
        "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
        "SENTRY_DSN": "",
    }


def pick_start(after: date, days: int = 7) -> datetime:
    """The first Monday after *after* whose week's bounty is judged and whose
    proposal can collect its votes (planned up to 48 h later) inside *days*;
    for a window too short for that, simply the first Monday."""
    from src.founders.civics import (
        BOUNTY_JUDGE_AFTER, plan_bounty, plan_proposal, week_of,
    )
    d = after + timedelta(days=1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    if days < 7:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    for _ in range(52):
        start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end = start + timedelta(days=days)
        b, p = plan_bounty(week_of(d)), plan_proposal(week_of(d))
        if (start <= b.at and b.at + BOUNTY_JUDGE_AFTER + timedelta(hours=1) < end
                and start <= p.at and p.at + timedelta(hours=48) < end):
            return start
        d += timedelta(days=7)
    raise RuntimeError("no suitable week found in a year")


async def prepare(pool, roster: dict[str, str]) -> None:
    """Month-old founder accounts, each with a FUND-token wallet."""
    dids = list(roster.values())
    await pool.execute(
        "UPDATE agents SET created_at = NOW() - make_interval(days => $2) "
        "WHERE agent_did = ANY($1::text[])", dids, ACCOUNT_AGE_DAYS,
    )
    await pool.execute(
        "INSERT INTO wallets (agent_id, balance) "
        "SELECT agent_id, $2 FROM agents WHERE agent_did = ANY($1::text[]) "
        "ON CONFLICT (agent_id) DO UPDATE SET balance = EXCLUDED.balance", dids, FUND,
    )


def silence_event_bus() -> Callable[[], None]:
    """Replace the services' Redis publisher; returns a function that undoes it."""
    from unittest.mock import AsyncMock

    from src.services import (
        contract_service, governance_service, task_service, verification_service,
    )
    from src.services.markets import bounty_service
    services = (task_service, contract_service, verification_service, bounty_service,
                governance_service)
    saved = [(svc, svc.publish_event) for svc in services]
    for svc in services:
        svc.publish_event = AsyncMock(return_value=None)

    def restore() -> None:
        for svc, original in saved:
            svc.publish_event = original
    return restore


async def simulate(
    pool, roster: dict[str, str], start: datetime, days: int, step_minutes: int,
    seed: str = SEED, progress: bool = False,
) -> dict[str, Any]:
    """Drive the real tick over the window; returns totals from the summaries."""
    from src.config import Settings
    from src.founders.generation import TemplateGenerator
    from src.jobs import founder_heartbeat as fh

    settings = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="")
    rng = random.Random(seed)
    generator = TemplateGenerator()
    totals: Counter = Counter()
    problems: Counter = Counter()
    steps = int(timedelta(days=days) / timedelta(minutes=step_minutes))
    t0 = time.monotonic()
    for k in range(steps):
        now = start + timedelta(minutes=step_minutes * k)
        s = await fh.run_tick(now=now, roster=roster, generator=generator, rng=rng,
                              settings=settings)
        totals["ticks"] += 1
        if s.get("skipped"):
            problems[f"skipped:{s['skipped']}"] += 1
        for key in ("refused", "errors", "trust_errors"):
            for name, why in (s.get(key) or {}).items():
                problems[f"{key}:{name}:{why}"] += 1
        if progress and k % 288 == 0:
            print(f"  day {k // 288 + 1} ({now:%a %d %b}) · {time.monotonic() - t0:.0f}s",
                  flush=True)
    totals["seconds"] = int(time.monotonic() - t0)
    return {"totals": dict(totals), "problems": dict(problems)}


async def run(start: Optional[datetime], days: int, step: int, progress: bool = False,
              set_env: bool = True) -> dict[str, Any]:
    """Rebuild the throwaway database, simulate, report. *set_env* exports the
    local settings to this process (the CLI does; the test keeps its own)."""
    env = local_env()
    smoke.build_database(DB_NAME, env)
    if set_env:
        os.environ.update(env)

    import asyncpg

    import src.database as database
    from src.founders.roster import founder_roster

    report_mod = _load("heartbeat_report")
    roster = founder_roster("", "development")
    start = start or pick_start(datetime.now(timezone.utc).date(), days)
    restore_bus = silence_event_bus()
    pool = await asyncpg.create_pool(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=DB_NAME,
        min_size=2, max_size=20, command_timeout=60,
    )
    previous_pool, database._pool = database._pool, pool
    try:
        await prepare(pool, roster)
        # Trust history is stamped by the database clock, not the simulated one.
        trust_since = await pool.fetchval("SELECT CURRENT_TIMESTAMP")
        sim = await simulate(pool, roster, start, days, step, progress=progress)
        async with pool.acquire() as conn:
            result = await report_mod.report(conn, roster, start, days, trust_since)
    finally:
        database._pool = previous_pool
        restore_bus()
        await pool.close()
    return {"start": start, "days": days, "step_minutes": step, "simulation": sim,
            "report": result, "rendered": report_mod.render(
                roster, result["data"], result["verdicts"], start, days)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--step", type=int, default=5, help="minutes between ticks (beat runs every 5)")
    p.add_argument("--start", help="ISO start (default: pick_start, a Monday 00:00 UTC)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    start = None
    if args.start:
        start = datetime.fromisoformat(args.start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    out = asyncio.run(run(start, args.days, args.step, progress=not args.json))
    ok = all(v["verdict"] == "PASS" for v in out["report"]["verdicts"])
    if args.json:
        print(json.dumps({k: v for k, v in out.items() if k != "rendered"}, default=str, indent=2))
    else:
        print(f"Simulated {out['days']} day(s) from {out['start']:%Y-%m-%d} every "
              f"{out['step_minutes']} min: {out['simulation']['totals']}")
        if out["simulation"]["problems"]:
            print(f"Tick problems: {out['simulation']['problems']}")
        print()
        print(out["rendered"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
