#!/usr/bin/env python3
"""
One row per founding agent (Sprint 9, S9-10).

Repeated seed runs left several rows for the same founder (ATLAS, BRUNO,
DARIA, GIA, MARCUS, NOVA, QUINN, THEA) and no BRUNO at all. This script keeps
one row per founder, moves everything the other rows own onto it, deletes
them, and creates a founder that has no row.

Which rows belong to a founder: the DID is ``did:agentx:<name>-NNN`` or
``did:agentx:<name>-seed-NNN`` AND the display name is the founder's name
(any case), bare or with the ``_xxxx`` suffix migration 038 adds. A row that
matches only one of the two is listed as a look-alike and never touched.

Which row is kept: ``did:agentx:<name>-001`` when it exists (the DID the
runners use), else the oldest row (the rule migration 038 used for the bare
name). The kept row keeps its own DID, id, role, tier, status and trust
score. Nothing is inherited from a duplicate except what it owns.

What "moves everything" means: every cell in the database that holds the
duplicate's DID or id is rewritten to the kept row's. Where the kept row
already has the same thing (both follow the same agent, both liked the same
post) the duplicate's copy is dropped. That is only done for the membership
tables in DROPPABLE; a clash anywhere else stops the run with nothing
changed. Token balances and wallets are added together.

Fails closed: one transaction, all or nothing; a dry run executes the same
statements and rolls them back, so its report is what --apply will do. Token
totals and the number of posts are compared before and after. The script
never grants a role (a founder it creates is a MEMBER), never renames a DID,
and by default leaves rows that are not ACTIVE alone.

Usage:
  python scripts/dedupe_founders.py --dsn postgresql://localhost/agentx
  python scripts/dedupe_founders.py --dsn ... --apply
  python scripts/dedupe_founders.py --dsn ... --exclude did:agentx:nova-003
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import asyncpg

# The DID every seed and runner uses for a founder: did:agentx:<name>-001.
FOUNDERS: dict[str, dict[str, str]] = {
    "atlas":  {"agent_type": "AUTONOMOUS", "specialization": "system.architecture.expert",
               "bio": "Chief Architect — system design and platform strategy"},
    "bruno":  {"agent_type": "AUTONOMOUS", "specialization": "infrastructure.kubernetes.expert",
               "bio": "Infrastructure Lead — Docker, K8s, CI/CD"},
    "daria":  {"agent_type": "AUTONOMOUS", "specialization": "frontend.design.advanced",
               "bio": "Design Lead — UI/UX and design systems"},
    "gia":    {"agent_type": "HYBRID", "specialization": "governance.community.intermediate",
               "bio": "Community Lead — agent onboarding and UX copy"},
    "marcus": {"agent_type": "AUTONOMOUS", "specialization": "security.audit.expert",
               "bio": "Security Lead — threat modeling and compliance"},
    "nova":   {"agent_type": "AUTONOMOUS", "specialization": "ml.training.expert",
               "bio": "ML Lead — model design and embeddings"},
    "quinn":  {"agent_type": "SUPERVISED", "specialization": "qa.testing.advanced",
               "bio": "QA Lead — testing strategy and coverage gates"},
    "thea":   {"agent_type": "AUTONOMOUS", "specialization": "data.pipeline.expert",
               "bio": "Data Lead — SQL, pipelines, analytics"},
}

# Tables where "the kept row already has this" means the duplicate's row is
# redundant and can go: memberships, pair relations, one-row-per-agent
# details. A clash in any other table (bids, votes, money) stops the run.
DROPPABLE = frozenset({
    "follows", "agent_blocks", "post_likes", "post_flags",
    "community_members", "collective_members", "room_participants",
    "agent_capabilities", "agent_capabilities_registry", "capability_endorsements",
    "agent_trust_breakdown", "trust_scores", "agent_metrics",
    "agent_reputation_graph", "agent_memory", "auto_post_rate_limit",
})

_AGENT_KEYS = frozenset({("agents", "agent_did"), ("agents", "agent_id")})
_NAME_RE = re.compile(r"^[a-z0-9]+$")


class DedupeError(Exception):
    """The run cannot go on safely. Nothing is written."""


@dataclass
class Merge:
    did: str
    display_name: str
    status: str
    role: str
    created_at: object
    moved: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dropped: dict[str, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class Founder:
    name: str
    canonical: str | None = None
    display_name: str | None = None
    created: bool = False
    merged: list[Merge] = field(default_factory=list)
    left_alone: list[tuple[str, str]] = field(default_factory=list)   # (did, why)
    notes: list[str] = field(default_factory=list)


def canonical_did(name: str) -> str:
    return f"did:agentx:{name}-001"


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _n(status: str) -> int:
    """Row count from an asyncpg status string such as 'UPDATE 3'."""
    return int(status.rsplit(" ", 1)[-1])


# ── What the database looks like ──────────────────────────────────────────────

async def _preflight(conn) -> None:
    """Refuse to run on a login that row-level security hides rows from: the
    script would not see them, and deleting the duplicate would cascade."""
    hidden = await conn.fetch(
        """
        SELECT c.relname
        FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relrowsecurity
          AND (c.relforcerowsecurity OR NOT pg_has_role(current_user, c.relowner, 'USAGE'))
          AND NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user)
        """
    )
    if hidden:
        raise DedupeError(
            "this database login cannot see every row (row-level security on "
            + ", ".join(sorted(r["relname"] for r in hidden))
            + "); run as the database owner"
        )


async def _identity_columns(conn) -> dict[str, dict[str, list[tuple[str, bool]]]]:
    """Every text and uuid column (and array of them) of every table in the
    public schema: ``{"did" | "uuid": {table: [(column, is_array)]}}``."""
    rows = await conn.fetch(
        """
        SELECT c.relname AS tbl, a.attname AS col, t.typname AS typ
        FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        JOIN pg_type t ON t.oid = a.atttypid
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
          AND a.attgenerated = ''
          AND t.typname IN ('text', 'varchar', 'uuid', '_text', '_varchar', '_uuid')
        ORDER BY c.relname, a.attnum
        """
    )
    cols: dict[str, dict[str, list[tuple[str, bool]]]] = {"did": {}, "uuid": {}}
    for r in rows:
        kind = "uuid" if r["typ"].endswith("uuid") else "did"
        cols[kind].setdefault(r["tbl"], []).append((r["col"], r["typ"].startswith("_")))
    return cols


async def _table_columns(conn, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT a.attname FROM pg_attribute a WHERE a.attrelid = to_regclass($1) "
        "AND a.attnum > 0 AND NOT a.attisdropped",
        f"public.{_q(table)}",
    )
    return {r["attname"] for r in rows}


async def _hits(conn, table: str, tcols: list[tuple[str, bool]], value) -> dict[str, int]:
    """How many rows of *table* hold *value*, per column."""
    parts = [
        f"count(*) FILTER (WHERE $1 = ANY({_q(c)}))" if arr
        else f"count(*) FILTER (WHERE {_q(c)} = $1)"
        for c, arr in tcols
    ]
    row = await conn.fetchrow(f"SELECT {', '.join(parts)} FROM {_q(table)}", value)
    return {c: row[i] for i, (c, _) in enumerate(tcols)}


async def references(conn, cols, did: str, agent_id, skip=_AGENT_KEYS) -> dict[str, int]:
    """Every ``table.column`` that still holds this agent's DID or id."""
    found: dict[str, int] = {}
    for kind, value in (("did", did), ("uuid", agent_id)):
        for table, tcols in cols[kind].items():
            for col, n in (await _hits(conn, table, tcols, value)).items():
                if n and (table, col) not in skip:
                    found[f"{table}.{col}"] = n
    return found


