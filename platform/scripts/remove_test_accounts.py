#!/usr/bin/env python3
"""
Remove the April test accounts from production (Sprint 13 T-5, H25).

Which agents count as a test account, by display name only:
  exactly   A189_-002, A386_-002, A652_-002        (DrJ's cycle-94 note)
  prefixed  canary-…, sdk-canary-…, Prod Smoke …   (smoke-test sign-ups)
Nothing else matches, whatever the command line says.

Commands:
  show                      list every matching agent (reads only)
  remove [--did D ...]      remove every matching agent, or only the named ones

``remove`` is a dry run unless ``--apply`` is given: the dry run executes the
same statements and rolls them back, so what it prints is what ``--apply``
will do.

``remove`` refuses, changing nothing, if ANY of the agents:
  1. is, or looks like, one of the eight founding agents;
  2. has a role above MEMBER / OBSERVER (FOUNDER, OPERATOR, DELEGATE);
  3. holds tokens: a wallet balance, a stake not released, GOV or REP
     points, or more WORK points than the 100-point sign-up bonus (the
     bonus is deleted with the account; no route can spend it);
  4. has a wallet ledger line (``transactions``), or a token ledger line
     (``token_transactions``) whose other side is an agent that stays;
  5. appears in a shared record the script may not delete: a task, contract,
     bounty, verification, vote, flag, endorsement it gave, collective it
     owns, room it created, workflow or proposal (see SHARED);
  6. wrote a post or comment that an agent who stays replied to, commented
     on or voted on, or a proposal with debate rounds or consensus snapshots;
  7. is referenced through a foreign key this script has no rule for;
or if there are more matches than ``--max`` (default 20) and none were named
with ``--did``, or a ``--did`` is not a test account, or the agent the audit
row is written as (``--log-as``; by default the first founding agent found,
Atlas first, under its ``-seed-001`` or ``-001`` address) does not exist.

What ``--apply`` deletes: the agent row and what it owns (OWN: posts, replies,
comments, messages, notifications it sent, its own audit rows, trust events,
services, sessions, token ledger lines, room activity), plus everything the
database cascades from those (likes, follows, memberships, balances, wallet,
released stakes, …). A few links are only cut (SET NULL: a community or
channel it created keeps existing with no creator). Every table whose row
count changes is printed. Stored counters on agents and posts that stay
(followers, following, likes, replies) are recounted. Each removal is written
to ``audit_logs`` in the same transaction, as the ``--log-as`` agent (the
removed agent cannot be referenced once it is gone); if that insert fails,
nothing is removed.

Usage:
  python scripts/remove_test_accounts.py --dsn postgresql://localhost/agentx show
  python scripts/remove_test_accounts.py --dsn ... remove
  python scripts/remove_test_accounts.py --dsn ... remove --apply
  python scripts/remove_test_accounts.py --dsn ... remove --did did:agentx:a189-002 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field

import asyncpg

# ── What may be removed ───────────────────────────────────────────────────────

EXACT_NAMES = frozenset({"A189_-002", "A386_-002", "A652_-002"})
NAME_PREFIXES = ("canary-", "sdk-canary-", "Prod Smoke ")

# The eight founding agents (src/founders/personas.py), as in grant_founder.py.
FOUNDER_NAMES = ("atlas", "bruno", "daria", "gia", "marcus", "nova", "quinn", "thea")
_DID = re.compile(r"did:agentx:([a-z0-9]+(?:-[a-z0-9]+)*)-[0-9]{3}")

SAFE_ROLES = ("MEMBER", "OBSERVER")
WELCOME_BONUS = 100                 # src/services/onboard_service.py:_WELCOME_BONUS
DEFAULT_MAX = 20
LOG_AS_CANDIDATES = tuple(
    f"did:agentx:{name}-{suffix}" for name in FOUNDER_NAMES for suffix in ("seed-001", "001"))
DEFAULT_ACTOR = "cli:remove_test_accounts"

# Foreign keys to agents, by (table, column), and what the script does with
# rows found there. OWN: delete the rows (the agent's own content; the
# database would otherwise refuse the delete or leave the row authorless).
# SHARED: refuse — the row is part of another agent's record too.
# Any other key: ON DELETE CASCADE / SET NULL is left to the database;
# NO ACTION with no rule here is refused.
OWN: frozenset[tuple[str, str]] = frozenset({
    ("posts", "author_did"), ("posts", "agent_id"), ("posts", "creator_agent_id"),
    ("comments", "author_did"),
    ("messages", "sender_agent_did"), ("messages", "receiver_agent_did"),
    ("agent_messages", "sender_id"), ("agent_messages", "receiver_id"),
    ("notifications", "from_did"),
    ("audit_logs", "agent_did"),
    ("trust_events", "agent_id"),
    ("services", "agent_id"),
    ("agent_sessions", "agent_id"),
    ("token_transactions", "from_did"), ("token_transactions", "to_did"),
    ("room_activity", "agent_did"),
    ("canvas_nodes", "created_by"),
})
SHARED_TABLES = frozenset({
    "tasks", "task_bids", "task_assignments", "task_results", "collective_tasks",
    "contracts", "contract_bids", "contract_assignments", "contract_results",
    "contract_disputes", "verifications", "verification_votes", "verification_rewards",
    "capability_bounties", "bounty_submissions", "bounty_rewards",
    "collectives", "workflows", "stake_slashes", "proposals", "votes",
    "governance_votes", "post_flags",
})
SHARED_COLS: frozenset[tuple[str, str]] = frozenset({
    ("capability_endorsements", "endorser_did"),     # an endorsement it gave
    ("rooms", "creator_did"),                        # a room others may be in
})


class RemoveRefused(Exception):
    """Nothing was changed. `problems` lists every reason found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass
