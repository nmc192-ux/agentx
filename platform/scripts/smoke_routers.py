#!/usr/bin/env python3
"""
Local all-routers smoke harness (Sprint 9, step S9-4)
═════════════════════════════════════════════════════

Answers one question before a router cohort is switched on: "with THIS set of
routers enabled, does any GET endpoint return a 5xx on a correctly-migrated
database?"

What it does, in order:

  1. Builds a throwaway local database (default ``agentx_smoke``): drop,
     create, load ``scripts/init-db.sql`` (the production baseline), then
     ``alembic stamp 001`` + ``alembic upgrade head`` — the same chain CI's
     ``migration-chain`` job runs.
  2. Boots the API with uvicorn on a free localhost port, with the chosen
     ``DISABLED_ROUTERS`` list, rate limits in log-only mode and a
     throwaway Redis DB (15).
  3. Onboards one agent (``POST /onboard`` with a first post) so DID / post
     path parameters point at real rows, and its token exercises the
     authenticated code paths.
  4. Reads ``/openapi.json`` (exactly the mounted routes), and GETs every
     GET route twice — anonymous, then with the agent's Bearer token —
     filling path and required query parameters with plausible values.
  5. Fails (exit 1) on any 5xx or connection error. 4xx is fine: it means the
     handler ran and refused cleanly (404 for a dummy id, 401 without a token,
     422 for a dummy value).

Local only. It refuses any database host other than localhost and any
database name that does not start with ``agentx_smoke``, so it can never
touch the dev ``agentx`` database or anything remote.

Usage (from ``platform/``):

    .venv/bin/python scripts/smoke_routers.py                  # repo default list
    .venv/bin/python scripts/smoke_routers.py --enable memory,graph
    .venv/bin/python scripts/smoke_routers.py --disabled ""    # everything on
    .venv/bin/python scripts/smoke_routers.py --no-migrate     # reuse the DB

Limits: routes hidden from the OpenAPI schema (``include_in_schema=False``),
WebSockets and non-GET methods are not exercised. Streaming responses
(``text/event-stream``) are judged on their status line only.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))

from src.router_config import DEFAULT_DISABLED_ROUTERS  # noqa: E402

DB_HOST = "localhost"
DB_PREFIX = "agentx_smoke"
# 127.0.0.1, not "localhost": src/cache.py switches the cache off outside
# production when the URL contains "localhost", and we want the real cache path.
SMOKE_REDIS_URL = "redis://127.0.0.1:6379/15"
# Throwaway values for a local, single-run process. Not secrets: the database
# uses local trust auth and the JWT key only signs tokens for this run.
SMOKE_JWT_SECRET = "smoke-harness-local-only-not-a-secret-0000000000"
SMOKE_DB_PASSWORD = "smoke-local-trust-auth"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
REQUEST_TIMEOUT = 20.0


# ── Database ──────────────────────────────────────────────────────────────────

def _run(cmd: list[str], env: dict[str, str], label: str) -> None:
    result = subprocess.run(cmd, cwd=PLATFORM_DIR, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"\n✗ {label} failed ({' '.join(cmd)}):\n{result.stdout}\n{result.stderr}\n")
        raise SystemExit(2)


def build_database(db: str, env: dict[str, str]) -> None:
    pg_env = {**os.environ, "PGHOST": DB_HOST, "PGPORT": env["POSTGRES_PORT"], "PGUSER": env["POSTGRES_USER"]}
    for tool in ("dropdb", "createdb", "psql"):
        if not shutil.which(tool):
            sys.stderr.write(f"✗ `{tool}` not found on PATH\n")
            raise SystemExit(2)
    print(f"• rebuilding local database {db!r}")
    _run(["dropdb", "--if-exists", db], pg_env, "dropdb")
    _run(["createdb", db], pg_env, "createdb")
    _run(["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-q", "-f", "scripts/init-db.sql"], pg_env, "init-db.sql")
    print("• migrating: alembic stamp 001 → upgrade head")
    _run([sys.executable, "-m", "alembic", "stamp", "001"], env, "alembic stamp")
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env, "alembic upgrade")


# ── Server ────────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(env: dict[str, str], log_path: Path) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PLATFORM_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            if httpx.get(f"{base}/openapi.json", timeout=2).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.terminate()
    sys.stderr.write(f"✗ API did not start. Last log lines:\n{_tail(log_path)}\n")
    raise SystemExit(2)


def _tail(path: Path, lines: int = 60) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


# ── Probing ───────────────────────────────────────────────────────────────────

def _value_for(name: str, schema: dict, ctx: dict[str, str]) -> str:
    lname = name.lower()
    if "did" in lname:
        return ctx["did"]
    if lname == "post_id" and ctx.get("post_id"):
        return ctx["post_id"]
    if "enum" in schema:
        return str(schema["enum"][0])
    typ = schema.get("type")
    if typ == "integer":
        return "1"
    if typ == "number":
        return "1"
    if typ == "boolean":
        return "true"
    if schema.get("format") == "uuid" or lname.endswith("id"):
        return ZERO_UUID
    return "smoke"


def _resolve(schema: dict, spec: dict) -> dict:
    """Follow a $ref or take the first non-null branch of anyOf."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return spec.get("components", {}).get("schemas", {}).get(name, {})
    for key in ("anyOf", "oneOf", "allOf"):
        for option in schema.get(key, []):
            if option.get("type") != "null":
                return _resolve(option, spec)
    return schema