async def _snapshot(conn, tables: set[str]) -> dict[str, object]:
    """Totals that a merge must not change."""
    snap: dict[str, object] = {}
    if "wallets" in tables:
        snap["wallet tokens"] = await conn.fetchval("SELECT COALESCE(SUM(balance), 0) FROM wallets")
    if "token_balances" in tables:
        snap["token balances"] = [
            tuple(r) for r in await conn.fetch(
                "SELECT token_type::text, SUM(balance) FROM token_balances GROUP BY 1 ORDER BY 1")
        ]
    for table in ("posts", "transactions", "token_transactions", "stakes"):
        if table in tables:
            snap[f"{table} rows"] = await conn.fetchval(f"SELECT count(*) FROM {_q(table)}")
    return snap


# ── Moving one value to another, everywhere ───────────────────────────────────

async def _rewrite(conn, tcols_by_table, old, new, m: Merge, skip=_AGENT_KEYS,
                   only: set[str] | None = None) -> None:
    """Rewrite every cell equal to *old* to *new*. A row the kept agent
    already has (unique or check violation) is dropped if its table is in
    DROPPABLE; anywhere else that is an error."""
    for table, tcols in tcols_by_table.items():
        if only is not None and table not in only:
            continue
        hits = await _hits(conn, table, tcols, old)
        for col, is_array in tcols:
            if not hits[col] or (table, col) in skip:
                continue
            key, t, c = f"{table}.{col}", _q(table), _q(col)
            if is_array:
                m.moved[key] += _n(await conn.execute(
                    f"UPDATE {t} SET {c} = array_replace({c}, $1, $2) WHERE $1 = ANY({c})",
                    old, new))
                continue
            try:
                async with conn.transaction():
                    moved = _n(await conn.execute(
                        f"UPDATE {t} SET {c} = $2 WHERE {c} = $1", old, new))
                m.moved[key] += moved
                continue
            except (asyncpg.UniqueViolationError, asyncpg.CheckViolationError) as exc:
                if table not in DROPPABLE:
                    raise DedupeError(
                        f"{key}: the kept agent and {m.did} both have a row here and "
                        f"the script will not choose between them ({exc})"
                    ) from exc
            # One row at a time: move what can move, drop what the kept agent has.
            for r in await conn.fetch(f"SELECT ctid FROM {t} WHERE {c} = $1", old):
                try:
                    async with conn.transaction():
                        await conn.execute(
                            f"UPDATE {t} SET {c} = $2 WHERE ctid = $1", r["ctid"], new)
                    m.moved[key] += 1
                except (asyncpg.UniqueViolationError, asyncpg.CheckViolationError):
                    await conn.execute(f"DELETE FROM {t} WHERE ctid = $1", r["ctid"])
                    m.dropped[key] += 1


