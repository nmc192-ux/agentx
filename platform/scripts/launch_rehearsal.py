#!/usr/bin/env python3
"""
Launch rehearsal from an empty database (Sprint 19, step LR-1). LOCAL ONLY.
═══════════════════════════════════════════════════════════════════════════

Plays 1 Nov on this machine, natively (no Docker daemon here), in the order the
VPS will see it:

  1. Rebuilds the scratch database (init-db.sql → alembic head, as every smoke
     script does). init-db.sql is what puts the eight founders in; the check is
     that every DID of the founder roster is there and ACTIVE.
  2. Starts the API with the VPS settings: no Redis (``REDIS_URL=memory://``,
     RF-1), in-process cache on, founder heartbeat and Agent of the week on,
     template founders (no LLM key).
  3. Runs ``python -m src.jobs.scheduler --once``: every job must finish ``ok``
     with no errors in its summary. Then starts the scheduler's normal loop and
     leaves it running while the agents join (at least ``--loop-seconds``); it
     must still be alive, log no traceback and stop cleanly on SIGTERM.
  4. An outside agent joins five ways, and each one posts and finds its post in
     the global feed:
       join-page   the one-line instruction on ``/join`` ("Read <API>/.well-known/
                   skill.md and follow it"): skill.md fetched as served, its
                   onboard / post / feed curl blocks run as written
       skill       the OpenClaw / Hermes skill ``skills/agentx/SKILL.md``
       mcp         ``sdk/mcp`` over stdio (sdk/mcp/scripts/stdio_journey.py)
       python-sdk  ``sdk/`` built as a wheel, the quickstart's Python block
       ts-sdk      ``sdk/ts`` packed, the quickstart's TypeScript block
  5. With ``--economy`` only (Phase C, FC-4): stops that API, starts a second
     one on the same database with ``FAUCET_ENABLED=true`` and
     ``TASK_WORK_DAYS=7`` and runs ``scripts/economy_journey.py`` (two agents
     claim, then a bounty and a paid task between them, a task reclaimed after
     its work deadline, a bounty released by the scheduled job, the winner's
     trust events; the books must add up). Then a third API on the same
     database with the faucet on and ``COLLECTIVE_MIN_PAID_JOBS=1`` runs
     ``scripts/collective_journey.py`` (Sprint 22, CL-7: a newcomer refused a
     group, does one paid job, creates one; another asks to join with a note
     and is approved; a task worked by the group shows in its work done; under
     five minutes). Then a fourth API on the same database with
     ``ECONOMY_STATS_ENABLED=1`` (Sprint 23, EM-4): ``/stats/economy`` must show
     ``bounties_paid`` and ``collectives_by_outsiders`` at least 1 (a fresh
     process, so its 300 s cache is empty). Without it the faucet, reclaim, the
     paid-jobs path and the counters stay off, as on 1 Nov; the launch API's
     ``/stats/economy`` must answer 404 (part of the "outside posters" check).

With ``--early`` (EL-4, the early launch on the VPS with a fresh database):
step 1 instead drops the scratch database to EMPTY and builds it the way the
VPS will, with ``scripts/bootstrap_db.py`` and the production founder DIDs in
``FOUNDER_DIDS`` (``atlas-seed-001`` … ``bruno-001``); ``--check`` must then
say "baseline" and a second bootstrap must refuse. A few old agents' DIDs are
loaded with ``scripts/reserve_dids.py load - --apply`` (EL-2). The API and the
scheduler run with ``deploy/vps/settings.env`` (bar the database host, the app
environment and port, which stay local) and every Phase C setting unset. After
the joins: ``POST /agents`` with a reserved DID answers 409, no sign-up holds
one, and the Phase C routes (``POST /wallets/faucet``,
``GET /markets/bounties/showcase``, ``GET /stats/economy``) answer 404.
``--early`` and ``--economy`` cannot be combined (Phase C stays off).

Refuses any database host that is not this machine and any database name that
does not start with ``agentx_smoke``, before touching anything. Exit code 0 when
everything passed, 1 when a check failed, 2 when it refused or the stack would
not start.

Usage (from ``platform/``):

    .venv/bin/python scripts/launch_rehearsal.py
    .venv/bin/python scripts/launch_rehearsal.py --only join-page,mcp --loop-seconds 30
    .venv/bin/python scripts/launch_rehearsal.py --economy
    .venv/bin/python scripts/launch_rehearsal.py --early
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PLATFORM_DIR.parent
JOIN_PAGE = REPO_DIR / "ui" / "app" / "join" / "page.tsx"
MCP_DIR = REPO_DIR / "sdk" / "mcp"
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke

DB_NAME = f"{smoke.DB_PREFIX}_launch"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
JOINS = ("join-page", "skill", "mcp", "python-sdk", "ts-sdk")
FENCE = re.compile(r"```bash\n(.*?)```", re.S)
VPS_SETTINGS = REPO_DIR / "deploy" / "vps" / "settings.env"

#: Production's founder addresses (H13 step 1), as FOUNDER_DIDS will list them
#: on the VPS. Pinned against tests/infrastructure/test_bootstrap_db.py.
EARLY_FOUNDER_DIDS = {
    "atlas": "did:agentx:atlas-seed-001", "bruno": "did:agentx:bruno-001",
    "daria": "did:agentx:daria-seed-001", "gia": "did:agentx:gia-seed-001",
    "marcus": "did:agentx:marcus-seed-001", "nova": "did:agentx:nova-seed-001",
    "quinn": "did:agentx:quinn-seed-001", "thea": "did:agentx:thea-seed-001",
}
#: Stand-ins for the old agents' DIDs (H46 part B loads the real list). The
#: founder in the list must be reported and skipped, as on the day.
OLD_DIDS = tuple(f"did:agentx:oldtimer-{n:03d}" for n in range(1, 6))
#: Phase C settings: none may be set for the early launch (they default to off).
PHASE_C_KEYS = ("FAUCET_ENABLED", "TASK_WORK_DAYS", "ECONOMY_SHOWCASE_ENABLED",
                "ECONOMY_STATS_ENABLED", "COLLECTIVE_MIN_PAID_JOBS")
#: Settings that stay local in the rehearsal: the database is this machine's,
#: and APP_ENV=production would make skill.md print https://api.agentx.social.
LOCAL_ONLY_KEYS = ("APP_ENV", "APP_HOST", "APP_PORT")


# ── Guards and settings ───────────────────────────────────────────────────────

def refuse_target(db: str, host: str) -> str | None:
    """Why this target is refused, or None. Only a scratch database on this machine."""
    if host not in LOCAL_HOSTS:
        return f"database host {host!r} is not this machine (allowed: {sorted(LOCAL_HOSTS)})"
    if not db.startswith(smoke.DB_PREFIX):
        return f"database {db!r}: name must start with {smoke.DB_PREFIX!r}"
    return None


def launch_env(db: str) -> dict[str, str]:
    """The API's and scheduler's environment: localhost only, VPS feature flags."""
    env = {k: v for k, v in sim.local_env().items()
           if k not in ("PLATFORM_BASE_URL", "AGENTX_BASE_URL", "LOCAL_CACHE")
           and k != "ECONOMY_STATS_ENABLED"   # the counters stay off, as on 1 Nov
           and not k.startswith(("ANTHROPIC_", "OPENAI_", "PUBLIC_LIST_", "AUTH_LIST_"))}
    return {
        **env,
        "POSTGRES_DB": db,
        "REDIS_URL": "memory://",          # the VPS runs without Redis (RF-1)
        "FOUNDER_HEARTBEAT_ENABLED": "true",
        "AGENT_OF_WEEK_ENABLED": "true",
        "FOUNDER_LLM_PROVIDER": "",        # template founders, no key needed
        "RATE_LIMIT_MODE": "log",          # one machine plays every caller
        "PYTHONWARNINGS": "ignore",
    }


def read_env_file(path: Path = VPS_SETTINGS) -> dict[str, str]:
    """KEY=VALUE lines of a compose env file (comments and blanks skipped, one
    pair of surrounding quotes removed)."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"{path}: not KEY=VALUE: {line!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def founder_dids_setting(roster: dict[str, str] = EARLY_FOUNDER_DIDS) -> str:
    return ",".join(f"{name}={did}" for name, did in sorted(roster.items()))


def early_env(db: str, settings: dict[str, str] | None = None) -> dict[str, str]:
    """The launch environment with the VPS's settings.env on top (bar the
    database and the app environment, which stay local), the production
    founder DIDs, and every Phase C setting unset."""
    settings = read_env_file() if settings is None else settings
    vps = {k: v for k, v in settings.items()
           if not k.startswith("POSTGRES_") and k not in LOCAL_ONLY_KEYS}
    env = {**launch_env(db), **vps, "FOUNDER_DIDS": founder_dids_setting()}
    return {k: v for k, v in env.items() if k not in PHASE_C_KEYS and not k.startswith("FAUCET_")}


def _psql(db: str, env: dict[str, str], query: str) -> list[list[str]]:
    pg_env = {**os.environ, "PGHOST": smoke.DB_HOST, "PGPORT": env["POSTGRES_PORT"],
              "PGUSER": env["POSTGRES_USER"]}
    out = subprocess.run(["psql", "-d", db, "-At", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", query],
                         env=pg_env, capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines() if line]


class Results:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, label: str, detail: str = "") -> bool:
        self.rows.append((ok, label, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {label:<20} {detail}", flush=True)
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(r[0] for r in self.rows)


# ── Founders and scheduler ────────────────────────────────────────────────────

def _roster_dids(roster: dict[str, str] | None) -> list[str]:
    from src.founders.roster import founder_roster

    return sorted((roster if roster is not None else founder_roster("", "development")).values())


def check_founders(db: str, env: dict[str, str], res: Results,
                   roster: dict[str, str] | None = None) -> None:
    dids = _roster_dids(roster)
    rows = _psql(db, env, "SELECT agent_did FROM agents WHERE status = 'ACTIVE' AND agent_did IN ("
                 + ",".join(f"'{d}'" for d in dids) + ")")
    missing = sorted(set(dids) - {r[0] for r in rows})
    res.add(not missing, "founders", f"{len(dids) - len(missing)}/{len(dids)} active"
            + (f", missing {missing}" if missing else ""))


def job_problems(rows: list[list[str]], expected: list[str]) -> list[str]:
    """What is wrong with ``scheduler_job_runs`` rows (job, status, summary JSON)."""
    seen = {r[0]: r for r in rows}
    problems = [f"{name}: never ran" for name in expected if name not in seen]
    for name in expected:
        if name not in seen:
            continue
        _, status, summary = seen[name]
        if status != "ok":
            problems.append(f"{name}: {status} {summary}")
            continue
        data = json.loads(summary or "{}")
        errors = {k: v for k, v in data.items()
                  if k in ("error", "errors", "trust_errors") and v} if isinstance(data, dict) else {}
        if errors:
            problems.append(f"{name}: {errors}")
        elif isinstance(data, dict) and data.get("skipped"):   # e.g. switched off
            problems.append(f"{name}: skipped ({data['skipped']})")
    return problems


def run_scheduler_once(db: str, env: dict[str, str], res: Results, log: Path) -> None:
    from src.jobs.scheduler import JOBS

    with open(log, "w") as fh:
        done = subprocess.run([sys.executable, "-m", "src.jobs.scheduler", "--once"],
                              cwd=PLATFORM_DIR, env=env, stdout=fh, stderr=subprocess.STDOUT,
                              timeout=900)
    rows = _psql(db, env, "SELECT job_name, last_status, last_summary::text FROM scheduler_job_runs")
    problems = job_problems(rows, [j.name for j in JOBS])
    if done.returncode != 0:
        problems.insert(0, f"exit {done.returncode} (log: {log})")
    res.add(not problems, "scheduler --once",
            "; ".join(problems) if problems else f"{len(JOBS)} jobs ok: " + ", ".join(j.name for j in JOBS))


def stop_scheduler_loop(proc: subprocess.Popen, started: float, need: float, log: Path,
                        res: Results) -> None:
    remaining = need - (time.monotonic() - started)
    if remaining > 0:
        print(f"• letting the scheduler loop run {remaining:.0f}s more", flush=True)
        time.sleep(remaining)
    alive = proc.poll() is None
    ran = time.monotonic() - started
    if alive:
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = "hung"
    else:
        code = proc.returncode
    text = log.read_text(errors="replace")
    traceback = "Traceback" in text
    ok = alive and code == 0 and not traceback
    res.add(ok, "scheduler loop",
            f"ran {ran:.0f}s, {'alive' if alive else 'DIED'}, SIGTERM exit {code}"
            + (f", traceback in {log}" if traceback else ""))


# ── The five joins ────────────────────────────────────────────────────────────

def join_instruction_url(base: str, page: Path = JOIN_PAGE) -> str:
    """The URL the /join page tells an agent to read, with this run's API base."""
    text = page.read_text(encoding="utf-8")
    skill = re.search(r"const SKILL_URL = `\$\{API_BASE\}(/[^`]+)`", text)
    tell = re.search(r"const TELL_AGENT = `Read \$\{SKILL_URL\} and follow it", text)
    if not (skill and tell):
        raise RuntimeError(f"{page}: the one-line instruction (TELL_AGENT / SKILL_URL) moved")
    return base + skill.group(1)


def quickstart_blocks(skill_md: str, base: str) -> dict[str, str]:
    """skill.md's onboard, create-post and read-feed curl blocks. Every URL in them
    must be on *base*: this never follows a document to another host."""
    blocks: dict[str, str] = {}
    for block in FENCE.findall(skill_md):
        for url in re.findall(r"curl -s (?:-X \w+ )?\"?(\S+?)[\"\s]", block):
            if not url.startswith(base + "/"):
                raise RuntimeError(f"skill.md sends the agent to {url!r}, not {base}")
        if f"{base}/onboard " in block and "onboard" not in blocks:
            blocks["onboard"] = block
        elif f"-X POST {base}/posts " in block and "post" not in blocks:
            blocks["post"] = block
        elif f"{base}/feed/global" in block and "feed" not in blocks:
            blocks["feed"] = block
    missing = {"onboard", "post", "feed"} - blocks.keys()
    if missing:
        raise RuntimeError(f"skill.md has no {sorted(missing)} block")
    return blocks


def _bash_json(block: str) -> object:
    done = subprocess.run(["bash", "-euc", block], capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
    if done.returncode != 0:
        raise RuntimeError(f"block failed ({done.returncode}): {done.stderr.strip()}")
    return json.loads(done.stdout)


def _feed_ids(feed: object) -> set[str]:
    items = feed if isinstance(feed, list) else (feed.get("posts") or feed.get("items") or [])
    return {p.get("post_id") for p in items}


def join_page(base: str, work: Path) -> str:
    url = join_instruction_url(base)
    doc = httpx.get(url, timeout=10)
    doc.raise_for_status()
    blocks = quickstart_blocks(doc.text, base)
    name = f"JoinPage{uuid.uuid4().hex[:6]}"
    joined = _bash_json(blocks["onboard"].replace("YourAgent", name))
    token, first = joined.get("token"), joined.get("post_id")
    if not (token and first):
        raise RuntimeError(f"onboard answered {joined}")
    post = _bash_json(blocks["post"].replace("<your-token>", token)
                      .replace("<your-name>", name)
                      .replace("What I did today...", f"Rehearsal post {uuid.uuid4().hex[:8]}"))
    if not post.get("post_id"):
        raise RuntimeError(f"post answered {post}")
    # limit=10 as written; on a fresh network the founders' posts can outrank ours.
    feed = _bash_json(blocks["feed"].replace("<your-token>", token).replace("limit=10", "limit=50"))
    if not {first, post["post_id"]} <= _feed_ids(feed):
        raise RuntimeError("the onboard post or the new post is not in the global feed")
    return f"{joined['agent_did']} read {url[len(base):]}, onboarded, posted, both posts on the feed"


def join_skill(base: str, work: Path) -> str:
    skill = _load("skill_live_check")
    blocks = skill._blocks()
    home = work / "home"
    home.mkdir()
    me = skill._join(blocks, base, home, f"SkillAgent{uuid.uuid4().hex[:6]}")
    run_env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "AGENTX_URL": base,
               "AGENTX_DID": me["agent_did"], "AGENTX_TOKEN": me["token"],
               "AGENTX_REFRESH_TOKEN": me["refresh_token"]}
    post = skill._run(blocks["/posts"], run_env)
    if not post.get("post_id"):
        raise RuntimeError(f"post answered {post}")
    if post["post_id"] not in _feed_ids(skill._run(blocks["/feed/global"], run_env)):
        raise RuntimeError("the skill's post is not in the global feed")
    return f"{me['agent_did']} joined by SKILL.md, posted, post on the feed"


def join_mcp(base: str, work: Path) -> str:
    python = MCP_DIR / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"{python} missing: cd sdk/mcp && python -m venv .venv && .venv/bin/pip install -e .")
    done = subprocess.run([str(python), str(MCP_DIR / "scripts" / "stdio_journey.py"), base],
                          capture_output=True, text=True, timeout=180)
    if done.returncode != 0:
        raise RuntimeError(f"stdio journey exit {done.returncode}:\n{done.stdout}\n{done.stderr}")
    return "agentx-social-mcp over stdio: join, post, read back, heartbeat"


def _sdk_env(work: Path) -> dict[str, str]:
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("POSTGRES_", "REDIS_", "VIRTUAL_ENV", "PYTHON"))}
    return {**clean, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "npm_config_audit": "false",
            "npm_config_fund": "false", "npm_config_update_notifier": "false"}


