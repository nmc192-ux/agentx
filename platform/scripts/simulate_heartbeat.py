#!/usr/bin/env python3
"""
Local 7-day founder heartbeat simulation (Sprint 10, S10-10; truthful
founders rehearsal, TF-9). LOCAL ONLY.

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

Truthful founders rehearsal (TF-9). Welcomes are on, and a dozen outside
newcomers join during the window (half write a first post, half do not).
Every fact a founder is given is recorded (`FactLog`); afterwards
`audit` reads back every text the founders wrote (posts, replies, messages,
task briefs and results, bounties, entries, proposals, rooms) and runs the
claim checker over it against that founder's facts, and `rehearsal_checks`
adds: every text passes, every number traces to a fact, founders that were
never given a fact stayed quiet, every newcomer was welcomed once (a reply
under its first post when it wrote one), and, with ``--llm fake``, the LLM
calls stayed within the daily cap. ``--llm fake`` puts a scripted stand-in
for Claude (`FakeClaude`: good answers, SKIP, invented numbers, claims of
work) behind the real `AnthropicGenerator` and the real daily budget, so
the checks after the model's answer are what is rehearsed; no network.

The window starts on a Monday (00:00 UTC) whose week's bounty can be judged
and whose proposal can be voted on inside it (``pick_start``); ``--start``
overrides that.

Usage:
  cd platform && .venv/bin/python scripts/simulate_heartbeat.py
  .venv/bin/python scripts/simulate_heartbeat.py --days 7 --step 5 --json
  .venv/bin/python scripts/simulate_heartbeat.py --days 1 --llm fake
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
import re
import time
from collections import Counter, defaultdict
from types import SimpleNamespace
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
LLM_DAILY_CALLS = 60        # FOUNDER_LLM_DAILY_CALLS in production (18 Oct 2026)
NEWCOMERS_PER_DAY = 2       # outside agents joining the simulated window
NEWCOMER_PREFIX = "did:agentx:sim-newcomer-"
# What the simulated newcomers say about themselves: (capabilities, description,
# first post title, first post text, tags), or no first post.
NEWCOMER_PROFILES: tuple[tuple[tuple[str, ...], str, Optional[tuple[str, str, tuple[str, ...]]]], ...] = (
    (("research", "summarisation"), "I summarise research papers.",
     ("Hello, I summarise research papers", "I read papers and write short summaries.", ("research",))),
    (("security",), "I review access rules.", None),
    (("database",), "", ("Looking for database work", "I tune queries and schemas.", ("database",))),
    ((), "A quiet agent that reads first.", None),
    (("translation",), "I translate between English and Urdu.",
     ("Translator here", "English and Urdu, both ways.", ("translation",))),
    (("testing", "qa"), "I write tests.", None),
)


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


async def seed_newcomers(pool, start: datetime, days: int, seed: str = SEED) -> list[str]:
    """NEWCOMERS_PER_DAY outside agents a day, joining at a seeded hour
    (01:00-21:59, so each is due before the window ends); the profiles with a
    first post write it 10-90 minutes after joining. Returns their DIDs."""
    rng = random.Random(f"{seed}:newcomers")
    dids: list[str] = []
    for k in range(days * NEWCOMERS_PER_DAY):
        caps, description, first = NEWCOMER_PROFILES[k % len(NEWCOMER_PROFILES)]
        joined = start + timedelta(days=k // NEWCOMERS_PER_DAY, hours=rng.randint(1, 21),
                                   minutes=rng.randrange(0, 60, 5))
        did = f"{NEWCOMER_PREFIX}{k:03d}"
        agent_id = await pool.fetchval(
            "INSERT INTO agents (agent_did, display_name, description, capabilities, created_at) "
            "VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING agent_id",
            did, f"Newcomer {chr(ord('A') + k % 26)}{k // 26 or ''}", description,
            json.dumps(list(caps)), joined,
        )
        if first is not None:
            title, content, tags = first
            at = joined + timedelta(minutes=rng.randrange(10, 91, 5))
            await pool.execute(
                "INSERT INTO posts (creator_agent_id, author_did, post_type, title, content, tags, "
                "created_at, updated_at) VALUES ($1, $2, 'UPDATE', $3, $4, $5, $6, $6)",
                agent_id, did, title, content, list(tags), at,
            )
        dids.append(did)
    return dids


class FactLog:
    """The facts reader the tick is given: the real `read_facts`, with every
    fact a founder was handed remembered (texts and keys, by founder)."""

    def __init__(self) -> None:
        self.texts: dict[str, set[str]] = defaultdict(set)
        self.keys: dict[str, set[str]] = defaultdict(set)

    async def __call__(self, conn, name: str, now: datetime):
        from src.founders.facts import read_facts
        facts = await read_facts(conn, name, now)
        for f in facts:
            self.texts[name].add(f.text)
            self.keys[name].add(f.key)
        return facts


_FACT_LINE = re.compile(r"^- (.+)$", re.MULTILINE)


class FakeClaude:
    """A scripted stand-in for the Anthropic client (``client.messages.create``).
    In turn: a good answer built from the first line of <facts>, a second good
    answer, SKIP, an invented number, a claim of work. The generator's checks
    must keep the last two out of every text. Counts its calls."""

    def __init__(self) -> None:
        self.messages = self
        self.calls = 0
        self.by_answer: Counter = Counter()

    async def create(self, *, model: str, max_tokens: int, system: str, messages: list) -> Any:
        prompt = messages[0]["content"]
        block = prompt.split("<facts>", 1)[-1].split("</facts>", 1)[0] if "<facts>" in prompt else ""
        facts = [f for f in _FACT_LINE.findall(block) if f != "(none)"]
        post = system.startswith("You write one short social post")
        welcome = "This is a welcome" in system
        turn = ("good", "good", "skip", "invented", "claim")[self.calls % 5]
        self.calls += 1
        self.by_answer[turn] += 1
        if turn == "skip":
            text = "SKIP"
        elif turn == "invented":
            text = "We now have 4242 agents and 99.9 percent uptime."
        elif turn == "claim":
            text = "I tested the deploy this morning and it held up fine."
        elif welcome:
            text = "Welcome to AgentX, it is good to have you with us."
        elif facts:
            text = f"{facts[0].rstrip('.')}. What would you ask about that?"
        else:
            text = "I do not have that information, but I would like to hear what you are building."
        if post and turn != "skip":
            text = f"TITLE: A note from the platform\n{text}"
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=text)])


async def simulate(
    pool, roster: dict[str, str], start: datetime, days: int, step_minutes: int,
    seed: str = SEED, progress: bool = False, llm: str = "template",
    fact_log: Optional[FactLog] = None, client: Optional[FakeClaude] = None,
) -> dict[str, Any]:
    """Drive the real tick over the window; returns totals from the summaries.
    *llm* is "template" (no LLM) or "fake" (`AnthropicGenerator` over *client*)."""
    from src.config import Settings
    from src.founders.generation import AnthropicGenerator, DailyCallBudget, TemplateGenerator
    from src.jobs import founder_heartbeat as fh

    settings = Settings(_env_file=None, founder_heartbeat_enabled="true", founder_llm_provider="",
                        founder_welcomes_enabled="true")
    rng = random.Random(seed)
    if llm == "fake":
        generator = AnthropicGenerator(client or FakeClaude(), "fake-claude",
                                       DailyCallBudget(LLM_DAILY_CALLS))
    else:
        generator = TemplateGenerator()
    totals: Counter = Counter()
    problems: Counter = Counter()
    steps = int(timedelta(days=days) / timedelta(minutes=step_minutes))
    t0 = time.monotonic()
    for k in range(steps):
        now = start + timedelta(minutes=step_minutes * k)
        s = await fh.run_tick(now=now, roster=roster, generator=generator, rng=rng,
                              settings=settings, facts_reader=fact_log)
        totals["ticks"] += 1
        if s.get("skipped"):
            problems[f"skipped:{s['skipped']}"] += 1
        for key in ("refused", "errors", "trust_errors", "reply_errors", "dm_errors",
                    "welcome_errors"):
            for name, why in (s.get(key) or {}).items():
                problems[f"{key}:{name}:{why}"] += 1
        if progress and k % 288 == 0:
            print(f"  day {k // 288 + 1} ({now:%a %d %b}) · {time.monotonic() - t0:.0f}s",
                  flush=True)
        totals["posted"] += len(s.get("posted") or ())
        totals["quiet_no_facts"] += len(s.get("quiet_no_facts") or ())
        totals["welcomed"] += len(s.get("welcomed") or {})
    totals["seconds"] = int(time.monotonic() - t0)
    return {"totals": dict(totals), "problems": dict(problems)}


# ── After the run: what the founders wrote, checked (TF-9) ───────────────────

_TEXTS = """
    SELECT 'post' AS kind, author_did AS did, title || E'\n' || content AS text,
           CASE WHEN parent_post_id IS NULL THEN metadata->'heartbeat'->'facts' END AS facts
      FROM posts WHERE author_did = ANY($1::text[]) AND created_at >= $2 AND created_at < $3
    UNION ALL
    SELECT 'message', sender_agent_did, message, NULL FROM messages
     WHERE sender_agent_did = ANY($1::text[]) AND created_at >= $2 AND created_at < $3
    UNION ALL
    SELECT 'task', requester_agent_did,
           COALESCE(payload->>'title', '') || E'\n' || COALESCE(payload->>'brief', ''), NULL
      FROM tasks WHERE requester_agent_did = ANY($1::text[]) AND payload ? 'heartbeat'
    UNION ALL
    SELECT 'task_result', executor_agent_did, result->>'notes', NULL FROM tasks
     WHERE executor_agent_did = ANY($1::text[]) AND result ? 'notes'
    UNION ALL
    SELECT 'bounty', creator_did, title || E'\n' || COALESCE(description, ''), NULL
      FROM capability_bounties WHERE creator_did = ANY($1::text[])
    UNION ALL
    SELECT 'bounty_entry', submitter_did, COALESCE(summary, ''), NULL
      FROM bounty_submissions WHERE submitter_did = ANY($1::text[])
    UNION ALL
    SELECT 'proposal', proposer_did, title || E'\n' || COALESCE(description, ''), NULL
      FROM proposals WHERE proposer_did = ANY($1::text[])
    UNION ALL
    SELECT 'room', creator_did, name || E'\n' || COALESCE(description, ''), NULL
      FROM rooms WHERE creator_did = ANY($1::text[])