def build_requests(spec: dict, ctx: dict[str, str]) -> list[tuple[str, str, dict[str, str]]]:
    """Return (template, concrete path, query) for every GET in the schema."""
    out = []
    for template, ops in sorted(spec.get("paths", {}).items()):
        op = ops.get("get")
        if op is None:
            continue
        path, query = template, {}
        for param in op.get("parameters", []):
            schema = _resolve(param.get("schema", {}), spec)
            if param["in"] == "path":
                path = path.replace("{" + param["name"] + "}", _value_for(param["name"], schema, ctx))
            elif param["in"] == "query" and param.get("required"):
                query[param["name"]] = _value_for(param["name"], schema, ctx)
        # Any {param} the schema didn't describe (custom converters).
        path = re.sub(r"\{([^}:]+)(:[^}]+)?\}", lambda m: _value_for(m.group(1), {}, ctx), path)
        out.append((template, path, query))
    return out


def probe(client: httpx.Client, path: str, query: dict, headers: dict) -> tuple[str | int, str]:
    """Return (status code or error label, start of the body)."""
    try:
        with client.stream("GET", path, params=query, headers=headers) as resp:
            if "text/event-stream" in resp.headers.get("content-type", ""):
                return resp.status_code, "(event stream)"
            resp.read()
            return resp.status_code, resp.text[:300]
    except httpx.TimeoutException:
        return "TIMEOUT", ""
    except httpx.HTTPError as exc:
        return f"ERROR {type(exc).__name__}", str(exc)[:300]


def onboard(client: httpx.Client) -> dict[str, str]:
    name = f"smoke-{uuid.uuid4().hex[:8]}"
    resp = client.post("/onboard", json={
        "name": name,
        "capabilities": ["testing"],
        "bio": "Router smoke harness agent (local only).",
        "first_post": {"title": "Smoke test", "content": "Local router smoke harness post.", "tags": ["smoke"]},
    })
    if resp.status_code != 201:
        sys.stderr.write(f"✗ POST /onboard returned {resp.status_code}: {resp.text[:500]}\n")
        raise SystemExit(1)
    body = resp.json()
    return {"did": body["agent_did"], "token": body["token"], "post_id": body.get("post_id") or ""}


# ── Main ──────────────────────────────────────────────────────────────────────