class Removal:
    agent_did: str
    agent_id: str
    display_name: str
    role: str
    status: str
    created_at: object
    own: dict[str, int] = field(default_factory=dict)       # table.col -> rows deleted outright
    cascade: dict[str, int] = field(default_factory=dict)   # table.col -> rows the DB cascades
    unlinked: dict[str, int] = field(default_factory=dict)  # table.col -> rows set to NULL
    points: dict[str, int] = field(default_factory=dict)    # token_balances by type
    mentions: dict[str, int] = field(default_factory=dict)  # text cells still holding did/id
    problems: list[str] = field(default_factory=list)


@dataclass
class Report:
    removed: list[Removal] = field(default_factory=list)
    rows_removed: dict[str, int] = field(default_factory=dict)   # table -> net rows gone
    recounted_agents: int = 0
    recounted_posts: int = 0
    log_as: str = ""
    applied: bool = False


# ── Matching ──────────────────────────────────────────────────────────────────

def is_test_account(display_name: str | None) -> bool:
    """True only for the names this script may remove."""
    if not isinstance(display_name, str):
        return False
    return display_name in EXACT_NAMES or display_name.startswith(NAME_PREFIXES)


def founding_agent_lookalike(did: str, display_name: str) -> str | None:
    """The founder name *did* or *display_name* could be taken for, else None."""
    m = _DID.fullmatch(did or "")
    stem = m.group(1) if m else ""
    shown = (display_name or "").strip().lower()
    for name in FOUNDER_NAMES:
        if stem == name or stem.startswith(f"{name}-"):
            return name
        if shown == name or re.match(rf"^{name}[^a-z0-9]", shown):
            return name
    return None


_AGENT_COLS = ("agent_did, agent_id, display_name, governance_role::text AS role, "
               "status::text AS status, created_at")


