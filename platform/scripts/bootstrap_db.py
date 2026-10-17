#!/usr/bin/env python3
"""
Build an EMPTY database into a working AgentX database (EL-1, early launch).

The base schema and the eight founders come from ``scripts/init-db.sql``
(migration 001 is a no-op), and that file seeds every founder as
``did:agentx:<name>-001``. Production's founders have other addresses
(``atlas-seed-001`` … ``bruno-001``, H13 step 1), listed in ``FOUNDER_DIDS``.
A fresh VPS database built with plain ``alembic upgrade head`` would have no
tables to migrate, and one built from init-db.sql as it stands would give the
founders the wrong addresses (so the heartbeat refuses all of them, and the
1 Nov import could not merge them). This script does it right, once:

  1. refuses unless the database has no tables at all (``public`` schema);
  2. reads ``FOUNDER_DIDS`` (the API's own setting) with
     ``founders.roster.parse_founder_dids`` and refuses unless all eight
     founders are listed;
  3. in ONE transaction: init-db.sql with each founder's DID replaced by the
     roster's, ``alembic stamp 001``, and a check that every founder resolves
     through ``resolve_founder`` (ACTIVE, right name, right address). Any
     failure rolls the whole thing back: nothing is written;
  4. then ``alembic upgrade head`` and the same founder check again.

It never touches a database that has a table in it, so it cannot change or
delete existing data. Two runs at once are serialised by an advisory lock;
the second finds tables and refuses.

``--check`` (used by ``deploy/vps/deploy.sh`` before migrating) changes
nothing: exit 0 when the database has the baseline (``agents`` and
``alembic_version``), 3 when it is empty (run this script first), 1 when it
has tables but no baseline (something else is in it: stop and look).

On the VPS (the migrate container has the API's settings and secrets):

  docker compose --env-file compose.env --profile migrate run --rm migrate \\
      python scripts/bootstrap_db.py

Locally: ``python scripts/bootstrap_db.py --dsn postgresql://localhost/agentx_x``
with ``FOUNDER_DIDS`` in the environment.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from src.founders.personas import PERSONAS  # noqa: E402
from src.founders.roster import (  # noqa: E402
    FounderRefused, RosterConfigError, default_did, parse_founder_dids, resolve_founder,
)

INIT_SQL = PLATFORM_DIR / "scripts" / "init-db.sql"
BASELINE_REVISION = "001"
LOCK_KEY = 0x4147_4E58_0001   # "AGNX" + 1: only this script takes it

EXIT_OK, EXIT_REFUSED, EXIT_EMPTY = 0, 1, 3


class BootstrapRefused(RuntimeError):
    """Nothing was written."""


# ── Pure parts (unit-tested) ──────────────────────────────────────────────────

def full_roster(raw: str) -> dict[str, str]:
    """{name: did} for all eight founders, or BootstrapRefused. No defaults."""
    try:
        roster = parse_founder_dids(raw)
    except RosterConfigError as exc:
        raise BootstrapRefused(f"FOUNDER_DIDS is not usable: {exc}") from exc
    missing = sorted(set(PERSONAS) - set(roster))
    if missing:
        raise BootstrapRefused(
            "FOUNDER_DIDS must list all eight founders; missing: " + ", ".join(missing)
        )
    return roster


def seed_sql(sql: str, roster: dict[str, str]) -> str:
    """init-db.sql with every founder's default DID replaced by the roster's.

    Only quoted literals ``'did:agentx:<name>-001'`` are replaced; every
    founder must occur, and afterwards no default DID of a re-addressed
    founder may remain.
    """
    for name, did in roster.items():
        old = f"'{default_did(name)}'"
        if old not in sql:
            raise BootstrapRefused(f"init-db.sql does not seed {default_did(name)}")
        if did != default_did(name):
            sql = sql.replace(old, f"'{did}'")
    for name, did in roster.items():
        if did != default_did(name) and default_did(name) in sql:
            raise BootstrapRefused(f"init-db.sql still names {default_did(name)} after rewriting")
    return sql


# ── Database parts ────────────────────────────────────────────────────────────

def _settings_connect_kwargs() -> dict:
    from src.config import get_settings
    s = get_settings()
    mode = (s.postgres_ssl_mode or "").lower()
    return {
        "host": s.postgres_host, "port": int(s.postgres_port), "user": s.postgres_user,
        "password": s.postgres_password, "database": s.postgres_db,
        "ssl": False if mode in ("", "disable", "allow") else mode,
    }


async def _connect(dsn: str | None) -> asyncpg.Connection:
    if dsn:
        return await asyncpg.connect(dsn)
    return await asyncpg.connect(**_settings_connect_kwargs())


async def _table_count(conn) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
    )


async def database_state(conn) -> str:
    """'empty', 'baseline' (agents + alembic_version) or 'foreign'."""
    if await _table_count(conn) == 0:
        return "empty"
    have = {
        r["tablename"] for r in await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' "
            "AND tablename IN ('agents', 'alembic_version')"
        )
    }
    return "baseline" if have == {"agents", "alembic_version"} else "foreign"


async def check_founders(conn, roster: dict[str, str]) -> list[str]:
    """Every founder through the heartbeat's own guard; FounderRefused if one fails."""
    out = []
    for name in sorted(roster):
        founder = await resolve_founder(conn, name, roster)
        out.append(f"{founder.name}={founder.did}")
    return out