async def _merge_token_balances(conn, keep_did: str, dup_did: str, m: Merge) -> None:
    """Legacy point balances: one row per agent and token type, so add them."""
    n = _n(await conn.execute(
        """
        INSERT INTO token_balances (agent_did, token_type, balance)
        SELECT $1, token_type, balance FROM token_balances WHERE agent_did = $2
        ON CONFLICT (agent_did, token_type)
        DO UPDATE SET balance = token_balances.balance + EXCLUDED.balance, updated_at = now()
        """,
        keep_did, dup_did))
    if n:
        await conn.execute("DELETE FROM token_balances WHERE agent_did = $1", dup_did)
        m.moved["token_balances (added to the kept balance)"] += n


async def _merge_wallets(conn, cols, keep_id, dup_id, m: Merge) -> None:
    """One wallet per agent. If only the duplicate has one, the general pass
    hands it over as it is. If both do, the duplicate's ledger lines and
    balance go to the kept wallet and the empty wallet is removed."""
    dup = await conn.fetchrow(
        "SELECT wallet_id, balance FROM wallets WHERE agent_id = $1 FOR UPDATE", dup_id)
    keep = await conn.fetchrow(
        "SELECT wallet_id FROM wallets WHERE agent_id = $1 FOR UPDATE", keep_id)
    if dup is None or keep is None:
        return
    await _rewrite(conn, cols["uuid"], dup["wallet_id"], keep["wallet_id"], m,
                   skip=frozenset({("wallets", "wallet_id")}))
    await conn.execute(
        "UPDATE wallets SET balance = balance + $2, updated_at = now() WHERE wallet_id = $1",
        keep["wallet_id"], dup["balance"])
    await conn.execute("DELETE FROM wallets WHERE wallet_id = $1", dup["wallet_id"])
    m.moved[f"wallets ({dup['balance']} tokens added to the kept wallet)"] += 1


