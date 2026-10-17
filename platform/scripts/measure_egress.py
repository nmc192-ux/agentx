#!/usr/bin/env python3
"""
Database egress per call, measured on a local stack (EG-7, Neon egress). LOCAL ONLY.

Neon's free plan bills the bytes its Postgres sends out (DrJ's target: under
2 GB a month). This script measures exactly that, locally: a byte-counting TCP
proxy sits between the API and local Postgres, and every request or job is
charged the bytes that came back from the database while it ran (Postgres wire
protocol, no TLS; Neon adds TLS framing on top, a few percent).

  1. Rebuilds ``agentx_smoke_egress`` (init-db.sql → alembic head, as
     scripts/smoke_routers.py), month-old funded founders (as
     scripts/simulate_heartbeat.py) and ``--outsiders`` outside agents who post,
     reply, follow and message, so lists come back full.
  2. Runs the real founder tick (template generator, no LLM) for ``--days``
     simulated days on a fake clock, 5-minute steps: content plus the measured
     cost of one tick.
  3. Runs the other scheduled jobs once each through the scheduler's own wrapper.
  4. Calls the main routes in-process (httpx → ASGI → real Postgres) with the
     in-process caches OFF, so each figure is the cost of one cache miss. Each
     route is called 4 times: "first" (statements not yet prepared on that
     connection) and "steady" (median of the other three).
  5. Combines the steady figures with a traffic model (``--agents``,
     ``--page-views``) into a monthly total, plus the website's worst case
     (a visitor on every cached page every cache lifetime, 24/7).

Usage (from ``platform/``):
    .venv/bin/python scripts/measure_egress.py
    .venv/bin/python scripts/measure_egress.py --days 1 --agents 50 --out /tmp/egress.md
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke

DB_NAME = f"{smoke.DB_PREFIX}_egress"
DAYS_PER_MONTH = 30
SECONDS_PER_MONTH = DAYS_PER_MONTH * 86_400
TARGET_BYTES = 2 * 1024 ** 3          # DrJ's target: 2 GB of transfer a month
TLS_MARGIN = 1.05                     # TLS records on Neon's side; not on the local wire

# The production pool (src/database.init_pool), pointed at the proxy.
POOL_KW = dict(min_size=2, max_size=20, max_inactive_connection_lifetime=300,
               command_timeout=60, server_settings={"application_name": "agentx-api"})


# ── Byte-counting proxy ───────────────────────────────────────────────────────

class Counter:
    def __init__(self) -> None:
        self.down = 0      # Postgres → API: what Neon bills
        self.up = 0        # API → Postgres


async def start_proxy(counter: Counter, host: str, port: int) -> tuple[asyncio.AbstractServer, int]:
    async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter, attr: str) -> None:
        try:
            while data := await src.read(65_536):
                setattr(counter, attr, getattr(counter, attr) + len(data))
                dst.write(data)
                await dst.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            dst.close()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_r, up_w = await asyncio.open_connection(host, port)
        await asyncio.gather(pipe(reader, up_w, "up"), pipe(up_r, writer, "down"))

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def charge(counter: Counter, fn: Callable[[], Awaitable[Any]]) -> tuple[int, Any]:
    """Bytes the database sent while *fn* ran (and its result)."""
    before = counter.down
    result = await fn()
    await asyncio.sleep(0)          # let the proxy finish forwarding the last packet
    return counter.down - before, result


# ── Seed ──────────────────────────────────────────────────────────────────────

WORDS = ("agent model trust escrow task review data pipeline latency eval summary "
         "graph vector cache index result benchmark proposal vote bounty market").split()


def _text(rng: random.Random, lo: int, hi: int) -> str:
    n = rng.randint(lo, hi)
    out: list[str] = []
    while sum(len(w) + 1 for w in out) < n:
        out.append(rng.choice(WORDS))
    return " ".join(out)[:n]


async def seed_outsiders(pool, n: int, rng: random.Random) -> list[tuple[str, int]]:
    """*n* month-old outside agents with posts (200–1,200 chars, the size real
    agents write), replies, follows and messages."""
    agents: list[tuple[str, int]] = []
    for i in range(n):
        did = f"did:agentx:outsider{i}-{uuid4().hex[:8]}-001"
        agent_id = await pool.fetchval(
            "INSERT INTO agents (agent_did, display_name, description, created_at) "
            "VALUES ($1, $2, $3, NOW() - interval '30 days') RETURNING agent_id",
            did, f"outsider-{i}-{uuid4().hex[:6]}", _text(rng, 80, 280),
        )
        await pool.execute("INSERT INTO wallets (agent_id, balance) VALUES ($1, 500)", agent_id)
        agents.append((did, agent_id))
    dids = [d for d, _ in agents]
    posts: list = []
    for did in dids:
        for _ in range(rng.randint(3, 8)):
            posts.append(await pool.fetchval(
                "INSERT INTO posts (author_did, post_type, title, content, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, NOW() - make_interval(mins => $5), NOW()) "
                "RETURNING post_id",
                did, rng.choice(["UPDATE", "UPDATE", "REQUEST", "OFFER", "TASK"]),
                _text(rng, 20, 70), _text(rng, 200, 1200), rng.randint(1, 60 * 24 * 7),
            ))
    for _ in range(len(posts)):
        await pool.execute(
            "INSERT INTO posts (author_did, post_type, title, content, parent_post_id, "
            "created_at, updated_at) VALUES ($1, 'UPDATE', 're', $2, $3, NOW(), NOW())",
            rng.choice(dids), _text(rng, 60, 400), rng.choice(posts),
        )
    for did in dids:
        for other in rng.sample(dids, min(len(dids) - 1, 12)):
            if other != did:
                await pool.execute(
                    "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING", did, other)
        for other in rng.sample(dids, min(len(dids), 3)):
            if other != did:
                await pool.execute(
                    "INSERT INTO messages (sender_agent_did, receiver_agent_did, message) "
                    "VALUES ($1, $2, $3)", other, did, _text(rng, 40, 600))
    return agents


# ── Routes ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Route:
    key: str
    method: str
    path: str
    signed_in: bool = False
    body: dict | None = None
    calls: int = 4          # 1 for writes the rate limit would refuse on the 2nd call


def routes(me: str, other: str, post_id: str, follow_dids: list[str]) -> list[Route]:
    status_q = "&".join(f"did={d}" for d in follow_dids)
    return [
        Route("heartbeat", "POST", "/heartbeat", True, {"agent_did": me}),
        Route("feed_personal", "GET", "/feed?limit=20", True),
        Route("notifications", "GET", "/notifications?limit=20", True),
        Route("unread_badge", "GET", "/notifications?limit=1", True),
        Route("follow_status", "GET", f"/agents/follow-status?{status_q}", True),
        Route("messages_inbox", "GET", f"/messages/{me}", True),
        Route("post_create", "POST", "/posts", True,
              {"post_type": "UPDATE", "title": "measured", "content": "m" * 600}, calls=1),
        Route("feed_global", "GET", "/feed/global?limit=20"),
        Route("feed_global_50", "GET", "/feed/global?limit=50"),
        Route("feed_activity", "GET", "/feed/activity?limit=20"),
        Route("posts_global", "GET", "/posts/global?limit=20"),
        Route("agents_list", "GET", "/agents?limit=20"),
        Route("agent_profile", "GET", f"/agents/{other}"),
        Route("agent_feed", "GET", f"/agents/{me}/feed?limit=20", True),
        Route("agent_activity", "GET", f"/agents/{other}/activity?limit=20"),
        Route("followers", "GET", f"/agents/{other}/followers?limit=20"),
        Route("post_detail", "GET", f"/posts/{post_id}"),
        Route("post_replies", "GET", f"/posts/{post_id}/replies"),
        Route("pulse", "GET", "/pulse"),
        Route("pulse_trending", "GET", "/pulse/trending"),
        Route("spotlight", "GET", "/spotlight/agent-of-the-week"),
        Route("skill_md", "GET", "/.well-known/skill.md"),
    ]


async def measure_routes(counter: Counter, client, rts: list[Route], caller_headers: dict
                         ) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rts:
        samples, status = [], None
        for _ in range(r.calls):
            headers = caller_headers if r.signed_in else {}
            async def call():
                return await client.request(r.method, r.path, json=r.body, headers=headers)
            n, resp = await charge(counter, call)
            samples.append(n)
            status = resp.status_code
        out[r.key] = {"path": f"{r.method} {r.path.split('?')[0]}", "status": status,
                      "first": samples[0], "steady": int(statistics.median(samples[1:] or samples))}
    return out


# ── Traffic model ─────────────────────────────────────────────────────────────

# Per active outside agent per day, besides the heartbeat (every 4 h = 6 a day,
# heartbeat_service.NEXT_HEARTBEAT_IN). Signed-in, so never served from cache.
AGENT_DAY = {"feed_personal": 4, "agent_feed": 2, "notifications": 4, "post_detail": 4, "post_replies": 2,
             "agent_profile": 2, "messages_inbox": 2, "post_create": 2}
# Per website page view: the API reads one view makes (the home page is the
# common landing page; profiles and posts are linked from it).
PAGE_VIEW = {"feed_global": 0.5, "pulse": 0.5, "pulse_trending": 0.5, "spotlight": 0.3,
             "agents_list": 0.2, "agent_profile": 0.3, "agent_activity": 0.3,
             "post_detail": 0.2, "post_replies": 0.2}
# Cached anonymous routes and their cache lifetime (src/middleware/response_cache.py).
CACHED_TTL = {"feed_global": 30, "feed_activity": 30, "posts_global": 30, "agents_list": 60,
              "pulse": 30, "pulse_trending": 30, "spotlight": 60}
API_PROCESSES = 2       # fly.toml `--workers 2`, or the VPS's api-1 + api-2: one cache each
SENS_AGENTS = (8, 50, 200, 500)
SENS_VIEWS = (100, 300, 1_000, 3_000, 10_000)


def monthly(measured: dict[str, int], *, agents: int, page_views: int, signed_in_hours: float,
            founder_tick: int, jobs: dict[str, int], reconnect: int
            ) -> list[tuple[str, float, int]]:
    """[(line, calls a month, bytes a month)] for the expected month."""
    m = DAYS_PER_MONTH
    lines: list[tuple[str, float, int]] = []

    def add(label: str, calls: float, per_call: int) -> None:
        lines.append((label, calls, int(calls * per_call)))

    add("Founder tick (every 5 min, 8 founders)", SECONDS_PER_MONTH / 300, founder_tick)
    add("Maintenance job (every 15 min)", SECONDS_PER_MONTH / 900, jobs["scheduled_maintenance"])
    add("Auto-release job (every 15 min)", SECONDS_PER_MONTH / 900, jobs["auto_release"])
    add("Agent-of-the-week job (hourly)", SECONDS_PER_MONTH / 3600, jobs["agent_of_week"])
    add(f"Heartbeat ({agents} agents, every 4 h)", agents * 6 * m, measured["heartbeat"])
    for key, per_day in AGENT_DAY.items():
        add(f"Agents: {key} ({per_day}/agent/day)", agents * per_day * m, measured[key])
    for key, per_view in PAGE_VIEW.items():
        calls = page_views * per_view * m
        if key in CACHED_TTL:     # a cache miss at most once per lifetime per process
            calls = min(calls, API_PROCESSES * SECONDS_PER_MONTH / CACHED_TTL[key])
        add(f"Website: {key} ({per_view}/view)", calls, measured[key])
    add(f"Unread badge ({signed_in_hours} signed-in tab-hours/day, 1/min)",
        signed_in_hours * 60 * m, measured["unread_badge"])
    # The pool drops a connection idle for 5 minutes (max_inactive_connection_lifetime);
    # the next one re-sends startup and re-prepares its statements. Worst case: every
    # API process and the scheduler reconnect every 5 minutes.
    add(f"Reconnects after 5 idle minutes ({API_PROCESSES} API processes + scheduler)",
        (API_PROCESSES + 1) * SECONDS_PER_MONTH / 300, reconnect)
    return lines


def website_ceiling(measured: dict[str, int]) -> int:
    """Every cached page missed once per lifetime per process, 24/7: the most the
    anonymous website can cost however many people visit."""
    return int(sum(API_PROCESSES * SECONDS_PER_MONTH / ttl * measured[k]
                   for k, ttl in CACHED_TTL.items()))


# ── Run ───────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> dict[str, Any]:
    env = {**sim.local_env(), "POSTGRES_DB": DB_NAME, "LOCAL_CACHE": "off",
           "PUBLIC_LIST_LIMITS": "off", "REDIS_URL": "memory://"}
    smoke.build_database(DB_NAME, env)
    os.environ.update(env)

    import asyncpg
    from httpx import ASGITransport, AsyncClient

    import src.database as database
    from src.config import Settings
    from src.founders.generation import TemplateGenerator
    from src.founders.roster import founder_roster
    from src.jobs import founder_heartbeat as fh
    from src.jobs import scheduler

    counter = Counter()
    server, proxy_port = await start_proxy(counter, smoke.DB_HOST, int(sim.PG_PORT))
    restore_bus = sim.silence_event_bus()
    pool = await asyncpg.create_pool(host="127.0.0.1", port=proxy_port, user=sim.PG_USER,
                                     database=DB_NAME, **POOL_KW)
    previous_pool, database._pool = database._pool, pool
    rng = random.Random("eg-7")
    try:
        roster = founder_roster("", "development")
        await sim.prepare(pool, roster)
        outsiders = await seed_outsiders(pool, args.outsiders, rng)

        # Founder tick: average over the simulated days (fake clock, 5-minute steps).
        settings = Settings(_env_file=None, founder_heartbeat_enabled="true",
                            founder_llm_provider="")
        generator, tick_rng = TemplateGenerator(), random.Random("eg-7-ticks")
        start = sim.pick_start(datetime.now(timezone.utc).date(), args.days)
        ticks = int(args.days * 288)
        per_tick: list[int] = []
        for k in range(ticks):
            n, _ = await charge(counter, lambda: fh.run_tick(
                now=start + timedelta(minutes=5 * k), roster=roster, generator=generator,
                rng=tick_rng, settings=settings))
            per_tick.append(n)
        founder_tick = sum(per_tick) // max(ticks, 1)
        q = max(ticks // 4, 1)       # does a tick cost more as the content grows?
        tick_quarters = [sum(per_tick[i:i + q]) // len(per_tick[i:i + q])
                         for i in range(0, q * 4, q) if per_tick[i:i + q]]

        # The other jobs, through the scheduler's lock/record wrapper (steady: 2nd run).
        jobs: dict[str, int] = {}
        for job in scheduler.JOBS:
            if job.name == "founder_heartbeat":
                continue
            forced = scheduler.Job(job.name, 0.0, job.run)   # interval 0: never "recent"
            await scheduler.run_job_once(forced)
            jobs[job.name], _ = await charge(counter, lambda: scheduler.run_job_once(forced))

        # A fresh connection: what every reconnect after 5 idle minutes costs.
        connect_bytes, conn = await charge(counter, lambda: asyncpg.connect(
            host="127.0.0.1", port=proxy_port, user=sim.PG_USER, database=DB_NAME,
            server_settings={"application_name": "agentx-api"}))
        await conn.close()

        # Routes, as one outside agent with a real access token (the auth lookup
        # is part of every signed-in call's cost).
        from src.auth.jwt import create_access_token
        from src.main import app

        me, other = outsiders[0][0], outsiders[1][0]
        post_id = str(await pool.fetchval(
            "SELECT post_id FROM posts WHERE parent_post_id IS NULL AND author_did = $1 "
            "ORDER BY created_at DESC LIMIT 1", other))
        follow_dids = [d for d, _ in outsiders[1:21]]
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://testserver") as client:
            measured = await measure_routes(
                counter, client, routes(me, other, post_id, follow_dids),
                {"Authorization": f"Bearer {create_access_token(me)}"})
        for v in measured.values():       # stable paths in the report
            v["path"] = (v["path"].replace(me, "{me}").replace(other, "{did}")
                         .replace(post_id, "{post_id}"))
    finally:
        database._pool = previous_pool
        restore_bus()
        await pool.close()
        server.close()

    steady = {k: v["steady"] for k, v in measured.items()}
    # A reconnect: startup plus the costliest re-prepare seen on any route.
    reconnect = connect_bytes + max(v["first"] - v["steady"] for v in measured.values())

    def total_for(agents: int, page_views: int) -> int:
        lines = monthly(steady, agents=agents, page_views=page_views,
                        signed_in_hours=args.signed_in_hours, founder_tick=founder_tick,
                        jobs=jobs, reconnect=reconnect)
        return int(sum(b for _, _, b in lines) * TLS_MARGIN)

    lines = monthly(steady, agents=args.agents, page_views=args.page_views,
                    signed_in_hours=args.signed_in_hours, founder_tick=founder_tick,
                    jobs=jobs, reconnect=reconnect)
    total = int(sum(b for _, _, b in lines) * TLS_MARGIN)
    grid = {f"{a}x{v}": total_for(a, v) for a in SENS_AGENTS for v in SENS_VIEWS}
    return {"routes": measured, "founder_tick": founder_tick, "jobs": jobs,
            "connect": connect_bytes, "lines": lines, "total": total,
            "website_ceiling": int(website_ceiling(steady) * TLS_MARGIN),
            "reconnect": reconnect, "grid": grid, "tick_quarters": tick_quarters,
            "params": vars(args)}


def _size(n: float) -> str:
    for unit, div in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{int(n)} B"


def render(r: dict[str, Any]) -> str:
    p = r["params"]
    out = ["## Measured bytes from the database per call", "",
           "| Route | Path | Status | First call | Steady |", "|---|---|---|---:|---:|"]
    for key, v in r["routes"].items():
        out.append(f"| {key} | `{v['path']}` | {v['status']} | {_size(v['first'])} | "
                   f"{_size(v['steady'])} |")
    out += ["", "| Job | Per run |", "|---|---:|",
            f"| founder tick (average of {int(p['days'] * 288)} ticks) | {_size(r['founder_tick'])} |"]
    out += [f"| {k} | {_size(v)} |" for k, v in r["jobs"].items()]
    out += [f"| new database connection | {_size(r['connect'])} |",
            f"| reconnect (connection + costliest re-prepare) | {_size(r['reconnect'])} |", "",
            "Founder tick by quarter of the simulated run (content growing): "
            + " → ".join(_size(x) for x in r["tick_quarters"]) + ".", "",
            f"## Expected month ({p['agents']} outside agents, {p['page_views']} website "
            f"page views/day)", "", "| Line | Calls/month | Bytes/month |", "|---|---:|---:|"]
    for label, calls, b in sorted(r["lines"], key=lambda x: -x[2]):
        out.append(f"| {label} | {int(calls):,} | {_size(b)} |")
    out += ["", f"**Total, +5 % for TLS: {_size(r['total'])}** against a 2 GB target "
            f"({100 * r['total'] / TARGET_BYTES:.0f} %).", "",
            f"Website worst case (every cached page missed every lifetime, 24/7, "
            f"{API_PROCESSES} processes): {_size(r['website_ceiling'])}.", "",
            "## Monthly total by traffic (+5 % TLS)", "",
            "| Outside agents \\ page views/day | " + " | ".join(f"{v:,}" for v in SENS_VIEWS) + " |",
            "|---|" + "---:|" * len(SENS_VIEWS)]
    for a in SENS_AGENTS:
        out.append(f"| {a} | " + " | ".join(_size(r["grid"][f"{a}x{v}"]) for v in SENS_VIEWS)
                   + " |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--days", type=float, default=1, help="simulated founder days (288 ticks each)")
    ap.add_argument("--outsiders", type=int, default=40, help="seeded outside agents")
    ap.add_argument("--agents", type=int, default=50, help="active outside agents in the model")
    ap.add_argument("--page-views", type=int, default=300, help="website page views a day")
    ap.add_argument("--signed-in-hours", type=float, default=4,
                    help="signed-in website tab-hours a day (unread badge)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path, help="also write the Markdown tables here")
    args = ap.parse_args()
    result = asyncio.run(run(args))
    text = json.dumps(result, indent=2, default=str) if args.json else render(result)
    print(text)
    if args.out:
        args.out.write_text(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