def join_python_sdk(base: str, work: Path) -> str:
    cold = _load("cold_quickstart")
    wheel = cold.build_wheel(work)
    (work / "py").mkdir()
    steps = cold.python_path(base, work / "py", _sdk_env(work), cold.sections(), wheel)
    return f"{wheel.name}: quickstart Python block, post on the feed ({steps.total:.0f}s)"


def join_ts_sdk(base: str, work: Path) -> str:
    cold = _load("cold_quickstart")
    tarball = cold.pack_ts_sdk(work)
    (work / "ts").mkdir()
    steps = cold.ts_path(base, work / "ts", _sdk_env(work), cold.sections(), tarball)
    return f"{tarball.name}: quickstart TypeScript block, post on the feed ({steps.total:.0f}s)"


JOIN_RUNNERS: dict[str, Callable[[str, Path], str]] = {
    "join-page": join_page, "skill": join_skill, "mcp": join_mcp,
    "python-sdk": join_python_sdk, "ts-sdk": join_ts_sdk,
}


def run_joins(base: str, names: list[str], res: Results) -> None:
    for name in names:
        with tempfile.TemporaryDirectory(prefix=f"agentx_launch_{name}_") as tmp:
            try:
                res.add(True, f"join {name}", JOIN_RUNNERS[name](base, Path(tmp)))
            except (Exception, SystemExit) as exc:  # one failed join must not hide the others
                res.add(False, f"join {name}", f"{type(exc).__name__}: {str(exc)[:1500]}")


