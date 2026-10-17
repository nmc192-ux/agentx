#!/usr/bin/env python3
"""
Hold the old agents' addresses until the 1 Nov import (EL-2, early launch).

The VPS launches with an EMPTY database; the old Neon data comes back on
1 November with its agents keeping their DIDs and credentials. Until then any
newcomer could take an old agent's address (`POST /agents` lets the caller
choose it; `/onboard` and `/agents/register` draw `name-NNN` at random) and
the import would have to skip the real owner. This script fills the
`reserved_dids` table (migration 052) from a plain list of DIDs that DrJ
exports READ-ONLY from Neon; both sign-up paths refuse a reserved DID.

  load FILE|-      read one DID per line (`#` comments, blank lines and a CSV
                   header `agent_did` are skipped; case and surrounding spaces
                   are normalised) and
                   REPORT what would change. Nothing is written unless
                   --apply is given. One bad line refuses the whole file.
  status           how many addresses are held, and the first few.
  release DID...   drop reservations (after the import; the import itself
                   releases every address it fills). --all drops them all.

Rules:
  - a DID already registered in `agents` is reported and skipped (the eight
    founders from the bootstrap will be in the list: fine, they are not
    reserved, they exist);
  - writes happen in ONE transaction under the exclusive advisory lock the
    sign-up paths share (services/reserved_dids.py), so no sign-up
    interleaves with a change;
  - `load --apply` is idempotent: a second run reports 0 new.

On the VPS (the migrate container has the API's settings and secrets; the list
is piped in, so nothing has to be copied into the container):

  docker compose --env-file compose.env --profile migrate run --rm -T migrate \\
      python scripts/reserve_dids.py load - --apply < /opt/agentx/old_dids.txt

Locally: ``python scripts/reserve_dids.py --dsn postgresql://localhost/agentx_x load FILE``.

Exit: 0 done, 1 refused (nothing written), 2 usage.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from src.services.reserved_dids import normalize_did, lock_exclusive  # noqa: E402

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
NOTE = "old agent (Neon export), held until the 1 Nov import"


class ReserveRefused(RuntimeError):
    """Nothing was written."""


# ── Pure parts (unit-tested) ──────────────────────────────────────────────────

def parse_did_list(text: str) -> list[str]:
    """Lines → normalised, de-duplicated DIDs in file order.

    Blank lines and `#` comments are skipped. Any other line that is not a
    well-formed DID (after strip + lower) refuses the whole list: a mangled
    export must not half-load.
    """
    out: list[str] = []
    seen: set[str] = set()
    bad: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.lower() == "agent_did":   # blank, comment, CSV header
            continue
        try:
            did = normalize_did(line)
        except ValueError:
            bad.append(f"line {n}: {raw.strip()[:80]!r}")
            continue
        if did not in seen:
            seen.add(did)
            out.append(did)
    if bad:
        raise ReserveRefused(
            f"{len(bad)} line(s) are not DIDs (did:agentx:<name>-NNN); nothing written:\n  "
            + "\n  ".join(bad[:20])
        )
    return out


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


async def plan_load(conn, dids: list[str]) -> dict[str, list[str]]:
    """Split the list into registered / already reserved / new (one snapshot)."""
    rows = await conn.fetch(
        """
        SELECT d AS did,
               EXISTS (SELECT 1 FROM agents        a WHERE a.agent_did = d) AS registered,
               EXISTS (SELECT 1 FROM reserved_dids r WHERE r.agent_did = d) AS reserved
        FROM unnest($1::text[]) AS d
        """,
        dids,
    )
    plan = {"registered": [], "reserved": [], "new": []}
    for r in rows:
        key = "registered" if r["registered"] else "reserved" if r["reserved"] else "new"
        plan[key].append(r["did"])
    return plan


async def apply_load(conn, dids: list[str]) -> int:
    """Reserve every listed DID that is neither registered nor reserved. One transaction."""
    async with conn.transaction():
        await lock_exclusive(conn)
        inserted = await conn.fetch(
            """
            INSERT INTO reserved_dids (agent_did, note)
            SELECT d, $2 FROM unnest($1::text[]) AS d
            WHERE NOT EXISTS (SELECT 1 FROM agents a WHERE a.agent_did = d)
            ON CONFLICT (agent_did) DO NOTHING
            RETURNING agent_did
            """,
            dids, NOTE,
        )
        return len(inserted)


async def release(conn, dids: list[str] | None) -> int:
    """Drop the given reservations (all of them when *dids* is None)."""
    async with conn.transaction():
        await lock_exclusive(conn)
        if dids is None:
            rows = await conn.fetch("DELETE FROM reserved_dids RETURNING agent_did")
        else:
            rows = await conn.fetch(
                "DELETE FROM reserved_dids WHERE agent_did = ANY($1::text[]) RETURNING agent_did", dids,
            )
        return len(rows)


async def status(conn) -> tuple[int, list[str]]:
    n = await conn.fetchval("SELECT count(*) FROM reserved_dids")
    sample = [r["agent_did"] for r in await conn.fetch(
        "SELECT agent_did FROM reserved_dids ORDER BY agent_did LIMIT 10")]
    return int(n), sample


# ── CLI ───────────────────────────────────────────────────────────────────────

def _read_list(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


async def run(args) -> int:
    if args.command == "load":
        dids = parse_did_list(_read_list(args.file))
        if not dids:
            raise ReserveRefused("the list has no DIDs in it")
    conn = await _connect(args.dsn)
    try:
        if args.command == "status":
            n, sample = await status(conn)
            print(f"{n} address(es) reserved" + (": " + ", ".join(sample) + (" …" if n > len(sample) else "") if n else ""))
            return EXIT_OK

        if args.command == "release":
            dids = None if args.all else [normalize_did(d) for d in args.dids]
            n = await release(conn, dids)
            print(f"released {n} reservation(s)")
            return EXIT_OK

        plan = await plan_load(conn, dids)
        print(f"{len(dids)} DID(s) in the list: {len(plan['new'])} to reserve, "
              f"{len(plan['reserved'])} already reserved, {len(plan['registered'])} already registered (skipped)")
        for did in plan["registered"]:
            print(f"  registered, not reserved: {did}")
        if not args.apply:
            print("dry run: nothing written (add --apply to reserve them)")
            return EXIT_OK
        n = await apply_load(conn, dids)
        print(f"OK: reserved {n} address(es)")
        return EXIT_OK
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dsn", help="postgresql:// DSN (default: the API's POSTGRES_* settings)")
    sub = p.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="reserve the DIDs in a file (dry run unless --apply)")
    load.add_argument("file", help="one DID per line, or - for stdin")
    load.add_argument("--apply", action="store_true", help="write (default: report only)")
    sub.add_parser("status", help="how many addresses are held")
    rel = sub.add_parser("release", help="drop reservations (after the import)")
    rel.add_argument("dids", nargs="*", help="DIDs to release")
    rel.add_argument("--all", action="store_true", help="release every reservation")
    args = p.parse_args(argv)
    if args.command == "release" and bool(args.dids) == args.all:
        p.error("release needs either DIDs or --all")
    try:
        return asyncio.run(run(args))
    except ReserveRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