async def matches(conn, dids: list[str] | None = None, lock: bool = False) -> list[dict]:
    """Every test account (or only the named ones, each of which must be one)."""
    rows = await conn.fetch(
        f"""
        SELECT {_AGENT_COLS} FROM agents
        WHERE display_name = ANY($1::text[])
           OR display_name LIKE 'canary-%' OR display_name LIKE 'sdk-canary-%'
           OR display_name LIKE 'Prod Smoke %'
        ORDER BY created_at, agent_did
        {"FOR UPDATE" if lock else ""}
        """,
        sorted(EXACT_NAMES),
    )
    found = [dict(r) for r in rows if is_test_account(r["display_name"])]
    if dids is None:
        return found
    by_did = {r["agent_did"]: r for r in found}
    problems = []
    for did in dids:
        if did not in by_did:
            row = await conn.fetchrow("SELECT display_name FROM agents WHERE agent_did = $1", did)
            if row is None:
                problems.append(f"{did}: no agent has this address")
            else:
                problems.append(f"{did} is shown as {row['display_name']!r}, not a test account")
    if problems:
        raise RemoveRefused(problems)
    return [by_did[d] for d in dict.fromkeys(dids)]


# ── What the database looks like ──────────────────────────────────────────────

def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _n(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])


async def _foreign_keys(conn) -> list[tuple[str, str, str, str]]:
    """Every foreign key to agents: (table, column, delete rule, referenced column)."""
    rows = await conn.fetch(
        """
        SELECT c.conrelid::regclass::text AS tbl, a.attname AS col,
               c.confdeltype::text AS rule, af.attname AS refcol
        FROM pg_constraint c
        JOIN pg_attribute a  ON a.attrelid = c.conrelid  AND a.attnum  = ANY(c.conkey)
        JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = ANY(c.confkey)
        WHERE c.contype = 'f' AND c.confrelid = 'public.agents'::regclass
          AND array_length(c.conkey, 1) = 1
        ORDER BY 1, 2
        """
    )
    return [(r["tbl"].removeprefix("public."), r["col"], r["rule"], r["refcol"]) for r in rows]


async def _tables(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
        "AND relkind IN ('r', 'p') ORDER BY relname")
    return [r["relname"] for r in rows]


async def _row_counts(conn, tables: list[str]) -> dict[str, int]:
    return {t: await conn.fetchval(f"SELECT count(*) FROM {_q(t)}") for t in tables}


async def _identity_columns(conn) -> dict[str, dict[str, list[tuple[str, bool]]]]:
    """Every text and uuid column (and array of them) of every public table."""
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


async def _mentions(conn, cols, did: str, agent_id) -> dict[str, int]:
    """Every table.column that still holds this agent's DID or id."""
    found: dict[str, int] = {}
    for kind, value in (("did", did), ("uuid", agent_id)):
        for table, tcols in cols[kind].items():
            parts = [
                f"count(*) FILTER (WHERE $1 = ANY({_q(c)}))" if arr
                else f"count(*) FILTER (WHERE {_q(c)} = $1)"
                for c, arr in tcols
            ]
            row = await conn.fetchrow(f"SELECT {', '.join(parts)} FROM {_q(table)}", value)
            for i, (c, _) in enumerate(tcols):
                if row[i]:
                    found[f"{table}.{c}"] = row[i]
    return found


async def _preflight(conn) -> None:
    """Refuse a login that row-level security hides rows from (as dedupe_founders)."""
    hidden = await conn.fetch(
        """
        SELECT c.relname FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relrowsecurity
          AND (c.relforcerowsecurity OR NOT pg_has_role(current_user, c.relowner, 'USAGE'))
          AND NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user)
        """
    )
    if hidden:
        raise RemoveRefused([
            "this database login cannot see every row (row-level security on "
            + ", ".join(sorted(r["relname"] for r in hidden)) + "); run as the database owner"
        ])


# ── One agent ─────────────────────────────────────────────────────────────────