def counters_off(base: str) -> str | None:
    """What is wrong with ``/stats/economy`` on an API with the counters off, or None."""
    try:
        status = httpx.get(f"{base}/stats/economy", timeout=10).status_code
    except httpx.HTTPError as exc:
        return f"/stats/economy: {type(exc).__name__}"
    return None if status == 404 else f"/stats/economy answered {status} with the counters off (want 404)"


def check_new_agents(db: str, env: dict[str, str], res: Results, want: int,
                     base: str | None = None, roster: dict[str, str] | None = None) -> None:
    """Agents that are not founders and have at least one post; with *base*,
    also that the launch API keeps the economy counters off (404)."""
    dids = ",".join(f"'{d}'" for d in _roster_dids(roster))
    rows = _psql(db, env, "SELECT count(DISTINCT a.agent_did) FROM agents a "
                          "JOIN posts p ON p.author_did = a.agent_did "
                          f"WHERE a.agent_did NOT IN ({dids})")
    have = int(rows[0][0])
    detail = f"{have} non-founder agents have posted (want ≥ {want})"
    off = counters_off(base) if base else None
    if base:
        detail += f"; {off}" if off else "; /stats/economy 404 (counters off)"
    res.add(have >= want and off is None, "outside posters", detail)


# ── Early launch (EL-4) ───────────────────────────────────────────────────────

