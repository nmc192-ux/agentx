#!/usr/bin/env python3
"""
The stranger's journey on a local stack, both paths (Sprint 11, S11-7). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_journey``, the same
init-db.sql → alembic chain as scripts/smoke_routers.py), gives the seeded
founders month-old accounts and funded wallets (as scripts/simulate_heartbeat.py
does: an account under a day old cannot vouch for trust), boots the API with
uvicorn on a free localhost port with the founder heartbeat and welcomes on,
and runs the real founder tick (`jobs.founder_heartbeat.run_tick`, template
generator, no LLM, wall clock) every ``--tick`` seconds in the background —
the local stand-in for the Celery beat. Welcomes go out on the next tick
(``FOUNDER_WELCOME_DELAY_MINUTES=0``).

Then it runs ``scripts/external_smoke.py`` against that API, once per path
(``curl`` and ``sdk``), and prints both transcripts plus what the ticks did.
``--out`` writes the combined Markdown record. Exit code 0 only if every path
passed.

Usage:
  cd platform && .venv/bin/python scripts/local_journey.py
  .venv/bin/python scripts/local_journey.py --wait 60 --out /tmp/journey.md
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look the module up
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke
journey = _load("external_smoke")

DB_NAME = f"{smoke.DB_PREFIX}_journey"
PATHS = ("curl", "sdk")


def local_env() -> dict[str, str]:
    return {
        **sim.local_env(),
        "POSTGRES_DB": DB_NAME,
        "RATE_LIMIT_MODE": "log",
        "PYTHONWARNINGS": "ignore",
        "FOUNDER_HEARTBEAT_ENABLED": "true",
        "FOUNDER_WELCOMES_ENABLED": "true",
        "FOUNDER_WELCOME_DELAY_MINUTES": "0",
        "FOUNDER_LLM_PROVIDER": "",
    }


async def ticker(roster, stop: asyncio.Event, every: float, totals: Counter) -> None:
    """The founder tick on the wall clock until *stop* is set."""
    from src.config import Settings
    from src.founders.generation import TemplateGenerator
    from src.jobs import founder_heartbeat as fh

    settings = Settings(
        _env_file=None, founder_heartbeat_enabled="true", founder_welcomes_enabled="true",
        founder_welcome_delay_minutes=0, founder_llm_provider="",
    )
    generator = TemplateGenerator()
    while not stop.is_set():
        s = await fh.run_tick(roster=roster, generator=generator, settings=settings)
        totals["ticks"] += 1
        for did, founder in (s.get("welcomed") or {}).items():
            totals[f"welcomed {did} by {founder}"] += 1
        for key in ("welcome_held", "welcome_dm_blocked", "welcome_rejected"):
            totals[key] += len(s.get(key) or [])
        for key in ("refused", "errors", "trust_errors", "welcome_errors"):
            for name, why in (s.get(key) or {}).items():
                totals[f"{key}:{name}:{why}"] += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
        except asyncio.TimeoutError:
            pass


async def run(args) -> int:
    import asyncpg

    import src.database as database
    from src.founders.roster import founder_roster

    env = local_env()
    smoke.build_database(DB_NAME, env)
    os.environ.update(env)

    roster = founder_roster("", "development")
    restore_bus = sim.silence_event_bus()
    pool = await asyncpg.create_pool(
        host=smoke.DB_HOST, port=int(sim.PG_PORT), user=sim.PG_USER, database=DB_NAME,
        min_size=2, max_size=10, command_timeout=60,
    )
    previous_pool, database._pool = database._pool, pool
    log_path = Path(tempfile.gettempdir()) / "agentx_local_journey_api.log"
    proc = None
    stop = asyncio.Event()
    totals: Counter = Counter()
    results: dict[str, tuple[int, str]] = {}
    try:
        await sim.prepare(pool, roster)
        proc, base = smoke.start_server(env, log_path)
        print(f"• API on {base} (log: {log_path}); founder tick every {args.tick:g} s")
        tick_task = asyncio.create_task(ticker(roster, stop, args.tick, totals))
        for path in PATHS:
            out = Path(tempfile.gettempdir()) / f"agentx_local_journey_{path}.md"
            print(f"• journey, --path {path}")
            code = await asyncio.to_thread(journey.main, [
                "--base-url", base, "--path", path, "--wait", str(args.wait),
                "--poll-interval", str(args.poll_interval), "--out", str(out),
            ])
            results[path] = (code, out.read_text(encoding="utf-8"))
        stop.set()
        await tick_task
    finally:
        stop.set()
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=20)
        database._pool = previous_pool
        restore_bus()
        await pool.close()

    ok = all(code == 0 for code, _ in results.values())
    record = render(results, totals, args)
    if args.out:
        Path(args.out).write_text(record, encoding="utf-8")
    print(record)
    return 0 if ok else 1


def render(results: dict[str, tuple[int, str]], totals: Counter, args) -> str:
    lines = [
        "## Local run",
        "",
        f"- **Run at:** {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- **Stack:** scratch database `{DB_NAME}`, API under uvicorn on localhost, "
        f"founder tick every {args.tick:g} s (wall clock, template text, no LLM), "
        "`FOUNDER_WELCOME_DELAY_MINUTES=0`, founders aged 30 days",
        "- **Result:** " + ", ".join(
            f"{p} {'PASS' if code == 0 else 'FAIL'}" for p, (code, _) in results.items()
        ),
        f"- **Founder ticks:** {totals.get('ticks', 0)}",
    ]
    extra = sorted(k for k in totals if k != "ticks" and totals[k])
    if extra:
        lines.append("- **Tick counters:** " + ", ".join(f"`{k}` {totals[k]}" for k in extra))
    for path, (_, text) in results.items():
        lines += ["", f"### Path: {path}", "", text.replace("# External smoke", "#### External smoke", 1)]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tick", type=float, default=3.0, help="seconds between founder ticks")
    p.add_argument("--wait", type=float, default=90.0, help="journey poll limit (seconds)")
    p.add_argument("--poll-interval", type=float, default=1.0)
    p.add_argument("--out", help="write the Markdown record here")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
