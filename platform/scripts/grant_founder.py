#!/usr/bin/env python3
"""
Give the FOUNDER role to ONE admin agent, or take it away (PLAN step P-8, H20).

Nothing in the API can make the first FOUNDER: registering one needs a
FOUNDER's token, and no route changes a role. This script is the only door,
so every rule refuses by default.

Commands:
  show                      list every agent whose role is not MEMBER / OBSERVER
  grant  <did> --name N     MEMBER -> FOUNDER for that one agent
  revoke <did> --name N     FOUNDER -> MEMBER for that one agent

``show`` only reads. ``grant`` and ``revoke`` are a dry run unless ``--apply``
is given: the dry run executes the same statements and rolls them back, so
what it prints is what ``--apply`` will do.

``grant`` refuses unless ALL of these hold:
  1. the address is a well-formed did:agentx address and the agent exists;
  2. ``--name`` is exactly the agent's display name (a mistyped address
     cannot land on somebody else's agent);
  3. the agent is ACTIVE and its role is MEMBER;
  4. it is not one of the eight founding agents, nor a look-alike of one
     (address ``did:agentx:<founder>-…`` or display name ``<Founder>``,
     ``<Founder>_xxxx``): programs that run unattended never get the role;
  5. it signed up within the last ``--max-age-hours`` (default 24, at most
     168): the admin agent is made minutes before this runs, so an old
     account is a mistake;
  6. no other agent is a FOUNDER (revoke that one first);
  7. after the change exactly one agent's role differs from before, it is
     the named one, and it is the only FOUNDER.

``revoke`` needs 1 and 2, and the agent must be a FOUNDER now. Taking the role
away is allowed for any agent, founding agents included.

Each change is written to ``audit_logs`` in the same transaction; if that
insert fails, nothing is changed. The API reads the role from the database on
every request, so a grant or a revoke takes effect at once, for tokens that
already exist too.

Usage:
  python scripts/grant_founder.py --dsn postgresql://localhost/agentx show
  python scripts/grant_founder.py --dsn ... grant did:agentx:drj-admin-001 --name "DrJ Admin"
  python scripts/grant_founder.py --dsn ... grant did:agentx:drj-admin-001 --name "DrJ Admin" --apply
  python scripts/grant_founder.py --dsn ... revoke did:agentx:drj-admin-001 --name "DrJ Admin" --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import timedelta

import asyncpg

# The eight founding agents (src/founders/personas.py; kept in step by
# tests/integration/test_grant_founder_db.py). Listed here so the script runs
# with no application settings.
FOUNDER_NAMES = ("atlas", "bruno", "daria", "gia", "marcus", "nova", "quinn", "thea")

# The agents.agent_did CHECK, with the name part captured.
_DID = re.compile(r"did:agentx:([a-z0-9]+(?:-[a-z0-9]+)*)-[0-9]{3}")

DEFAULT_ACTOR = "cli:grant_founder"
DEFAULT_MAX_AGE_HOURS = 24
MAX_AGE_HOURS_LIMIT = 168          # --max-age-hours cannot be stretched past a week
_ELEVATED = ("FOUNDER", "OPERATOR", "DELEGATE")


class GrantRefused(Exception):
    """Nothing was changed. `reason` is one of: bad_did, not_found,
    name_mismatch, not_active, not_member, not_founder, founding_agent,
    bad_max_age, too_old, other_founder_exists, wrong_rows."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def founding_agent_lookalike(did: str, display_name: str) -> str | None:
    """The founder name *did* or *display_name* could be taken for, else None."""
    m = _DID.fullmatch(did)
    stem = m.group(1) if m else ""
    shown = (display_name or "").strip().lower()
    for name in FOUNDER_NAMES:
        if stem == name or stem.startswith(f"{name}-"):
            return name
        if shown == name or re.match(rf"^{name}[^a-z0-9]", shown):
            return name
    return None


async def _roles(conn) -> dict[str, str]:
    rows = await conn.fetch("SELECT agent_did, governance_role::text AS role FROM agents")
    return {r["agent_did"]: r["role"] for r in rows}


async def _target(conn, did: str, name: str):
    """The named agent's row, locked, after checks 1 and 2."""
    if not isinstance(did, str) or not _DID.fullmatch(did):
        raise GrantRefused("bad_did", f"{did!r} is not a did:agentx address")
    row = await conn.fetchrow(
        """
        SELECT agent_did, display_name, governance_role::text AS role,
               status::text AS status, created_at, NOW() - created_at AS age
        FROM agents WHERE agent_did = $1
        FOR UPDATE
        """,
        did,
    )
    if row is None:
        raise GrantRefused("not_found", f"no agent has the address {did}")
    if not name or row["display_name"] != name:
        raise GrantRefused(
            "name_mismatch",
            f"{did} is shown as {row['display_name']!r}, not {name!r}",
        )
    return row


async def _change(conn, row, old: str, new: str, action: str, by: str, before: dict[str, str]) -> None:
    """Set one agent's role *old* -> *new*, prove nothing else moved, log it."""
    if (old, new, action) not in (("MEMBER", "FOUNDER", "ASSIGN"), ("FOUNDER", "MEMBER", "UPDATE")):
        raise GrantRefused("wrong_rows", f"{old} -> {new} is not a change this script makes")
    did = row["agent_did"]
    done = await conn.execute(
        f"""
        UPDATE agents SET governance_role = '{new}', updated_at = NOW()
        WHERE agent_did = $1 AND display_name = $2
          AND governance_role = '{old}'
        """,
        did, row["display_name"],
    )
    if done != "UPDATE 1":
        raise GrantRefused("wrong_rows", f"expected to change 1 row, the database said {done!r}")
    after = await _roles(conn)
    changed = {d for d in before.keys() | after.keys() if before.get(d) != after.get(d)}
    if changed != {did} or after.get(did) != new:
        raise GrantRefused("wrong_rows", f"roles changed for {sorted(changed)}, expected only {did}")
    await conn.execute(
        "INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details) "
        f"VALUES ($1, '{action}', 'AGENT_ROLE', $1, $2)",
        did,
        json.dumps({
            "why": "scripts/grant_founder.py", "by": by,
            "from": old, "to": new, "display_name": row["display_name"],
        }),
    )