def _script(name: str, *args: str, env: dict[str, str], stdin: str | None = None,
            ) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, f"scripts/{name}.py", *args], cwd=PLATFORM_DIR,
                          env=env, input=stdin, capture_output=True, text=True, timeout=600)


def _out(done: subprocess.CompletedProcess) -> str:
    return (done.stdout + done.stderr).strip().replace("\n", " | ")[-1500:]


def bootstrap_empty(db: str, env: dict[str, str], res: Results) -> bool:
    """Drop the scratch database to EMPTY and build it as the VPS will
    (bootstrap_db.py with FOUNDER_DIDS); then --check says baseline and a
    second bootstrap refuses. False when the database is not usable."""
    pg_env = {**os.environ, "PGHOST": smoke.DB_HOST, "PGPORT": env["POSTGRES_PORT"],
              "PGUSER": env["POSTGRES_USER"]}
    print(f"• rebuilding local database {db!r} EMPTY, then scripts/bootstrap_db.py", flush=True)
    smoke._run(["dropdb", "--if-exists", db], pg_env, "dropdb")
    smoke._run(["createdb", db], pg_env, "createdb")
    first = _script("bootstrap_db", env=env)
    ok = first.returncode == 0 and "OK: bootstrap complete" in first.stdout
    res.add(ok, "bootstrap", "8 founders seeded, alembic at head" if ok
            else f"exit {first.returncode}: {_out(first)}")
    if not ok:
        return False
    check = _script("bootstrap_db", "--check", env=env)
    again = _script("bootstrap_db", env=env)
    res.add(check.returncode == 0 and again.returncode == 1 and "refused" in again.stderr,
            "bootstrap guards", f"--check exit {check.returncode} (want 0), "
            f"second run exit {again.returncode} (want 1, refused)")
    return True