async def _inspect(conn, row: dict, fks, removal_dids: set[str], removal_ids: set) -> Removal:
    """Everything the agent owns and every reason it cannot be removed."""
    did, aid, name = row["agent_did"], row["agent_id"], row["display_name"]
    r = Removal(did, str(aid), name, row["role"], row["status"], row["created_at"])
    p = r.problems

    look = founding_agent_lookalike(did, name)
    if look:
        p.append(f"is, or looks like, the founding agent {look.upper()}")
    if r.role not in SAFE_ROLES:
        p.append(f"role is {r.role}; only MEMBER or OBSERVER accounts can be removed")

    # 3. tokens
    for w in await conn.fetch("SELECT wallet_id, balance FROM wallets WHERE agent_id = $1", aid):
        if w["balance"]:
            p.append(f"wallet holds {w['balance']} tokens")
        ledger = await conn.fetchval(
            "SELECT count(*) FROM transactions WHERE from_wallet = $1 OR to_wallet = $1",
            w["wallet_id"])
        if ledger:
            p.append(f"wallet has {ledger} ledger line(s) in transactions")
    for b in await conn.fetch(
            "SELECT token_type::text AS t, balance FROM token_balances WHERE agent_did = $1", did):
        r.points[b["t"]] = b["balance"]
        if b["t"] == "WORK" and 0 <= b["balance"] <= WELCOME_BONUS:
            continue
        if b["balance"]:
            p.append(f"holds {b['balance']} {b['t']} points")
    unreleased = await conn.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE agent_id = $1 AND released_at IS NULL",
        aid)
    if unreleased:
        p.append(f"has {unreleased} tokens staked and not released")

    # 4. token ledger lines with an agent that stays
    other = await conn.fetch(
        """
        SELECT CASE WHEN from_did = $1 THEN to_did ELSE from_did END AS other, count(*) AS n
        FROM token_transactions WHERE from_did = $1 OR to_did = $1 GROUP BY 1
        """, did)
    for o in other:
        if o["other"] is not None and o["other"] not in removal_dids:
            p.append(f"{o['n']} token ledger line(s) with {o['other']}, who stays")

    # 5./7. every foreign key to agents
    for table, col, rule, refcol in fks:
        value = did if refcol == "agent_did" else aid
        n = await conn.fetchval(f"SELECT count(*) FROM {_q(table)} WHERE {_q(col)} = $1", value)
        if not n:
            continue
        key = f"{table}.{col}"
        if table in SHARED_TABLES or (table, col) in SHARED_COLS:
            p.append(f"{n} row(s) in {key} (shared record; the script will not delete it)")
        elif (table, col) in OWN:
            r.own[key] = n
        elif rule == "c":
            r.cascade[key] = n
        elif rule == "n":
            r.unlinked[key] = n
        else:
            p.append(f"{n} row(s) in {key} and no rule for that table (not deleted)")

    # 6. what agents that stay wrote or decided on this agent's content. Its
    # posts and comments are deleted outright, which would cascade to these.
    mine = "(p.author_did = $1 OR p.agent_id = $2::uuid OR p.creator_agent_id = $2::uuid)"
    dids_, ids_ = sorted(removal_dids), list(removal_ids)
    stays = "NOT (COALESCE({a}, '') = ANY($3::text[]))"
    for label, sql, args in (
        ("reply(ies) to its posts",
         f"SELECT COALESCE(r.author_did, r.agent_id::text) AS who, count(*) AS n FROM posts r "
         f"JOIN posts p ON r.parent_post_id = p.post_id WHERE {mine} "
         f"AND {stays.format(a='r.author_did')} "
         f"AND NOT (COALESCE(r.agent_id, $2::uuid) = ANY($4::uuid[])) GROUP BY 1",
         (did, aid, dids_, ids_ + [aid])),
        ("comment(s) on its posts",
         f"SELECT c.author_did AS who, count(*) AS n FROM comments c "
         f"JOIN threads t ON c.thread_id = t.thread_id JOIN posts p ON t.post_id = p.post_id "
         f"WHERE {mine} AND c.author_did IS NOT NULL AND {stays.format(a='c.author_did')} "
         "GROUP BY 1",
         (did, aid, dids_)),
        ("reply(ies) to its comments",
         "SELECT c.author_did AS who, count(*) AS n FROM comments c "
         "JOIN comments m ON c.parent_comment_id = m.comment_id "
         "WHERE m.author_did = $1 AND c.author_did IS NOT NULL "
         "AND NOT (c.author_did = ANY($2::text[])) GROUP BY 1",
         (did, dids_)),
        ("vote(s) on its posts",
         f"SELECT v.voter_did AS who, count(*) AS n FROM votes v "
         f"JOIN posts p ON v.post_id = p.post_id WHERE {mine} "
         f"AND {stays.format(a='v.voter_did')} GROUP BY 1",
         (did, aid, dids_)),
    ):
        for x in await conn.fetch(sql, *args):
            p.append(f"{x['n']} {label} by {x['who']}, who stays")
    for table in ("debate_rounds", "consensus_snapshots"):
        n = await conn.fetchval(
            f"SELECT count(*) FROM {table} d JOIN posts p ON d.proposal_id = p.post_id WHERE {mine}",
            did, aid)
        if n:
            p.append(f"{n} row(s) in {table} on its proposal(s) (shared record)")
    return r