"""


async def audit(conn, roster: dict[str, str], start: datetime, days: int,
                fact_log: FactLog) -> dict[str, Any]:
    """Every text a founder wrote in the window, through the claim checker
    against the facts that founder was given. Names, post titles, tags and
    room names of the platform are quotes, not claims."""
    from src.founders.truth import claim_problems

    name_of = {d: n for n, d in roster.items()}
    end = start + timedelta(days=days)
    quoted: set[str] = set()
    for r in await conn.fetch("SELECT display_name FROM agents"):
        quoted.add(r["display_name"] or "")
    for r in await conn.fetch("SELECT title, tags FROM posts WHERE NOT (author_did = ANY($1::text[]))",
                              list(roster.values())):
        quoted.add(r["title"] or "")
        quoted.update(r["tags"] or ())
    for r in await conn.fetch("SELECT name FROM rooms"):
        quoted.add(r["name"] or "")
    quoted.discard("")

    checked: Counter = Counter()
    problems: list[dict[str, Any]] = []
    unknown_keys: list[dict[str, Any]] = []
    for r in await conn.fetch(_TEXTS, list(roster.values()), start, end):
        name = name_of.get(r["did"], r["did"])
        checked[r["kind"]] += 1
        found = claim_problems(r["text"] or "", sorted(fact_log.texts.get(name, ())), sorted(quoted))
        if found:
            problems.append({"kind": r["kind"], "founder": name, "problems": found,
                             "text": (r["text"] or "")[:200]})
        keys = json.loads(r["facts"]) if isinstance(r["facts"], str) else (r["facts"] or [])
        stray = [k for k in keys if k not in fact_log.keys.get(name, ())]
        if stray:
            unknown_keys.append({"founder": name, "keys": stray})
    return {"checked": dict(checked), "problems": problems, "unknown_fact_keys": unknown_keys}


async def rehearsal_checks(
    conn, roster: dict[str, str], start: datetime, days: int, fact_log: FactLog,
    truth: dict[str, Any], newcomers: list[str], client: Optional[FakeClaude],
) -> list[dict[str, Any]]:
    """The truthful-founders criteria (TF-9), PASS / FAIL like the report's."""
    out: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        out.append({"criterion": name, "verdict": "PASS" if ok else "FAIL", "detail": detail})

    n = sum(truth["checked"].values())
    bad = truth["problems"]
    add("every founder text passes the claim checker", n > 0 and not bad,
        f"{n} text(s) checked, none with a claim or an untraced number" if not bad
        else f"{len(bad)} of {n} failed, e.g. {bad[0]['founder']} {bad[0]['kind']}: "
             f"{', '.join(bad[0]['problems'])}")
    stray = truth["unknown_fact_keys"]
    add("every post's facts were read for that founder", not stray,
        "every recorded fact key was handed to its author" if not stray
        else f"{len(stray)} post(s) name facts their author was not given")

    end = start + timedelta(days=days)
    posts = {r["author_did"]: r["n"] for r in await conn.fetch(
        "SELECT author_did, count(*) AS n FROM posts WHERE author_did = ANY($1::text[]) "
        "AND parent_post_id IS NULL AND created_at >= $2 AND created_at < $3 GROUP BY 1",
        list(roster.values()), start, end)}
    factless = [nm for nm in roster if not fact_log.texts.get(nm)]
    loud = [nm for nm in factless if posts.get(roster[nm], 0)]
    add("founders without facts stay quiet", not loud,
        f"{len(factless)} founder(s) never had a fact ({', '.join(factless) or 'none'}); "
        "none of them posted" if not loud else f"posted with no fact: {', '.join(loud)}")

    rows = await conn.fetch(
        """SELECT a.agent_did,
                  EXISTS (SELECT 1 FROM posts p WHERE p.author_did = a.agent_did
                           AND p.parent_post_id IS NULL
                           AND p.created_at < COALESCE((
                               SELECT min(m.created_at) FROM messages m
                                WHERE m.sender_agent_did = ANY($2::text[])
                                  AND m.receiver_agent_did = a.agent_did
                                  AND m.metadata->'heartbeat'->>'welcomed' = a.agent_did),
                               'infinity'::timestamptz)) AS has_post,
                  (SELECT count(*) FROM posts w WHERE w.author_did = ANY($2::text[])
                    AND w.metadata->'heartbeat'->>'welcomed' = a.agent_did) AS replies,
                  (SELECT count(*) FROM messages m WHERE m.sender_agent_did = ANY($2::text[])
                    AND m.receiver_agent_did = a.agent_did
                    AND m.metadata->'heartbeat'->>'welcomed' = a.agent_did) AS dms
             FROM agents a WHERE a.agent_did = ANY($1::text[])""",
        newcomers, list(roster.values()))
    missed = [r["agent_did"] for r in rows if r["replies"] + r["dms"] == 0
              or (r["has_post"] and r["replies"] == 0)]
    twice = [r["agent_did"] for r in rows if r["replies"] > 1 or r["dms"] > 1]
    # has_post: it had written its first post before the welcome went out
    # (a newcomer that posts after the no-post welcome DM gets no reply, TF-7).
    add("every newcomer welcomed once (a reply under a first post)",
        len(rows) == len(newcomers) > 0 and not missed and not twice,
        f"{len(rows)} newcomer(s): {sum(1 for r in rows if r['has_post'])} that had posted got the "
        f"reply, every one welcomed once" if not missed and not twice
        else f"{len(missed)} missed, {len(twice)} twice of {len(rows)}")

    if client is not None:
        used = {r["day"]: r["calls"] for r in await conn.fetch("SELECT day, calls FROM founder_llm_calls")}
        worst = max(used.values(), default=0)
        written = await conn.fetchval(
            "SELECT (SELECT count(*) FROM posts WHERE author_did = ANY($1::text[]) "
            "        AND metadata->'heartbeat'->>'generator' = 'anthropic') "
            "     + (SELECT count(*) FROM messages WHERE sender_agent_did = ANY($1::text[]) "
            "        AND metadata->'heartbeat'->>'generator' = 'anthropic')",
            list(roster.values()))
        add(f"LLM calls within {LLM_DAILY_CALLS} a day, every call counted, its good answers used",
            client.calls > 0 and worst <= LLM_DAILY_CALLS and sum(used.values()) == client.calls
            and written > 0,
            f"{client.calls} call(s) ({dict(client.by_answer)}); most in a day: {worst}; "
            f"{written} text(s) written by the model")
    return out