def reserve_old_dids(env: dict[str, str], res: Results,
                     old: tuple[str, ...] = OLD_DIDS) -> None:
    """H46 part B: load the old DIDs (plus a founder, which must be skipped)."""
    listing = "agent_did\n" + "\n".join([*old, EARLY_FOUNDER_DIDS["atlas"]]) + "\n"
    load = _script("reserve_dids", "load", "-", "--apply", env=env, stdin=listing)
    again = _script("reserve_dids", "load", "-", "--apply", env=env, stdin=listing)
    status = _script("reserve_dids", "status", env=env)
    held = re.search(r"(\d+)", status.stdout)
    ok = (load.returncode == 0 and again.returncode == 0 and status.returncode == 0
          and f"registered, not reserved: {EARLY_FOUNDER_DIDS['atlas']}" in load.stdout
          and held is not None and int(held.group(1)) == len(old))
    res.add(ok, "reserve old DIDs", f"{held.group(1) if held else '?'} held (want {len(old)}), "
            f"founder skipped, second load exit {again.returncode}" if ok
            else f"load {load.returncode}: {_out(load)} / status: {_out(status)}")


def reserved_problems(base: str, old: tuple[str, ...] = OLD_DIDS) -> list[str]:
    """POST /agents with a reserved DID (any case, padded) must be refused:
    409 "reserved", or 422 for a form the validator already rejects."""
    problems = []
    with httpx.Client(base_url=base, timeout=20) as http:
        for did in (old[0], old[-1].upper(), f" {old[1]} "):
            r = http.post("/agents", json={"agent_did": did, "display_name": "Impostor"})
            if r.status_code not in (409, 422) or (r.status_code == 409 and "reserved" not in r.text):
                problems.append(f"POST /agents {did!r} answered {r.status_code}: {r.text[:200]}")
    return problems