async def _linked_counters(conn, dids: list[str], ids: list) -> tuple[list[str], list]:
    """Agents and posts that stay whose stored counters involve these agents."""
    agents = await conn.fetch(
        """
        SELECT following_did AS did FROM follows
        WHERE follower_did = ANY($1::text[]) AND NOT (following_did = ANY($1::text[]))
        UNION
        SELECT follower_did FROM follows
        WHERE following_did = ANY($1::text[]) AND NOT (follower_did = ANY($1::text[]))
        """, dids)
    posts = await conn.fetch(
        """
        SELECT p.post_id FROM posts p
        WHERE NOT (p.author_did = ANY($1::text[]))
          AND NOT (p.agent_id = ANY($2::uuid[])) AND NOT (p.creator_agent_id = ANY($2::uuid[]))
          AND (EXISTS (SELECT 1 FROM post_likes l WHERE l.post_id = p.post_id
                         AND l.agent_did = ANY($1::text[]))
            OR EXISTS (SELECT 1 FROM posts r WHERE r.parent_post_id = p.post_id
                         AND (r.author_did = ANY($1::text[]) OR r.agent_id = ANY($2::uuid[])
                              OR r.creator_agent_id = ANY($2::uuid[]))))
        """, dids, ids)
    return [a["did"] for a in agents], [x["post_id"] for x in posts]


async def _recount(conn, agent_dids: list[str], post_ids: list) -> None:
    if agent_dids:
        await conn.execute(
            """
            UPDATE agents SET
              followers_count = (SELECT count(*) FROM follows WHERE following_did = agents.agent_did),
              following_count = (SELECT count(*) FROM follows WHERE follower_did = agents.agent_did)
            WHERE agent_did = ANY($1::text[])
            """, agent_dids)
    if post_ids:
        await conn.execute(
            """
            UPDATE posts SET
              like_count  = (SELECT count(*) FROM post_likes WHERE post_id = posts.post_id),
              reply_count = (SELECT count(*) FROM posts r WHERE r.parent_post_id = posts.post_id)
            WHERE post_id = ANY($1::uuid[])
            """, post_ids)


# ── The transaction ───────────────────────────────────────────────────────────

async def _run(conn, apply: bool, work) -> Report:
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
    """Every test account with what it owns (reads only; nothing is locked)."""
    out = []
    for row in await matches(conn):
        did, aid = row["agent_did"], row["agent_id"]
        out.append({
            **row,
            "posts": await conn.fetchval(
                "SELECT count(*) FROM posts WHERE author_did = $1 OR agent_id = $2", did, aid),
            "wallet": await conn.fetchval(
                "SELECT COALESCE(SUM(balance), 0) FROM wallets WHERE agent_id = $1", aid),
            "points": {b["t"]: b["balance"] for b in await conn.fetch(
                "SELECT token_type::text AS t, balance FROM token_balances WHERE agent_did = $1",
                did)},
        })
    return out


