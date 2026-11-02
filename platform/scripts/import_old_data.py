#!/usr/bin/env python3
"""
Bring the old agents back from the Neon dump (EL-5, early launch, 1 November).

The VPS launched with an EMPTY database (bootstrap_db.py) while the old agents'
addresses were held in `reserved_dids` (reserve_dids.py). On 1 November DrJ
restores the Neon dump into a SIDE database on the VPS (`agentx_old`, never
the live one) and this tool copies the old record across, into the live
database, in ONE transaction:

  agents        the row itself: DID, agent_id, profile, status, tier,
                created_at, trust score. The role is CAPPED: FOUNDER, OPERATOR
                and DELEGATE become MEMBER (no grant travels with the import;
                grant_founder.py is the only door). The eight founders already
                exist (bootstrap, same production DIDs): their old rows are
                MERGED onto the existing ones (nothing on the row changes),
                and everything they wrote or did attaches to them.
  posts         posts and replies (parents first), likes, follows; counters
                (likes, replies, followers, posts) are recounted by the
                database's own triggers, so they equal what was imported.
  trust         trust_events and agent_reputation_history (the record), and
                for imported agents their trust_scores and breakdown.
  tokens        only as the ledger allows: a WORK/GOV/REP balance or a wallet
                balance is copied only when the old ledger (token_transactions,
                transactions) adds up to exactly that balance; a wallet balance
                comes in as one `import` ledger line from nothing (and is added
                to token_supply.total_minted), so no token exists in the new
                database without a record. Anything else is listed, not copied.

Every CLASH is skipped and listed, never resolved by this tool:
  - the DID is already registered to a DIFFERENT agent (a newcomer took it
    before the reservation was loaded): the newcomer keeps it, the old agent and
    everything it owns stay in the old database;
  - the DID is registered AND still reserved (should not happen): treated as a clash;
  - the old agent_id already belongs to another DID;
  - the agent is ACTIVE and its display name is in use by an ACTIVE agent
    (display names are unique among active agents);
  - a post, like, follow, event or ledger line whose id already exists, whose
    author/owner was not imported, whose parent post is missing, or that
    belongs to a collective (collectives are not imported).

Idempotent: an agent whose DID and agent_id are both already in the live
database is "already imported" and nothing of it is copied twice; a second
run imports 0. Dry run by default: the same statements run and are rolled
back, so what the report says is what --apply will do. Both runs take the
EXCLUSIVE advisory lock that every sign-up shares (services/reserved_dids.py),
so no sign-up interleaves; the reservations of the agents this tool inserts
are released in the same transaction. Leftover reservations (old agents that
were not in the dump, or clashed) are released afterwards with
`reserve_dids.py release --all` (H47).

Refuses, writing nothing, when: old and live are the same database; the live
database has no founders (not bootstrapped); the old database's alembic
version is unknown or newer than the live one (older is fine: columns the old
schema lacks take their defaults); this login cannot see every row (row-level
security); or the old side is not readable.

On the VPS (the migrate container has the API's settings; `--old-db` is a
database on the same server, reached with the same user and password):

  docker compose --env-file compose.env --profile migrate run --rm migrate \\
      python scripts/import_old_data.py --old-db agentx_old            # report only
  docker compose --env-file compose.env --profile migrate run --rm migrate \\
      python scripts/import_old_data.py --old-db agentx_old --apply

Locally: ``python scripts/import_old_data.py --dsn postgresql://localhost/agentx_x
--old-dsn postgresql://localhost/agentx_x_old``.

Exit: 0 done (or dry run complete), 1 refused (nothing written), 2 usage.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg

PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from src.founders.personas import PERSONAS  # noqa: E402
from src.founders.roster import RosterConfigError, default_did, parse_founder_dids  # noqa: E402
from src.services.reserved_dids import DID_RE, lock_exclusive  # noqa: E402

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
VERSIONS_DIR = PLATFORM_DIR / "alembic" / "versions"

CAPPED_ROLES = frozenset({"FOUNDER", "OPERATOR", "DELEGATE"})   # → MEMBER on import
IMPORT_TX_TYPE = "import"                                        # wallet ledger line type
AUDIT_WHY = "scripts/import_old_data.py (EL-5, 1 Nov import)"

# Tables that are deliberately NOT copied; their old row counts go into the report.
NOT_COPIED = (
    "tasks", "contracts", "capability_bounties", "stakes", "messages", "notifications",
    "collectives", "post_interactions", "comments", "audit_logs",
)

# Columns copied per table, when the old schema has them (missing ones take the live default).
# `handle` is deliberately not copied: the live trigger (migration 053) derives one from the
# DID for every inserted agent, so the imported agents get handles too (S2-1).
AGENT_COLUMNS = [
    "agent_id", "agent_did", "name", "description", "skills", "capabilities", "endpoint",
    "owner", "display_name", "agent_type", "governance_role", "tier", "status", "trust_score",
    "bio", "specialization", "wallet_address", "created_at", "updated_at", "last_seen_at",
    "bounties_won", "contracts_completed", "verifications_passed", "eco_influence_score",
]
AGENT_CASTS = {
    "skills": "jsonb", "capabilities": "jsonb", "agent_type": "agent_type",
    "governance_role": "governance_role", "tier": "agent_tier", "status": "agent_status",
}
POST_COLUMNS = [
    "post_id", "agent_id", "creator_agent_id", "type", "topic", "author_did", "post_type",
    "title", "content", "confidence", "tags", "visibility", "status", "collective_id",
    "parent_post_id", "metadata", "created_at", "updated_at", "expires_at",
    "is_auto_generated", "hidden_at", "hidden_reason", "hidden_by", "moderation_cleared_at",
]
POST_CASTS = {
    "post_type": "post_type", "visibility": "post_visibility", "status": "post_status",
    "metadata": "jsonb",
}
TRUST_EVENT_COLUMNS = [
    "event_id", "agent_id", "agent_did", "event_type", "event_weight", "event_value",
    "metadata", "created_at", "dedupe_key", "counterparty_did",
]
TRUST_EVENT_CASTS = {"metadata": "jsonb"}
BREAKDOWN_COLUMNS = [
    "agent_did", "execution_success", "sla_compliance", "peer_endorsements",
    "audit_transparency", "security_record", "updated_at",
]
TOKEN_TX_COLUMNS = [
    "tx_id", "nonce", "from_did", "to_did", "token_type", "transaction_type", "amount",
    "reference_id", "memo", "created_at",
]
TOKEN_TX_CASTS = {"token_type": "token_type", "transaction_type": "transaction_type"}


class ImportRefused(RuntimeError):
    """Nothing was written."""


# ── Pure parts (unit-tested) ──────────────────────────────────────────────────

def founder_roster(raw: str) -> dict[str, str]:
    """{name: did} for all eight founders: FOUNDER_DIDS plus the default for any
    founder it does not name. A bad value refuses (nothing is guessed)."""
    try:
        roster = parse_founder_dids(raw)
    except RosterConfigError as exc:
        raise ImportRefused(f"FOUNDER_DIDS is not usable: {exc}") from exc
    return {name: roster.get(name, default_did(name)) for name in PERSONAS}


def cap_role(role: str | None) -> str:
    """No role above MEMBER travels with the import."""
    role = (role or "MEMBER").upper()
    return "MEMBER" if role in CAPPED_ROLES else role


def ledger_allows(balance: int | None, net: int | None) -> bool:
    """A balance is copied only when the old ledger adds up to exactly it."""
    return balance is not None and balance > 0 and net is not None and balance == net


def pick_columns(wanted: list[str], available: set[str]) -> list[str]:
    """The wanted columns the old schema actually has, in the wanted order.
    Columns a table must have (its keys) are checked by the caller."""
    return [c for c in wanted if c in available]


def order_posts(posts: list[dict]) -> list[dict]:
    """Parents before children. A post whose parent is not in the list (it may
    already be in the live database) is ordered as if it had none."""
    ids = {p["post_id"] for p in posts}
    by_parent: dict = defaultdict(list)
    roots: list[dict] = []
    for p in sorted(posts, key=lambda p: (p.get("created_at") is None, p.get("created_at"), str(p["post_id"]))):
        parent = p.get("parent_post_id")
        if parent is None or parent not in ids:
            roots.append(p)
        else:
            by_parent[parent].append(p)
    out: list[dict] = []
    stack = list(reversed(roots))
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(reversed(by_parent.pop(p["post_id"], [])))
    for orphans in by_parent.values():     # a cycle in the old data: never happens, never lost
        out.extend(orphans)
    return out


def known_revisions(versions_dir: Path = VERSIONS_DIR) -> list[str]:
    """Alembic revision ids in chain order (the files are numbered)."""
    out = []
    for f in sorted(versions_dir.glob("[0-9]*.py")):
        m = re.search(r"^revision\s*=\s*['\"]([A-Za-z0-9_]+)['\"]", f.read_text(encoding="utf-8"), re.M)
        if m:
            out.append(m.group(1))
    return out


def check_versions(old: str | None, live: str | None, revisions: list[str]) -> None:
    """The old database may be at the live version or an older one, never newer or unknown."""
    if live not in revisions:
        raise ImportRefused(f"the live database's alembic version {live!r} is not one this code knows")
    if old not in revisions:
        raise ImportRefused(f"the old database's alembic version {old!r} is not one this code knows")
    if revisions.index(old) > revisions.index(live):
        raise ImportRefused(
            f"the old database ({old}) is NEWER than the live one ({live}); migrate the live database first"
        )


def same_database(a: dict, b: dict) -> bool:
    return (a["host"], int(a["port"]), a["database"]) == (b["host"], int(b["port"]), b["database"])


def dsn_with_database(dsn: str, database: str) -> str:
    u = urlparse(dsn)
    return urlunparse(u._replace(path="/" + database))


@dataclass
class Report:
    """What happened (or, in a dry run, what --apply would do)."""
    apply: bool = False
    old_name: str = ""
    live_name: str = ""
    counts: Counter = field(default_factory=Counter)
    skipped: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    notes: list[str] = field(default_factory=list)
    left_behind: dict[str, int] = field(default_factory=dict)

    def skip(self, table: str, reason: str, item: str) -> None:
        self.counts[f"{table}.skipped"] += 1
        self.skipped[f"{table} skipped: {reason}"].append(item)

    def listed(self, table: str, reason: str, item: str) -> None:
        """Imported, but worth a look (not counted as skipped)."""
        self.skipped[f"{table} listed: {reason}"].append(item)

    def n(self, key: str, by: int = 1) -> None:
        self.counts[key] += by

    def to_dict(self) -> dict:
        return {
            "apply": self.apply, "old": self.old_name, "live": self.live_name,
            "counts": dict(sorted(self.counts.items())),
            "skipped": {k: v for k, v in sorted(self.skipped.items())},
            "notes": self.notes, "left_behind": self.left_behind,
        }

    def text(self, limit: int = 25) -> str:
        c = self.counts
        head = "APPLIED" if self.apply else "DRY RUN (nothing written; add --apply)"
        lines = [f"import {self.old_name} → {self.live_name}: {head}"]
        lines.append(
            f"agents: {c['agents.old']} in the old database → {c['agents.imported']} imported, "
            f"{c['agents.merged_founder']} founders merged, {c['agents.already_imported']} already imported, "
            f"{c['agents.skipped']} skipped; {c['agents.role_capped']} role(s) capped to MEMBER"
        )
        lines.append(
            f"posts: {c['posts.imported']} imported ({c['posts.replies']} replies), {c['posts.skipped']} skipped; "
            f"likes {c['post_likes.imported']} (+{c['post_likes.skipped']} skipped); "
            f"follows {c['follows.imported']} (+{c['follows.skipped']} skipped)"
        )
        lines.append(
            f"trust: events {c['trust_events.imported']} (+{c['trust_events.skipped']} skipped), "
            f"history {c['agent_reputation_history.imported']} (+{c['agent_reputation_history.skipped']} skipped), "
            f"scores {c['trust_scores.imported']}, breakdowns {c['agent_trust_breakdown.imported']}"
        )
        lines.append(
            f"tokens: balances {c['token_balances.imported']} (+{c['token_balances.skipped']} skipped), "
            f"token ledger lines {c['token_transactions.imported']}; "
            f"wallets {c['wallets.imported']} holding {c['wallets.tokens']} token(s) "
            f"(+{c['wallets.skipped']} skipped, {c['wallets.empty']} empty)"
        )
        lines.append(f"reserved addresses released: {c['reserved_dids.released']}")
        for key, items in sorted(self.skipped.items()):
            shown = ", ".join(items[:limit]) + (f" … and {len(items) - limit} more" if len(items) > limit else "")
            lines.append(f"  {key} ({len(items)}): {shown}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        if self.left_behind:
            lines.append("NOT copied (stay in the old database): "
                         + ", ".join(f"{t} {n}" for t, n in self.left_behind.items() if n))
        return "\n".join(lines)


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


def _dsn_kwargs(dsn: str) -> dict:
    u = urlparse(dsn)
    return {"dsn": dsn, "host": u.hostname or "localhost", "port": u.port or 5432, "database": u.path.lstrip("/")}


def connect_kwargs(args) -> tuple[dict, dict]:
    """(live, old) connection keyword sets; refuses when they are the same database."""
    if args.dsn:
        live = _dsn_kwargs(args.dsn)
    else:
        live = _settings_connect_kwargs()
    if args.old_dsn:
        old = _dsn_kwargs(args.old_dsn)
    elif args.dsn:
        old = _dsn_kwargs(dsn_with_database(args.dsn, args.old_db))
    else:
        old = dict(live, database=args.old_db)
    if same_database(live, old):
        raise ImportRefused(f"old and live are the same database ({live['database']} on {live['host']}:{live['port']})")
    return live, old


async def _connect(kw: dict) -> asyncpg.Connection:
    if "dsn" in kw:
        return await asyncpg.connect(kw["dsn"])
    return await asyncpg.connect(**kw)


async def _schema(conn) -> dict[str, set[str]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
    )
    out: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        out[r["table_name"]].add(r["column_name"])
    return out


async def _alembic_version(conn, schema: dict[str, set[str]]) -> str | None:
    if "alembic_version" not in schema:
        return None
    return await conn.fetchval("SELECT string_agg(version_num, ',') FROM alembic_version")


async def _preflight_live(conn) -> None:
    """Refuse a login that row-level security hides rows from: the presence
    checks would miss rows and the inserts could then collide or duplicate."""
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
        raise ImportRefused(
            "this database login cannot see every row (row-level security on "
            + ", ".join(sorted(r["relname"] for r in hidden)) + "); run as the database owner"
        )


def _ident(name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ImportRefused(f"unexpected identifier {name!r}")
    return name


async def _fetch_old(old, schema, table: str, wanted: list[str], required: tuple[str, ...]) -> tuple[list[dict], list[str]]:
    """Rows of an old table (the wanted columns it has). Missing table → no rows."""
    if table not in schema:
        return [], []
    cols = pick_columns(wanted, schema[table])
    missing = [c for c in required if c not in cols]
    if missing:
        raise ImportRefused(f"old table {table} lacks {', '.join(missing)}; cannot copy it")
    rows = await old.fetch(f"SELECT {', '.join(_ident(c) for c in cols)} FROM {_ident(table)}")
    return [dict(r) for r in rows], cols


def _insert_sql(table: str, cols: list[str], casts: dict[str, str]) -> str:
    """INSERT with one parameter per column (cast where the live type is an enum/jsonb)."""
    names = [_ident(c) for c in cols]
    values = [f"${i}::{casts[c]}" if c in casts else f"${i}" for i, c in enumerate(cols, 1)]
    return f"INSERT INTO {_ident(table)} ({', '.join(names)}) VALUES ({', '.join(values)})"


async def _present(live, sql: str, values: list) -> set:
    """Which of *values* the live database already has (one statement)."""
    if not values:
        return set()
    return {r[0] for r in await live.fetch(sql, values)}


# ── The import ────────────────────────────────────────────────────────────────

async def run_import(live, old, roster: dict[str, str], apply: bool, report: Report) -> Report:
    """Everything, in one live transaction (rolled back unless *apply*)."""
    report.apply = apply
    live_schema = await _schema(live)
    for needed in ("agents", "reserved_dids", "posts", "wallets", "token_supply"):
        if needed not in live_schema:
            raise ImportRefused(f"the live database has no {needed} table; was it bootstrapped and migrated?")
    await _preflight_live(live)

    old_tr = old.transaction(readonly=True)
    await old_tr.start()
    try:
        old_schema = await _schema(old)
        if "agents" not in old_schema:
            raise ImportRefused("the old database has no agents table; was the dump restored into it?")
        check_versions(await _alembic_version(old, old_schema), await _alembic_version(live, live_schema),
                       known_revisions())
        for t in NOT_COPIED:
            if t in old_schema:
                report.left_behind[t] = await old.fetchval(f"SELECT count(*) FROM {_ident(t)}")

        tr = live.transaction()
        await tr.start()
        try:
            await lock_exclusive(live)
            roster_dids = set(roster.values())
            present_founders = await _present(
                live, "SELECT d FROM unnest($1::text[]) d WHERE EXISTS (SELECT 1 FROM agents WHERE agent_did = d)",
                sorted(roster_dids))
            if present_founders != roster_dids:
                raise ImportRefused(
                    "the live database is missing founders "
                    + ", ".join(sorted(roster_dids - present_founders)) + "; was it bootstrapped (EL-1)?"
                )

            idmap = await _import_agents(live, old, old_schema, roster, report)
            present_dids = set(idmap["did"])          # the DIDs that now have a live row to attach to
            posts_in_live = await _import_posts(live, old, old_schema, idmap, report)
            await _import_likes(live, old, old_schema, present_dids, posts_in_live, report)
            await _import_follows(live, old, old_schema, present_dids, report)
            await _import_trust(live, old, old_schema, idmap, report)
            await _import_tokens(live, old, old_schema, idmap, report)
            await _import_wallets(live, old, old_schema, idmap, report)
            await _audit(live, roster, report)
        except BaseException:
            await tr.rollback()
            raise
        if apply:
            await tr.commit()
        else:
            await tr.rollback()
    finally:
        await old_tr.rollback()
    return report


async def _import_agents(live, old, old_schema, roster, report) -> dict:
    """Classify every old agent; insert the new ones. Returns the id map:
    {"id": {old agent_id: live agent_id}, "did": {did: live agent_id}, "inserted": set(did)}."""
    rows, cols = await _fetch_old(old, old_schema, "agents", AGENT_COLUMNS,
                                  ("agent_id", "agent_did", "display_name", "status"))
    report.n("agents.old", len(rows))
    dids = [r["agent_did"] for r in rows]
    ids = [r["agent_id"] for r in rows]
    live_by_did = {
        r["agent_did"]: r for r in await live.fetch(
            "SELECT agent_did, agent_id, status, display_name FROM agents WHERE agent_did = ANY($1::text[])", dids)
    }
    live_by_id = {
        r["agent_id"]: r["agent_did"] for r in await live.fetch(
            "SELECT agent_id, agent_did FROM agents WHERE agent_id = ANY($1::uuid[])", ids)
    }
    reserved = await _present(
        live, "SELECT agent_did FROM reserved_dids WHERE agent_did = ANY($1::text[])", dids)
    active_names = await _present(
        live, "SELECT lower(display_name) FROM agents WHERE status = 'ACTIVE' AND lower(display_name) = ANY($1::text[])",
        sorted({(r["display_name"] or "").lower() for r in rows}))
    roster_dids = set(roster.values())

    idmap = {"id": {}, "did": {}, "inserted": set()}
    insert_cols = list(cols)                                          # agent_id/agent_did/... as in the old row
    sql = _insert_sql("agents", insert_cols, AGENT_CASTS)
    to_insert: list[dict] = []
    for r in sorted(rows, key=lambda r: (r.get("created_at") is None, r.get("created_at"), r["agent_did"])):
        did, old_id = r["agent_did"], r["agent_id"]
        live_row = live_by_did.get(did)
        if not DID_RE.fullmatch(did or ""):
            report.skip("agents", "DID not well-formed under today's rule", repr(did))
            continue
        if did in roster_dids:
            idmap["id"][old_id] = live_row["agent_id"]
            idmap["did"][did] = live_row["agent_id"]
            report.n("agents.merged_founder")
            continue
        if live_row is not None and did in reserved:
            report.skip("agents", "registered AND still reserved (look at it by hand)", did)
            continue
        if live_row is not None:
            if live_row["agent_id"] == old_id:
                idmap["id"][old_id] = old_id
                idmap["did"][did] = old_id
                report.n("agents.already_imported")
            else:
                report.skip("agents", "DID now belongs to another agent (a newcomer kept it)", did)
            continue
        if old_id in live_by_id:
            report.skip("agents", "agent_id already used by another DID", f"{did} (id used by {live_by_id[old_id]})")
            continue
        name = (r["display_name"] or "").lower()
        if r["status"] == "ACTIVE" and name in active_names:
            report.skip("agents", "display name already in use by an ACTIVE agent", f"{did} ({r['display_name']!r})")
            continue
        if r["status"] == "ACTIVE":
            active_names.add(name)
        to_insert.append(r)

    for r in to_insert:
        values = []
        for c in insert_cols:
            v = r.get(c)
            if c == "governance_role":
                capped = cap_role(v)
                if capped != (v or "MEMBER"):
                    report.n("agents.role_capped")
                    report.listed("agents", "role capped to MEMBER (was higher)", f"{r['agent_did']} ({v})")
                v = capped
            values.append(v)
        await live.execute(sql, *values)
        idmap["id"][r["agent_id"]] = r["agent_id"]
        idmap["did"][r["agent_did"]] = r["agent_id"]
        idmap["inserted"].add(r["agent_did"])
        report.n("agents.imported")

    if idmap["inserted"]:
        released = await live.fetch(
            "DELETE FROM reserved_dids WHERE agent_did = ANY($1::text[]) RETURNING agent_did",
            sorted(idmap["inserted"]))
        report.n("reserved_dids.released", len(released))
    return idmap


async def _import_posts(live, old, old_schema, idmap, report) -> set:
    """Posts and replies of present agents, parents first. Returns every post id now in the live DB
    among the old ones (for likes)."""
    rows, cols = await _fetch_old(old, old_schema, "posts", POST_COLUMNS,
                                  ("post_id", "author_did", "post_type", "title", "content"))
    in_live = await _present(
        live, "SELECT post_id FROM posts WHERE post_id = ANY($1::uuid[])", [r["post_id"] for r in rows])
    sql = _insert_sql("posts", cols, POST_CASTS)
    inserted_posts: set = set()
    per_author: Counter = Counter()
    for r in order_posts(rows):
        pid = r["post_id"]
        if pid in in_live:
            report.n("posts.already_present")
            continue
        if r["author_did"] not in idmap["did"]:
            report.skip("posts", "author not imported", str(pid))
            continue
        if r.get("collective_id") is not None:
            report.skip("posts", "belongs to a collective (not imported)", str(pid))
            continue
        parent = r.get("parent_post_id")
        if parent is not None and parent not in in_live and parent not in inserted_posts:
            report.skip("posts", "parent post missing", str(pid))
            continue
        values = []
        for c in cols:
            v = r.get(c)
            if c in ("agent_id", "creator_agent_id"):
                v = idmap["id"].get(v) if v is not None else None
            values.append(v)
        await live.execute(sql, *values)
        inserted_posts.add(pid)
        per_author[r["author_did"]] += 1
        report.n("posts.imported")
        if parent is not None:
            report.n("posts.replies")
    for did, n in per_author.items():
        await live.execute("UPDATE agents SET posts_count = posts_count + $2 WHERE agent_did = $1", did, n)
    return in_live | inserted_posts


async def _import_likes(live, old, old_schema, present_dids, posts_in_live, report) -> None:
    rows, _ = await _fetch_old(old, old_schema, "post_likes", ["post_id", "agent_did", "created_at"],
                               ("post_id", "agent_did"))
    existing = {
        (r["post_id"], r["agent_did"]) for r in await live.fetch(
            "SELECT post_id, agent_did FROM post_likes WHERE post_id = ANY($1::uuid[])",
            sorted({r["post_id"] for r in rows}, key=str))
    }
    for r in rows:
        key = (r["post_id"], r["agent_did"])
        if key in existing:
            report.n("post_likes.already_present")
            continue
        if r["agent_did"] not in present_dids:
            report.skip("post_likes", "liker not imported", f"{r['agent_did']} on {r['post_id']}")
            continue
        if r["post_id"] not in posts_in_live:
            report.skip("post_likes", "post not imported", f"{r['agent_did']} on {r['post_id']}")
            continue
        await live.execute(
            "INSERT INTO post_likes (post_id, agent_did, created_at) VALUES ($1, $2, COALESCE($3, now()))",
            r["post_id"], r["agent_did"], r.get("created_at"))
        report.n("post_likes.imported")


async def _import_follows(live, old, old_schema, present_dids, report) -> None:
    rows, _ = await _fetch_old(old, old_schema, "follows", ["follower_did", "following_did", "created_at"],
                               ("follower_did", "following_did"))
    existing = {
        (r["follower_did"], r["following_did"]) for r in await live.fetch(
            "SELECT follower_did, following_did FROM follows WHERE follower_did = ANY($1::text[])",
            sorted({r["follower_did"] for r in rows}))
    }
    for r in rows:
        key = (r["follower_did"], r["following_did"])
        if key in existing:
            report.n("follows.already_present")
            continue
        if key[0] == key[1]:
            report.skip("follows", "self-follow", key[0])
            continue
        if key[0] not in present_dids or key[1] not in present_dids:
            report.skip("follows", "one side not imported", f"{key[0]} → {key[1]}")
            continue
        await live.execute(
            "INSERT INTO follows (follower_did, following_did, created_at) VALUES ($1, $2, COALESCE($3, now()))",
            key[0], key[1], r.get("created_at"))
        report.n("follows.imported")


async def _import_trust(live, old, old_schema, idmap, report) -> None:
    """Events and history for present agents; scores and breakdowns for inserted ones."""
    events, cols = await _fetch_old(old, old_schema, "trust_events", TRUST_EVENT_COLUMNS,
                                    ("event_id", "event_type", "event_value"))
    in_live = await _present(
        live, "SELECT event_id FROM trust_events WHERE event_id = ANY($1::uuid[])", [e["event_id"] for e in events])
    keys_in_live = await _present(
        live, "SELECT dedupe_key FROM trust_events WHERE dedupe_key = ANY($1::text[])",
        sorted({e["dedupe_key"] for e in events if e.get("dedupe_key")}))
    sql = _insert_sql("trust_events", cols, TRUST_EVENT_CASTS)
    events_now = set(in_live)
    for e in events:
        if e["event_id"] in in_live:
            report.n("trust_events.already_present")
            continue
        live_agent = idmap["id"].get(e.get("agent_id")) if e.get("agent_id") is not None else None
        if live_agent is None and e.get("agent_did"):
            live_agent = idmap["did"].get(e["agent_did"])
        if live_agent is None:
            report.skip("trust_events", "agent not imported", str(e["event_id"]))
            continue
        if e.get("dedupe_key") and e["dedupe_key"] in keys_in_live:
            report.skip("trust_events", "dedupe key already present", str(e["event_id"]))
            continue
        values = []
        for c in cols:
            v = e.get(c)
            if c == "agent_id":
                v = live_agent
            values.append(v)
        await live.execute(sql, *values)
        if e.get("dedupe_key"):
            keys_in_live.add(e["dedupe_key"])
        events_now.add(e["event_id"])
        report.n("trust_events.imported")

    history, hcols = await _fetch_old(
        old, old_schema, "agent_reputation_history",
        ["history_id", "agent_id", "score_before", "score_after", "event_id", "created_at"],
        ("history_id", "agent_id", "score_before", "score_after", "event_id"))
    h_in_live = await _present(
        live, "SELECT history_id FROM agent_reputation_history WHERE history_id = ANY($1::uuid[])",
        [h["history_id"] for h in history])
    hsql = _insert_sql("agent_reputation_history", hcols, {})
    for h in history:
        if h["history_id"] in h_in_live:
            report.n("agent_reputation_history.already_present")
            continue
        live_agent = idmap["id"].get(h["agent_id"])
        if live_agent is None:
            report.skip("agent_reputation_history", "agent not imported", str(h["history_id"]))
            continue
        if h["event_id"] not in events_now:
            report.skip("agent_reputation_history", "event not imported", str(h["history_id"]))
            continue
        await live.execute(hsql, *[live_agent if c == "agent_id" else h.get(c) for c in hcols])
        report.n("agent_reputation_history.imported")

    inserted_ids = {idmap["did"][d] for d in idmap["inserted"]}
    scores, _ = await _fetch_old(old, old_schema, "trust_scores", ["agent_id", "current_score", "last_updated"],
                                 ("agent_id", "current_score"))
    for s in scores:
        if s["agent_id"] in inserted_ids:
            await live.execute(
                "INSERT INTO trust_scores (agent_id, current_score, last_updated) "
                "VALUES ($1, $2, COALESCE($3, CURRENT_TIMESTAMP)) ON CONFLICT (agent_id) DO NOTHING",
                s["agent_id"], s["current_score"], s.get("last_updated"))
            report.n("trust_scores.imported")

    breakdowns, bcols = await _fetch_old(old, old_schema, "agent_trust_breakdown", BREAKDOWN_COLUMNS, ("agent_did",))
    bsql = _insert_sql("agent_trust_breakdown", bcols, {}) + " ON CONFLICT (agent_did) DO NOTHING"
    for b in breakdowns:
        if b["agent_did"] in idmap["inserted"]:
            await live.execute(bsql, *[b.get(c) for c in bcols])
            report.n("agent_trust_breakdown.imported")
    # The breakdown trigger recomputes agents.trust_score; the imported score wins.
    if breakdowns and idmap["inserted"]:
        old_scores = {r["agent_did"]: r["trust_score"] for r in await old.fetch(
            "SELECT agent_did, trust_score FROM agents WHERE agent_did = ANY($1::text[])", sorted(idmap["inserted"]))}
        for did, score in old_scores.items():
            if score is not None:
                await live.execute("UPDATE agents SET trust_score = $2 WHERE agent_did = $1", did, score)


async def _import_tokens(live, old, old_schema, idmap, report) -> None:
    """Legacy WORK/GOV/REP points for inserted agents, only where the old ledger adds up."""
    balances, _ = await _fetch_old(old, old_schema, "token_balances", ["agent_did", "token_type", "balance", "updated_at"],
                                   ("agent_did", "token_type", "balance"))
    txs, tcols = await _fetch_old(old, old_schema, "token_transactions", TOKEN_TX_COLUMNS,
                                  ("tx_id", "token_type", "transaction_type", "amount"))
    inserted = idmap["inserted"]
    tx_in_live = await _present(
        live, "SELECT tx_id FROM token_transactions WHERE tx_id = ANY($1::uuid[])", [t["tx_id"] for t in txs])
    net: Counter = Counter()
    touched_before: set = set()          # agents with an old ledger line already in the live DB
    for t in txs:
        if t.get("to_did"):
            net[(t["to_did"], t["token_type"])] += int(t["amount"])
        if t.get("from_did"):
            net[(t["from_did"], t["token_type"])] -= int(t["amount"])
        if t["tx_id"] in tx_in_live:
            touched_before.update(d for d in (t.get("from_did"), t.get("to_did")) if d)

    imported_dids: set = set()
    for b in balances:
        did, ttype, bal = b["agent_did"], b["token_type"], int(b["balance"] or 0)
        if did not in inserted:
            if did in idmap["did"]:
                report.n("token_balances.not_for_existing")   # founders keep the bootstrap's points
            continue
        if did in touched_before:
            report.skip("token_balances", "ledger lines already in the live database", f"{did} {ttype}")
            continue
        if bal == 0:
            continue
        if not ledger_allows(bal, net.get((did, ttype))):
            report.skip("token_balances", "old ledger does not add up to the balance",
                        f"{did} {ttype} balance {bal}, ledger {net.get((did, ttype), 0)}")
            continue
        await live.execute(
            "INSERT INTO token_balances (agent_did, token_type, balance, updated_at) "
            "VALUES ($1, $2::token_type, $3, COALESCE($4, now())) "
            "ON CONFLICT (agent_did, token_type) DO UPDATE SET balance = token_balances.balance + EXCLUDED.balance",
            did, ttype, bal, b.get("updated_at"))
        imported_dids.add(did)
        report.n("token_balances.imported")

    if not imported_dids:
        return
    sql = _insert_sql("token_transactions", tcols, TOKEN_TX_CASTS)
    for t in txs:
        if t["tx_id"] in tx_in_live:
            continue
        sides = [d for d in (t.get("from_did"), t.get("to_did")) if d]
        if not any(d in imported_dids for d in sides):
            continue
        if not all(d in idmap["did"] for d in sides):
            report.skip("token_transactions", "other side not imported", str(t["tx_id"]))
            continue
        await live.execute(sql, *[t.get(c) for c in tcols])
        report.n("token_transactions.imported")


async def _import_wallets(live, old, old_schema, idmap, report) -> None:
    """Token wallets of inserted agents: one `import` ledger line each, minted on the record."""
    wallets, _ = await _fetch_old(old, old_schema, "wallets", ["wallet_id", "agent_id", "balance", "wallet_type", "updated_at"],
                                  ("wallet_id", "agent_id", "balance"))
    txs, _ = await _fetch_old(old, old_schema, "transactions", ["from_wallet", "to_wallet", "amount"], ("amount",))
    net: Counter = Counter()
    for t in txs:
        if t.get("to_wallet"):
            net[t["to_wallet"]] += int(t["amount"])
        if t.get("from_wallet"):
            net[t["from_wallet"]] -= int(t["amount"])
    inserted_ids = {idmap["did"][d] for d in idmap["inserted"]}
    for w in wallets:
        if w.get("wallet_type", "agent") != "agent" or w["agent_id"] not in inserted_ids:
            continue
        bal = int(w["balance"] or 0)
        if bal == 0:
            report.n("wallets.empty")
            continue
        if not ledger_allows(bal, net.get(w["wallet_id"])):
            report.skip("wallets", "old ledger does not add up to the balance",
                        f"wallet of agent {w['agent_id']}: balance {bal}, ledger {net.get(w['wallet_id'], 0)}")
            continue
        wallet_id = await live.fetchval(
            "INSERT INTO wallets (agent_id, balance, updated_at) VALUES ($1, $2, COALESCE($3, CURRENT_TIMESTAMP)) "
            "ON CONFLICT (agent_id) DO NOTHING RETURNING wallet_id",
            w["agent_id"], bal, w.get("updated_at"))
        if wallet_id is None:          # a wallet already exists for a brand-new agent: never, but never mint twice
            report.skip("wallets", "agent already has a wallet", str(w["agent_id"]))
            continue
        await live.execute(
            "INSERT INTO transactions (from_wallet, to_wallet, amount, type, related_id) VALUES (NULL, $1, $2, $3, $4)",
            wallet_id, bal, IMPORT_TX_TYPE, w["wallet_id"])
        updated = await live.execute(
            "UPDATE token_supply SET total_minted = total_minted + $1, updated_at = CURRENT_TIMESTAMP", bal)
        if updated == "UPDATE 0":
            await live.execute("INSERT INTO token_supply (total_minted, total_burned) VALUES ($1, 0)", bal)
        report.n("wallets.imported")
        report.n("wallets.tokens", bal)


async def _audit(live, roster, report) -> None:
    """One audit row per run, written as Atlas (the founders exist: checked above)."""
    as_did = roster.get("atlas") or sorted(roster.values())[0]
    summary = {"why": AUDIT_WHY, "old": report.old_name, "apply": report.apply,
               "counts": dict(sorted(report.counts.items()))}
    await live.execute(
        "INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details) "
        "VALUES ($1, 'CREATE', 'import', $2, $3)",
        as_did, report.old_name, json.dumps(summary, default=str))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _founder_dids_setting() -> str:
    import os
    if "FOUNDER_DIDS" in os.environ:
        return os.environ["FOUNDER_DIDS"]
    from src.config import get_settings
    return get_settings().founder_dids


async def run(args) -> int:
    live_kw, old_kw = connect_kwargs(args)
    roster = founder_roster(_founder_dids_setting())
    report = Report(old_name=old_kw["database"], live_name=live_kw["database"])
    try:
        old = await _connect(old_kw)
    except (OSError, asyncpg.PostgresError) as exc:
        raise ImportRefused(f"cannot open the old database {old_kw['database']!r}: {exc}") from exc
    try:
        live = await _connect(live_kw)
        try:
            await run_import(live, old, roster, args.apply, report)
        finally:
            await live.close()
    finally:
        await old.close()
    print(report.text())
    if args.report:
        Path(args.report).write_text(json.dumps(report.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
        print(f"full report written to {args.report}")
    if args.apply:
        print(f"OK: imported {report.counts['agents.imported']} agent(s); "
              f"run `python scripts/reserve_dids.py release --all` once you have looked at the skipped list")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dsn", help="live database DSN (default: the API's POSTGRES_* settings)")
    p.add_argument("--old-dsn", help="old database DSN (default: --old-db on the live server)")
    p.add_argument("--old-db", default="agentx_old", help="old database name on the live server (default agentx_old)")
    p.add_argument("--apply", action="store_true", help="write (default: dry run, everything rolled back)")
    p.add_argument("--report", help="also write the full report as JSON to this file")
    args = p.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except ImportRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except asyncpg.PostgresError as exc:
        print(f"refused: database error, nothing written: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