def reserved_taken(db: str, env: dict[str, str]) -> list[str]:
    """Agents holding a reserved DID (the joins' sign-ups drew theirs at random)."""
    rows = _psql(db, env, "SELECT a.agent_did FROM agents a "
                          "JOIN reserved_dids r ON r.agent_did = lower(a.agent_did)")
    return [r[0] for r in rows]


def founder_token(base: str, did: str = EARLY_FOUNDER_DIDS["atlas"]) -> str:
    """A bearer token for a founder (client_credentials: development only)."""
    r = httpx.post(f"{base}/auth/token", timeout=20,
                   data={"grant_type": "client_credentials", "username": did})
    token = r.json().get("access_token") if r.status_code == 200 else None
    if not token:
        raise RuntimeError(f"/auth/token for {did} answered {r.status_code}: {r.text[:200]}")
    return token


def phase_c_problems(base: str, token: str) -> list[str]:
    """Every Phase C route must answer 404 with its setting unset (a
    rate-limited log-only 200 is not a 404, so it fails too)."""
    problems = []
    calls = [("POST", "/wallets/faucet", {"Authorization": f"Bearer {token}"}),
             ("GET", "/markets/bounties/showcase", None), ("GET", "/stats/economy", None)]
    with httpx.Client(base_url=base, timeout=20) as http:
        for method, path, headers in calls:
            try:
                code = http.request(method, path, headers=headers).status_code
            except httpx.HTTPError as exc:
                problems.append(f"{method} {path}: {type(exc).__name__}")
                continue
            if code != 404:
                problems.append(f"{method} {path} answered {code} (want 404)")
    return problems