async def _default_log_as(conn) -> str:
    """The first founding agent in the database, Atlas first."""
    did = await conn.fetchval(
        "SELECT agent_did FROM agents WHERE agent_did = ANY($1::text[]) "
        "ORDER BY array_position($1::text[], agent_did) LIMIT 1", list(LOG_AS_CANDIDATES))
    if did is None:
        raise RemoveRefused([
            "no founding agent found to write the audit rows as; give one with --log-as"])
    return did


async def remove(conn, dids: list[str] | None = None, *, apply: bool = False,
                 max_count: int = DEFAULT_MAX, log_as: str | None = None,
                 by: str = DEFAULT_ACTOR) -> Report:
    """Remove every test account (or the named ones), or raise `RemoveRefused`."""
    if dids is not None:
        dids = list(dict.fromkeys(dids))
        if not dids:
            dids = None
    if not (isinstance(max_count, int) and 0 < max_count):
        raise RemoveRefused(["--max must be a positive number"])

    async def work() -> Report:
        await _preflight(conn)
        targets = await matches(conn, dids, lock=True)
        log_as_did = log_as if log_as is not None else await _default_log_as(conn)
        report = Report(log_as=log_as_did, applied=apply)
        if not targets:
            return report
        if dids is None and len(targets) > max_count:
            raise RemoveRefused([
                f"{len(targets)} test accounts match, more than --max {max_count}; "
                "name the ones to remove with --did, or raise --max"])
        removal_dids = {t["agent_did"] for t in targets}
        removal_ids = {t["agent_id"] for t in targets}
        if log_as_did in removal_dids:
            raise RemoveRefused([f"--log-as {log_as_did} is itself being removed"])
        if not _DID.fullmatch(log_as_did or "") or not await conn.fetchval(
                "SELECT 1 FROM agents WHERE agent_did = $1", log_as_did):
            raise RemoveRefused([
                f"--log-as {log_as_did!r} is not an existing agent; the audit row needs one that stays"])

        fks = await _foreign_keys(conn)
        tables = await _tables(conn)
        cols = await _identity_columns(conn)
        before = await _row_counts(conn, tables)
        all_before = {r["agent_did"] for r in await conn.fetch("SELECT agent_did FROM agents")}
        staying = all_before - removal_dids

        problems: list[str] = []
        for t in targets:
            r = await _inspect(conn, t, fks, removal_dids, removal_ids)
            report.removed.append(r)
            problems += [f"{r.agent_did} ({r.display_name!r}): {x}" for x in r.problems]
        if problems:
            raise RemoveRefused(problems)

        did_list, id_list = sorted(removal_dids), list(removal_ids)
        linked_agents, linked_posts = await _linked_counters(conn, did_list, id_list)

        # The agents' own rows first (the database would refuse the delete
        # otherwise), one statement per table over all its keys, so a reply
        # between removed agents goes in the same statement as its parent.
        own_tables: dict[str, list[tuple[str, str]]] = {}
        for table, col, rule, refcol in fks:
            if (table, col) in OWN:
                own_tables.setdefault(table, []).append((col, refcol))
        for table, keys in own_tables.items():
            args, conds = [], []
            for col, refcol in keys:
                value, cast = (did_list, "text") if refcol == "agent_did" else (id_list, "uuid")
                args.append(value)
                conds.append(f"{_q(col)} = ANY(${len(args)}::{cast}[])")
            await conn.execute(f"DELETE FROM {_q(table)} WHERE {' OR '.join(conds)}", *args)
        gone = _n(await conn.execute(
            "DELETE FROM agents WHERE agent_did = ANY($1::text[])", did_list))
        if gone != len(targets):
            raise RemoveRefused([f"expected to delete {len(targets)} agents, the database said {gone}"])
        all_after = {r["agent_did"] for r in await conn.fetch("SELECT agent_did FROM agents")}
        if all_after != staying:
            raise RemoveRefused([
                f"agents changed beyond the targets: missing {sorted(staying - all_after)}, "
                f"extra {sorted(all_after - staying)}"])

        await _recount(conn, linked_agents, linked_posts)
        report.recounted_agents, report.recounted_posts = len(linked_agents), len(linked_posts)

        after = await _row_counts(conn, tables)
        report.rows_removed = {
            t: before[t] - after[t] for t in tables if before[t] != after[t]}
        for r in report.removed:
            r.mentions = await _mentions(conn, cols, r.agent_did, r.agent_id)
            await conn.execute(
                "INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details) "
                "VALUES ($1, 'DELETE', 'agent', $2, $3)",
                log_as_did, r.agent_did,
                json.dumps({
                    "why": "scripts/remove_test_accounts.py (Sprint 13 T-5, H25)",
                    "by": by,
                    "agent_id": r.agent_id,
                    "display_name": r.display_name,
                    "role": r.role,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "own_rows": r.own,
                    "cascaded": r.cascade,
                    "unlinked": r.unlinked,
                    "points": r.points,
                    "mentions_left": r.mentions,
                }))
        return report

    return await _run(conn, apply, work)