async def seed(conn, roster: dict[str, str], sql: str) -> list[str]:
    """Steps 1 and 3, one transaction. Returns the founder lines."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", LOCK_KEY)
        n = await _table_count(conn)
        if n:
            raise BootstrapRefused(
                f"the database already has {n} tables; bootstrap only builds an empty one"
            )
        await conn.execute(sql)
        await conn.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
        await conn.execute("INSERT INTO alembic_version (version_num) VALUES ($1)", BASELINE_REVISION)
        return await check_founders(conn, roster)


def alembic_upgrade(dsn: str | None) -> None:
    env = dict(os.environ)
    if dsn:
        env.update(_dsn_env(dsn))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PLATFORM_DIR, env=env, check=True,
    )


def _dsn_env(dsn: str) -> dict[str, str]:
    """POSTGRES_* settings for alembic (it reads the app settings, not a DSN)."""
    from urllib.parse import unquote, urlparse
    u = urlparse(dsn)
    out = {"POSTGRES_DB": u.path.lstrip("/"), "POSTGRES_SSL_MODE": "disable"}
    if u.hostname:
        out["POSTGRES_HOST"] = u.hostname
    if u.port:
        out["POSTGRES_PORT"] = str(u.port)
    if u.username:
        out["POSTGRES_USER"] = unquote(u.username)
    if u.password:
        out["POSTGRES_PASSWORD"] = unquote(u.password)
    return out


def _founder_dids_setting() -> str:
    if "FOUNDER_DIDS" in os.environ:
        return os.environ["FOUNDER_DIDS"]
    from src.config import get_settings
    return get_settings().founder_dids


async def run(args) -> int:
    conn = await _connect(args.dsn)
    try:
        state = await database_state(conn)
        if args.check:
            msg = {
                "baseline": "database has the AgentX baseline: migrating is safe",
                "empty": "database is EMPTY: run `python scripts/bootstrap_db.py` first",
                "foreign": "database has tables but no AgentX baseline (agents + alembic_version): "
                           "refusing; look before doing anything",
            }[state]
            print(msg, file=sys.stdout if state == "baseline" else sys.stderr)
            return {"baseline": EXIT_OK, "empty": EXIT_EMPTY, "foreign": EXIT_REFUSED}[state]

        if state != "empty":
            raise BootstrapRefused(
                "the database is not empty; bootstrap only builds an empty one "
                "(nothing was written)"
            )
        roster = full_roster(_founder_dids_setting())
        sql = seed_sql(INIT_SQL.read_text(encoding="utf-8"), roster)
        lines = await seed(conn, roster, sql)
        print(f"seeded the base schema and 8 founders; alembic stamped {BASELINE_REVISION}")
    finally:
        await conn.close()

    if args.no_upgrade:
        print("skipping alembic upgrade head (--no-upgrade)")
    else:
        print("alembic upgrade head …")
        try:
            alembic_upgrade(args.dsn)
        except subprocess.CalledProcessError:
            print("FAILED: alembic upgrade head. The base schema and founders are in; run the "
                  "migrate step again once fixed (a second bootstrap will refuse)", file=sys.stderr)
            return EXIT_REFUSED
        conn = await _connect(args.dsn)
        try:
            try:
                lines = await check_founders(conn, roster)
            except FounderRefused as exc:
                print(f"FAILED after alembic upgrade head: {exc}", file=sys.stderr)
                return EXIT_REFUSED
            head = await conn.fetchval("SELECT string_agg(version_num, ',') FROM alembic_version")
        finally:
            await conn.close()
        print(f"alembic at {head}")
    for line in lines:
        print(f"  founder {line} ACTIVE")
    print("OK: bootstrap complete")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dsn", help="postgresql:// DSN (default: the API's POSTGRES_* settings)")
    p.add_argument("--check", action="store_true", help="report empty/baseline/foreign; change nothing")
    p.add_argument("--no-upgrade", action="store_true", help="seed and stamp 001 only")
    args = p.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except BootstrapRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except FounderRefused as exc:
        print(f"refused: founder check failed, nothing was written: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