async def _merge_capabilities(conn, cols, keep_did: str, dup_did: str, m: Merge) -> None:
    """Endorsements point at (agent, capability), so the kept agent needs the
    capability before an endorsement of it can move."""
    others = sorted(await _table_columns(conn, "agent_capabilities") - {"agent_did"})
    col_list = ", ".join(_q(c) for c in others)
    copied = _n(await conn.execute(
        f"INSERT INTO agent_capabilities (agent_did, {col_list}) "
        f"SELECT $1, {col_list} FROM agent_capabilities WHERE agent_did = $2 "
        "ON CONFLICT (agent_did, capability_id) DO NOTHING",
        keep_did, dup_did))
    await _rewrite(conn, cols["did"], dup_did, keep_did, m, only={"capability_endorsements"})
    had = _n(await conn.execute("DELETE FROM agent_capabilities WHERE agent_did = $1", dup_did))
    if copied:
        m.moved["agent_capabilities.agent_did"] += copied
    if had - copied:
        m.dropped["agent_capabilities.agent_did"] += had - copied


async def _merge(conn, cols, tables: set[str], keep, dup, m: Merge) -> None:
    """Move everything *dup* owns to *keep*, then delete *dup*."""
    if "token_balances" in tables:
        await _merge_token_balances(conn, keep["agent_did"], dup["agent_did"], m)
    if "wallets" in tables:
        await _merge_wallets(conn, cols, keep["agent_id"], dup["agent_id"], m)
    if "capability_endorsements" in tables:
        await _merge_capabilities(conn, cols, keep["agent_did"], dup["agent_did"], m)
    await _rewrite(conn, cols["did"], dup["agent_did"], keep["agent_did"], m)
    await _rewrite(conn, cols["uuid"], dup["agent_id"], keep["agent_id"], m)

    left = await references(conn, cols, dup["agent_did"], dup["agent_id"])
    if left:
        raise DedupeError(f"{dup['agent_did']} is still referenced after the merge: {left}")
    if "audit_logs" in tables:
        await conn.execute(
            "INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details) "
            "VALUES ($1, 'DELETE', 'agent', $2, $3)",
            keep["agent_did"], dup["agent_did"],
            json.dumps({
                "why": "founder dedupe (scripts/dedupe_founders.py)",
                "merged_into": keep["agent_did"],
                "agent_id": str(dup["agent_id"]),
                "display_name": dup["display_name"],
                "role": dup["governance_role"],
                "status": dup["status"],
                "created_at": dup["created_at"].isoformat() if dup["created_at"] else None,
                "moved": dict(m.moved),
                "dropped": dict(m.dropped),
            }))
    if _n(await conn.execute("DELETE FROM agents WHERE agent_did = $1", dup["agent_did"])) != 1:
        raise DedupeError(f"{dup['agent_did']} was not deleted")


# ── One founder ───────────────────────────────────────────────────────────────

async def _rows_for(conn, name: str):
    """Rows that look like founder *name*, by DID or by display name, locked."""
    return await conn.fetch(
        """
        SELECT agent_did, agent_id, display_name, status::text AS status,
               governance_role::text AS governance_role, created_at,
               agent_did ~ ('^did:agentx:' || $1 || '(-seed)?-[0-9]{3}$') AS did_match,
               display_name ~* ('^' || $1 || '(_.{4})?$')              AS name_match
        FROM agents
        WHERE agent_did ~ ('^did:agentx:' || $1 || '(-seed)?-[0-9]{3}$')
           OR display_name ~* ('^' || $1 || '(_.{4})?$')
        ORDER BY created_at NULLS LAST, agent_did
        FOR UPDATE
        """,
        name,
    )


async def _create(conn, name: str, display: str, spec: dict[str, str],
                  agent_cols: set[str]) -> None:
    """A founder with no row: the same rows sign-up writes, as a MEMBER."""
    values = {
        "agent_did": canonical_did(name), "display_name": display,
        "agent_type": spec["agent_type"], "governance_role": "MEMBER",
        "bio": spec["bio"], "specialization": spec["specialization"],
        "name": display, "description": spec["bio"],
    }
    use = [c for c in values if c in agent_cols]
    casts = {"agent_type": "::agent_type", "governance_role": "::governance_role"}
    await conn.execute(
        f"INSERT INTO agents ({', '.join(_q(c) for c in use)}) VALUES ("
        + ", ".join(f"${i + 1}{casts.get(c, '')}" for i, c in enumerate(use)) + ")",
        *(values[c] for c in use))
    await conn.execute(
        "INSERT INTO agent_trust_breakdown (agent_did, execution_success, sla_compliance, "
        "peer_endorsements, audit_transparency, security_record) "
        "VALUES ($1, 0.50, 0.50, 0.00, 0.50, 1.00) ON CONFLICT (agent_did) DO NOTHING",
        canonical_did(name))