# ── Command line ──────────────────────────────────────────────────────────────

def _counts(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "none"


def render(report: Report) -> str:
    if not report.removed:
        return "No test accounts found; nothing to remove."
    lines = [f"Test accounts to remove: {len(report.removed)}"]
    for r in report.removed:
        lines.append(f"  {r.agent_did}  {r.display_name!r}  {r.role} {r.status}  "
                     f"signed up {r.created_at:%Y-%m-%d}")
        lines.append(f"      own rows deleted: {_counts(r.own)}")
        lines.append(f"      cascaded by the database: {_counts(r.cascade)}")
        if r.unlinked:
            lines.append(f"      links cut (kept, creator set to NULL): {_counts(r.unlinked)}")
        if r.points:
            lines.append(f"      sign-up points deleted: {_counts(r.points)}")
        if r.mentions:
            lines.append(f"      text mentions left (no link): {_counts(r.mentions)}")
    lines.append("Rows removed per table (net, audit rows included): "
                 + _counts(report.rows_removed))
    lines.append(f"Counters recounted: {report.recounted_agents} agent(s), "
                 f"{report.recounted_posts} post(s). Audit rows written as {report.log_as}.")
    if report.applied:
        lines.append(f"Written to the database: {len(report.removed)} test account(s) removed.")
    else:
        lines.append(f"DRY RUN: {len(report.removed)} test account(s) would be removed. "
                     "Nothing was changed; add --apply to write.")
    return "\n".join(lines)


async def _main(args) -> int:
    conn = None
    try:
        conn = await asyncpg.connect(args.dsn)
        if args.command == "show":
            rows = await show(conn)
            print(f"Test accounts: {len(rows)}")
            for a in rows:
                print(f"  {a['agent_did']}  {a['display_name']!r}  {a['role']} {a['status']}  "
                      f"signed up {a['created_at']:%Y-%m-%d}  posts {a['posts']}  "
                      f"wallet {a['wallet']}  points {_counts(a['points'])}")
            return 0
        report = await remove(conn, args.did or None, apply=args.apply, max_count=args.max,
                              log_as=args.log_as, by=args.by)
        print(render(report))
        return 0
    except RemoveRefused as exc:
        print("REFUSED, nothing was changed:", file=sys.stderr)
        for p in exc.problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    except (asyncpg.PostgresError, OSError) as exc:
        print(f"STOPPED, nothing was changed: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="Postgres connection string")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="list the test accounts (reads only)")
    c = sub.add_parser("remove", help="remove the test accounts (dry run without --apply)")
    c.add_argument("--did", action="append", default=[],
                   help="remove only this agent (repeatable); it must be a test account")
    c.add_argument("--max", type=int, default=DEFAULT_MAX,
                   help=f"refuse more matches than this unless named (default {DEFAULT_MAX})")
    c.add_argument("--log-as", default=None,
                   help="existing agent the audit rows are written as "
                        "(default: the first founding agent found, Atlas first)")
    c.add_argument("--by", default=DEFAULT_ACTOR, help="who is acting (logged)")
    c.add_argument("--apply", action="store_true")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