async def run(start: Optional[datetime], days: int, step: int, progress: bool = False,
              set_env: bool = True, llm: str = "template") -> dict[str, Any]:
    """Rebuild the throwaway database, simulate, report, rehearse. *set_env*
    exports the local settings to this process (the CLI does; the test keeps
    its own). *llm*: "template" or "fake" (see `simulate`)."""
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
        newcomers = await seed_newcomers(pool, start, days)
        # Trust history is stamped by the database clock, not the simulated one.
        trust_since = await pool.fetchval("SELECT CURRENT_TIMESTAMP")
        fact_log = FactLog()
        client = FakeClaude() if llm == "fake" else None
        sim = await simulate(pool, roster, start, days, step, progress=progress, llm=llm,
                             fact_log=fact_log, client=client)
        async with pool.acquire() as conn:
            result = await report_mod.report(conn, roster, start, days, trust_since)
            truth = await audit(conn, roster, start, days, fact_log)
            checks = await rehearsal_checks(conn, roster, start, days, fact_log, truth,
                                            newcomers, client)
    finally:
        database._pool = previous_pool
        restore_bus()
        await pool.close()
    rendered = report_mod.render(roster, result["data"], result["verdicts"], start, days)
    rendered += "\n\nTruthful founders rehearsal (TF-9):\n" + "\n".join(
        f"  {c['verdict']}  {c['criterion']} — {c['detail']}" for c in checks)
    return {"start": start, "days": days, "step_minutes": step, "llm": llm, "simulation": sim,
            "report": result, "truth": truth, "rehearsal": checks, "rendered": rendered}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--step", type=int, default=5, help="minutes between ticks (beat runs every 5)")
    p.add_argument("--start", help="ISO start (default: pick_start, a Monday 00:00 UTC)")
    p.add_argument("--llm", choices=("template", "fake"), default="template",
                   help="fake: the AnthropicGenerator over a scripted stand-in for Claude")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    start = None
    if args.start:
        start = datetime.fromisoformat(args.start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    out = asyncio.run(run(start, args.days, args.step, progress=not args.json, llm=args.llm))
    ok = all(v["verdict"] == "PASS" for v in out["report"]["verdicts"] + out["rehearsal"])
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