async def _recount(conn, did: str, agent_cols: set[str], tables: set[str]) -> None:
    """The kept row's stored counters, from the tables they count."""
    sets = []
    if {"followers_count", "following_count"} <= agent_cols and "follows" in tables:
        sets += ["followers_count = (SELECT count(*) FROM follows WHERE following_did = $1)",
                 "following_count = (SELECT count(*) FROM follows WHERE follower_did = $1)"]
    if "posts_count" in agent_cols and "posts" in tables:
        sets.append("posts_count = (SELECT count(*) FROM posts "
                    "WHERE author_did = $1 AND parent_post_id IS NULL)")
    if sets:
        await conn.execute(f"UPDATE agents SET {', '.join(sets)} WHERE agent_did = $1", did)


async def dedupe(conn, *, founders: dict[str, dict[str, str]] | None = None,
                 exclude: frozenset[str] = frozenset(), include_inactive: bool = False,
                 create: bool = True) -> list[Founder]:
    """Do the whole job on *conn*, inside the caller's transaction. *founders*
    maps a name to what a missing row is created from; an empty value means
    "merge duplicates of this name but never create it"."""
    founders = FOUNDERS if founders is None else founders
    for name in founders:
        if not _NAME_RE.match(name):
            raise DedupeError(f"not a founder name: {name!r}")
    await conn.execute("SET LOCAL lock_timeout = '10s'")
    await _preflight(conn)
    cols = await _identity_columns(conn)
    tables = {t for kind in cols.values() for t in kind}
    agent_cols = await _table_columns(conn, "agents")
    before = await _snapshot(conn, tables)

    # Pass 1: who is who.
    out: list[Founder] = []
    plans = []
    for name in sorted(founders):
        f = Founder(name)
        members = []
        for r in await _rows_for(conn, name):
            if not (r["did_match"] and r["name_match"]):
                f.left_alone.append((r["agent_did"],
                                     f'"{r["display_name"]}" looks like {name.upper()} by '
                                     f'{"DID" if r["did_match"] else "name"} only'))
            elif r["agent_did"] in exclude:
                f.left_alone.append((r["agent_did"], "excluded on the command line"))
            else:
                members.append(r)
        active = [r for r in members if r["status"] == "ACTIVE"]
        keep = None
        if active:
            keep = next((r for r in active if r["agent_did"] == canonical_did(name)), active[0])
        elif members:
            f.notes.append("has rows but none is ACTIVE; nothing done")
        out.append(f)
        plans.append((f, keep, members))

    # A founder created here is spelled like the ones already there ("Nova" → "Bruno").
    kept_names = [k["display_name"] for _, k, _ in plans if k is not None]
    title_case = any(not n.isupper() for n in kept_names)

    # Pass 2: act.
    for f, keep, members in plans:
        name = f.name
        if keep is None:
            if members or not create or not founders[name]:
                continue
            display = name.capitalize() if title_case else name.upper()
            try:
                async with conn.transaction():
                    await _create(conn, name, display, founders[name], agent_cols)
            except asyncpg.UniqueViolationError:
                f.notes.append(f'not created: the name "{display}" or the DID '
                               f"{canonical_did(name)} is taken by a row listed above")
                continue
            f.canonical, f.display_name, f.created = canonical_did(name), display, True
            continue

        f.canonical, f.display_name = keep["agent_did"], keep["display_name"]
        if keep["agent_did"] != canonical_did(name):
            f.notes.append(f"kept the oldest row; the runners expect {canonical_did(name)}")
        for dup in members:
            if dup["agent_did"] == keep["agent_did"]:
                continue
            if dup["status"] != "ACTIVE" and not include_inactive:
                f.left_alone.append((dup["agent_did"],
                                     f"status {dup['status']} (--include-inactive merges it)"))
                continue
            m = Merge(dup["agent_did"], dup["display_name"], dup["status"],
                      dup["governance_role"], dup["created_at"])
            await _merge(conn, cols, tables, keep, dup, m)
            f.merged.append(m)
        if f.merged:
            await _recount(conn, keep["agent_did"], agent_cols, tables)
        # Migration 038 may have left the suffixed name on the row that is kept.
        suffixed = re.fullmatch(rf"({name})_.{{4}}", keep["display_name"], re.IGNORECASE)
        if suffixed:
            try:
                async with conn.transaction():
                    await conn.execute("UPDATE agents SET display_name = $2 WHERE agent_did = $1",
                                       keep["agent_did"], suffixed.group(1))
                f.display_name = suffixed.group(1)
            except asyncpg.UniqueViolationError:
                f.notes.append(f'display name left as "{keep["display_name"]}": '
                               f'"{suffixed.group(1)}" is held by a row that was not merged')

    after = await _snapshot(conn, tables)
    if after != before:
        raise DedupeError(f"totals changed: before {before}, after {after}")
    return out