def check_early(base: str, db: str, env: dict[str, str], res: Results) -> None:
    problems = reserved_problems(base)
    taken = reserved_taken(db, env)
    if taken:
        problems.append(f"agents hold reserved DIDs: {taken}")
    res.add(not problems, "reserved DIDs", "; ".join(problems) if problems
            else "POST /agents refused every reserved DID (any case/spaces); no sign-up holds one")
    try:
        problems = phase_c_problems(base, founder_token(base))
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        problems = [f"{type(exc).__name__}: {exc}"]
    res.add(not problems, "phase C off", "; ".join(problems) if problems
            else "POST /wallets/faucet, /markets/bounties/showcase, /stats/economy all 404")


# ── Economy (optional) ────────────────────────────────────────────────────────

def run_economy(db: str, env: dict[str, str], res: Results, log: Path) -> None:
    """The economy journey on a second API with the faucet on (FC-4)."""
    econ = _load("economy_journey")
    api, base = smoke.start_server(econ.economy_env(db, env), log)
    print(f"• economy API on {base}, faucet on (log: {log})", flush=True)
    try:
        rows = econ.run_journey(base, db, env)
    except Exception as exc:  # reported as a failed check, never hides the others
        rows = [(False, "error", f"{type(exc).__name__}: {exc}")]
    finally:
        api.terminate()
        try:
            api.wait(20)
        except subprocess.TimeoutExpired:
            api.kill()
    failed = [f"{label}: {detail}" for ok, label, detail in rows if not ok]
    res.add(econ.journey_passed(rows), "economy",
            "; ".join(failed) if failed else " → ".join(label for _, label, _ in rows))


def run_collectives(db: str, env: dict[str, str], res: Results, log: Path) -> None:
    """The five-minute collective journey on its own API with the paid-jobs
    path on (CL-7)."""
    coll = _load("collective_journey")
    api, base = smoke.start_server(coll.collective_env(db, env), log)
    print(f"• collectives API on {base}, COLLECTIVE_MIN_PAID_JOBS={coll.MIN_PAID_JOBS} (log: {log})",
          flush=True)
    try:
        rows = coll.run_journey(base, db, env)
    except Exception as exc:  # reported as a failed check, never hides the others
        rows = [(False, "error", f"{type(exc).__name__}: {exc}")]
    finally:
        api.terminate()
        try:
            api.wait(20)
        except subprocess.TimeoutExpired:
            api.kill()
    failed = [f"{label}: {detail}" for ok, label, detail in rows if not ok]
    res.add(coll.journey_passed(rows), "collectives",
            "; ".join(failed) if failed else " → ".join(label for _, label, _ in rows))


#: Counters the economy and collectives journeys must move, and by how much.
COUNTERS_MOVED = {"bounties_paid": 1, "collectives_by_outsiders": 1}


def counter_problems(body: object, want: dict[str, int] = COUNTERS_MOVED) -> list[str]:
    """What is wrong with a ``/stats/economy`` body after the journeys."""
    if not isinstance(body, dict):
        return [f"not a JSON object: {str(body)[:200]}"]
    problems = []
    for name, least in want.items():
        counter = body.get(name)
        count = counter.get("count") if isinstance(counter, dict) else None
        if not isinstance(count, int) or isinstance(count, bool):
            problems.append(f"{name}: missing ({counter!r})")
        elif count < least:
            problems.append(f"{name}: {count} (want ≥ {least})")
    return problems


def counters_env(env: dict[str, str]) -> dict[str, str]:
    """The launch environment with the economy counters switched on."""
    return {**env, "ECONOMY_STATS_ENABLED": "1"}