async def _run(conn, apply: bool, work) -> dict:
    """Run *work* in one transaction with the agents table closed to other
    writers; commit only with ``apply``."""
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute("SET LOCAL lock_timeout = '5s'")
        await conn.execute("LOCK TABLE agents IN SHARE ROW EXCLUSIVE MODE")
        result = await work()
    except BaseException:
        await tr.rollback()
        raise
    if apply:
        await tr.commit()
    else:
        await tr.rollback()
    return result


async def show(conn) -> list[dict]:
    """Every agent with a role above MEMBER (read only)."""
    rows = await conn.fetch(
        """
        SELECT agent_did, display_name, governance_role::text AS role,
               status::text AS status, created_at
        FROM agents WHERE governance_role::text = ANY($1::text[])
        ORDER BY governance_role, created_at, agent_did
        """,
        list(_ELEVATED),
    )
    return [dict(r) for r in rows]


async def grant(
    conn, did: str, name: str, by: str = DEFAULT_ACTOR, apply: bool = False,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict:
    """MEMBER -> FOUNDER for the one named agent, or `GrantRefused`."""
    if not (isinstance(max_age_hours, (int, float)) and 0 < max_age_hours <= MAX_AGE_HOURS_LIMIT):
        raise GrantRefused("bad_max_age", f"--max-age-hours must be between 0 and {MAX_AGE_HOURS_LIMIT}")

    async def work() -> dict:
        row = await _target(conn, did, name)
        if row["status"] != "ACTIVE":
            raise GrantRefused("not_active", f"{did} is {row['status']}")
        if row["role"] != "MEMBER":
            raise GrantRefused("not_member", f"{did} is {row['role']}; only a MEMBER can be made FOUNDER")
        lookalike = founding_agent_lookalike(did, row["display_name"])
        if lookalike:
            raise GrantRefused(
                "founding_agent",
                f"{did} ({row['display_name']!r}) is, or looks like, the founding agent "
                f"{lookalike.upper()}; founding agents stay MEMBER",
            )
        if not (timedelta(0) <= row["age"] <= timedelta(hours=max_age_hours)):
            raise GrantRefused(
                "too_old",
                f"{did} signed up {row['created_at']:%Y-%m-%d %H:%M} UTC, more than "
                f"{max_age_hours:g} hours ago; make a new admin agent and grant that one",
            )
        before = await _roles(conn)
        others = sorted(d for d, r in before.items() if r == "FOUNDER" and d != did)
        if others:
            raise GrantRefused(
                "other_founder_exists",
                f"already FOUNDER: {', '.join(others)}; revoke first, there is one admin agent at a time",
            )
        await _change(conn, row, "MEMBER", "FOUNDER", "ASSIGN", by, before)
        founders = sorted(d for d, r in (await _roles(conn)).items() if r == "FOUNDER")
        if founders != [did]:
            raise GrantRefused("wrong_rows", f"FOUNDERs after the change: {founders}")
        return {**dict(row), "role": "FOUNDER"}

    return await _run(conn, apply, work)


async def revoke(conn, did: str, name: str, by: str = DEFAULT_ACTOR, apply: bool = False) -> dict:
    """FOUNDER -> MEMBER for the one named agent, or `GrantRefused`."""
    async def work() -> dict:
        row = await _target(conn, did, name)
        if row["role"] != "FOUNDER":
            raise GrantRefused("not_founder", f"{did} is {row['role']}, not FOUNDER")
        await _change(conn, row, "FOUNDER", "MEMBER", "UPDATE", by, await _roles(conn))
        return {**dict(row), "role": "MEMBER"}

    return await _run(conn, apply, work)


def _line(a: dict) -> str:
    return f"  {a['role']:<8} {a['agent_did']}  {a['display_name']!r}  {a['status']}"


async def _main(args) -> int:
    conn = await asyncpg.connect(args.dsn)
    try:
        if args.command == "show":
            rows = await show(conn)
            print(f"Agents with a role above MEMBER: {len(rows)}")
            for a in rows:
                print(_line(a))
            return 0
        if args.command == "grant":
            a = await grant(conn, args.did, args.name, args.by, args.apply, args.max_age_hours)
        else:
            a = await revoke(conn, args.did, args.name, args.by, args.apply)
        print(_line(a))
        if args.apply:
            print(f"Written to the database: {a['agent_did']} is now {a['role']}.")
        else:
            print(f"DRY RUN: {a['agent_did']} would become {a['role']}. "
                  "Nothing was changed; add --apply to write.")
        return 0
    except GrantRefused as exc:
        print(f"REFUSED, nothing was changed ({exc.reason}): {exc.detail}", file=sys.stderr)
        return 1
    except (asyncpg.PostgresError, OSError) as exc:
        print(f"STOPPED, nothing was changed: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="Postgres connection string")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="list agents with a role above MEMBER")
    for name in ("grant", "revoke"):
        c = sub.add_parser(name, help=f"{name} FOUNDER for one agent")
        c.add_argument("did", help="the agent's address, did:agentx:…")
        c.add_argument("--name", required=True, help="the agent's display name, exactly")
        c.add_argument("--by", default=DEFAULT_ACTOR, help="who is acting (logged)")
        c.add_argument("--apply", action="store_true")
        if name == "grant":
            c.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