def effective_disabled(args: argparse.Namespace) -> list[str]:
    if args.disabled is not None:
        base = [n.strip().lower() for n in args.disabled.split(",") if n.strip()]
    else:
        base = list(DEFAULT_DISABLED_ROUTERS)
    enable = {n.strip().lower() for n in (args.enable or "").split(",") if n.strip()}
    return [n for n in base if n not in enable]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PREFIX, help="scratch database name (must start with agentx_smoke)")
    parser.add_argument("--pg-user", default=getpass.getuser(), help="local Postgres role (trust auth)")
    parser.add_argument("--pg-port", default="5432")
    parser.add_argument("--disabled", default=None, help="full disabled list, like the DISABLED_ROUTERS env var")
    parser.add_argument("--enable", default=None, help="routers to remove from the disabled list")
    parser.add_argument("--no-migrate", action="store_true", help="reuse the existing scratch database")
    parser.add_argument("--json", dest="json_out", default=None, help="write the full result table here")
    args = parser.parse_args(argv)

    if not args.db.startswith(DB_PREFIX):
        sys.stderr.write(f"✗ refusing database {args.db!r}: name must start with {DB_PREFIX!r}\n")
        return 2

    disabled = effective_disabled(args)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS"))},
        "APP_ENV": "development",
        "POSTGRES_HOST": DB_HOST,
        "POSTGRES_PORT": args.pg_port,
        "POSTGRES_USER": args.pg_user,
        "POSTGRES_DB": args.db,
        "POSTGRES_PASSWORD": SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": SMOKE_REDIS_URL,
        "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": SMOKE_JWT_SECRET,
        "RATE_LIMIT_MODE": "log",
        "DISABLED_ROUTERS": ",".join(disabled),
        # The list above is exact: lift the Tier A lock (S9-4a, development
        # only) so `--enable graph` or `--disabled ""` really mounts them.
        "ALLOW_UNSAFE_ROUTERS": "1",
        "SENTRY_DSN": "",
        "PYTHONWARNINGS": "ignore",
    }

    if not args.no_migrate:
        build_database(args.db, env)

    print(f"• disabled routers ({len(disabled)}): {','.join(sorted(disabled)) or '(none)'}")
    log_path = Path(tempfile.gettempdir()) / f"smoke_routers_{os.getpid()}.log"
    proc, base = start_server(env, log_path)
    try:
        with httpx.Client(base_url=base, timeout=REQUEST_TIMEOUT) as client:
            ctx = onboard(client)
            spec = client.get("/openapi.json").json()
            requests = build_requests(spec, ctx)
            auth = {"Authorization": f"Bearer {ctx['token']}"}
            results, failures = [], []
            for template, path, query in requests:
                anon, anon_body = probe(client, path, query, {})
                authed, auth_body = probe(client, path, query, auth)
                row = {"route": template, "path": path, "anon": anon, "auth": authed}
                results.append(row)
                if any(not isinstance(s, int) or s >= 500 for s in (anon, authed)):
                    failures.append({**row, "anon_body": anon_body, "auth_body": auth_body})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"disabled": sorted(disabled), "results": results, "failures": failures}, indent=2))

    counts: dict[str, int] = {}
    for row in results:
        for s in (row["anon"], row["auth"]):
            key = f"{s // 100}xx" if isinstance(s, int) else str(s)
            counts[key] = counts.get(key, 0) + 1
    print(f"• probed {len(results)} GET routes × 2 — " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    if failures:
        print(f"\n✗ {len(failures)} route(s) failed:")
        for row in failures:
            print(f"   {row['route']:<60} anon={row['anon']} auth={row['auth']}")
            print(f"      {row['auth_body'] or row['anon_body']}")
        print(f"\nServer log tail ({log_path}):\n{_tail(log_path, 80)}")
        return 1
    print("✓ smoke green: no 5xx on any GET route")
    log_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