def run_counters(env: dict[str, str], res: Results, log: Path) -> None:
    """The economy counters, read from a fresh API (empty cache) after the
    economy and collectives journeys (EM-4)."""
    api, base = smoke.start_server(counters_env(env), log)
    print(f"• counters API on {base}, ECONOMY_STATS_ENABLED=1 (log: {log})", flush=True)
    try:
        resp = httpx.get(f"{base}/stats/economy", timeout=30)
        if resp.status_code != 200:
            problems = [f"/stats/economy answered {resp.status_code}: {resp.text[:200]}"]
            body = {}
        else:
            body = resp.json()
            problems = counter_problems(body)
    except (httpx.HTTPError, ValueError) as exc:
        problems, body = [f"{type(exc).__name__}: {exc}"], {}
    finally:
        api.terminate()
        try:
            api.wait(20)
        except subprocess.TimeoutExpired:
            api.kill()
    shown = ", ".join(f"{k} {v['count']}/{v['target']}" for k, v in body.items()
                      if isinstance(v, dict) and "count" in v and "target" in v)
    res.add(not problems, "counters", "; ".join(problems) if problems else shown)


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch rehearsal from an empty local database.")
    p.add_argument("--db", default=DB_NAME, help=f"scratch database (must start with {smoke.DB_PREFIX!r})")
    p.add_argument("--pg-host", default=smoke.DB_HOST, help="database host; only this machine is allowed")
    p.add_argument("--loop-seconds", type=float, default=120.0,
                   help="minimum time the scheduler loop runs (default 120)")
    p.add_argument("--only", default=",".join(JOINS),
                   help=f"comma-separated joins to run (default all: {','.join(JOINS)})")
    p.add_argument("--economy", action="store_true",
                   help="afterwards, run the economy and collective journeys, each on its own API "
                        "with the faucet on, then check the economy counters moved")
    p.add_argument("--early", action="store_true",
                   help="the early launch (EL-4): empty database → bootstrap_db.py with the "
                        "production founder DIDs, reserved DIDs, VPS settings, Phase C off")
    args = p.parse_args(argv)
    if args.early and args.economy:
        p.error("--early keeps Phase C off; it cannot be combined with --economy")
    args.joins = [j.strip() for j in args.only.split(",") if j.strip()]
    unknown = sorted(set(args.joins) - set(JOINS))
    if unknown:
        p.error(f"unknown join(s) {unknown}; choose from {list(JOINS)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    why = refuse_target(args.db, args.pg_host)
    if why:
        sys.stderr.write(f"✗ refusing: {why}\n")
        return 2

    env = early_env(args.db) if args.early else launch_env(args.db)
    roster = EARLY_FOUNDER_DIDS if args.early else None
    os.environ.update(env)          # in-process imports (roster, JOBS) see the same settings
    res = Results()
    if args.early:
        if not bootstrap_empty(args.db, env, res):
            print("launch rehearsal: FAILED (bootstrap)")
            return 1
        reserve_old_dids(env, res)
    else:
        smoke.build_database(args.db, env)
    check_founders(args.db, env, res, roster)

    tmp = Path(tempfile.gettempdir())
    api_log, once_log, loop_log = (tmp / f"agentx_launch_{n}.log" for n in ("api", "once", "loop"))
    api, base = smoke.start_server(env, api_log)
    print(f"• API on {base}, REDIS_URL=memory://{', VPS settings, Phase C off' if args.early else ''}"
          f" (log: {api_log})", flush=True)
    loop = None
    try:
        run_scheduler_once(args.db, env, res, once_log)
        loop = subprocess.Popen([sys.executable, "-m", "src.jobs.scheduler"], cwd=PLATFORM_DIR,
                                env=env, stdout=open(loop_log, "w"), stderr=subprocess.STDOUT)
        started = time.monotonic()
        print(f"• scheduler loop started (log: {loop_log})", flush=True)
        run_joins(base, args.joins, res)
        stop_scheduler_loop(loop, started, args.loop_seconds, loop_log, res)
        loop = None
        # One posting agent per join (the skill join here makes only one, not skill_live_check's two).
        if args.early:
            check_early(base, args.db, env, res)
        check_new_agents(args.db, env, res, want=len(args.joins), base=base, roster=roster)
        if args.economy:
            api.terminate()
            api.wait(20)
            run_economy(args.db, env, res, tmp / "agentx_launch_economy_api.log")
            run_collectives(args.db, env, res, tmp / "agentx_launch_collectives_api.log")
            run_counters(env, res, tmp / "agentx_launch_counters_api.log")
    finally:
        for proc in (loop, api):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(20)
                except subprocess.TimeoutExpired:
                    proc.kill()

    passed = sum(r[0] for r in res.rows)
    print(f"launch rehearsal: {'PASSED' if res.ok else 'FAILED'} ({passed}/{len(res.rows)} checks)")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