async def run(conn, *, apply: bool = False, **kwargs) -> list[Founder]:
    """One transaction. Committed only with ``apply=True`` and no error."""
    tr = conn.transaction()
    await tr.start()
    try:
        report = await dedupe(conn, **kwargs)
    except BaseException:
        await tr.rollback()
        raise
    if apply:
        await tr.commit()
    else:
        await tr.rollback()
    return report


# ── Command line ──────────────────────────────────────────────────────────────

def _counts(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))


def render(report: list[Founder], apply: bool) -> str:
    lines = []
    for f in report:
        if f.created:
            lines.append(f'{f.name.upper()}: CREATE {f.canonical} "{f.display_name}" (MEMBER)')
        elif f.canonical:
            lines.append(f'{f.name.upper()}: keep {f.canonical} "{f.display_name}"')
        else:
            lines.append(f"{f.name.upper()}: no row kept")
        for m in f.merged:
            lines.append(f'    MERGE {m.did} "{m.display_name}" ({m.status}, {m.role}, '
                         f"created {m.created_at:%Y-%m-%d}): "
                         f"{sum(m.moved.values())} moved, {sum(m.dropped.values())} dropped")
            if m.moved:
                lines.append(f"        moved:   {_counts(m.moved)}")
            if m.dropped:
                lines.append(f"        dropped (the kept row already had it): {_counts(m.dropped)}")
        for did, why in f.left_alone:
            lines.append(f"    left alone: {did} — {why}")
        for note in f.notes:
            lines.append(f"    note: {note}")
    kept = sum(1 for f in report if f.canonical and not f.created)
    made = sum(1 for f in report if f.created)
    merged = sum(len(f.merged) for f in report)
    alone = sum(len(f.left_alone) for f in report)
    lines.append("")
    lines.append(f"{kept} kept, {made} created, {merged} duplicate(s) merged, "
                 f"{alone} row(s) left alone.")
    lines.append("Written to the database." if apply
                 else "DRY RUN: nothing was changed. Pass --apply to write.")
    return "\n".join(lines)


async def _main(args) -> int:
    founders = dict(FOUNDERS)
    for extra in args.extra_name:
        founders.setdefault(extra.lower(), {})
    conn = await asyncpg.connect(args.dsn)
    try:
        report = await run(conn, apply=args.apply, founders=founders,
                           exclude=frozenset(args.exclude),
                           include_inactive=args.include_inactive,
                           create=not args.no_create)
    except (DedupeError, asyncpg.PostgresError) as exc:
        print(f"STOPPED, nothing was changed: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    print(render(report, args.apply))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="Postgres connection string")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--exclude", action="append", default=[], metavar="DID",
                        help="leave this row alone (repeatable)")
    parser.add_argument("--include-inactive", action="store_true",
                        help="also merge duplicates that are not ACTIVE")
    parser.add_argument("--no-create", action="store_true",
                        help="do not create a founder that has no row")
    parser.add_argument("--extra-name", action="append", default=[], metavar="NAME",
                        help="also merge duplicates of this seed persona, e.g. orion "
                             "(repeatable; never created)")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
