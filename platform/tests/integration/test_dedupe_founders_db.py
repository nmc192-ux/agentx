"""
Integration tests: scripts/dedupe_founders.py against REAL local Postgres.
Sprint 9, S9-10.

Each test makes its own "founder" (a random name) in the shape production
has: the same persona registered several times by a seed script
(``<name>-seed-001``, ``<name>-002``, ``<name>-003``), renamed by migration
038 (``Name``, ``Name_-002``, ``Name_-003``).

What is proven:
  • a dry run changes nothing and reports what --apply then does
  • one row is left; it is ``<name>-001`` when that exists, else the oldest;
    its suffixed display name is put back
  • everything the duplicates own ends up on the kept row: posts, follows,
    likes, messages, notifications, trust events, capabilities, endorsements;
    no cell in the database still holds a duplicate's DID or id
  • a relation the kept row already has is dropped once, and the stored
    counters (followers, following, posts, likes) are right afterwards
  • tokens: point balances and wallets are added together, ledger lines and
    stakes move, the total number of tokens is unchanged
  • a role is never inherited from a duplicate; a created founder is a MEMBER
  • look-alikes (name only, DID only), excluded rows and rows that are not
    ACTIVE are left alone
  • a clash in a table the script may not choose in (a vote) stops the run
    with nothing changed, even with --apply
  • a database login that row-level security hides rows from is refused
  • a missing founder is created once; a second run is a no-op
  • the eight real founders of a fresh database are already one row each,
    under the DIDs the runners use
  • the command line runs end to end

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from .conftest import PG_PORT, PG_USER, smoke
from .support import total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dedupe_founders.py"
_spec = importlib.util.spec_from_file_location("dedupe_founders", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["dedupe_founders"] = mod      # dataclasses look the module up by name
_spec.loader.exec_module(mod)

SPEC = {"agent_type": "AUTONOMOUS", "specialization": "qa.testing.advanced", "bio": "Test founder"}


def _name() -> str:
    return "f" + uuid4().hex[:9]


async def _row(pool, did: str, display: str, days_old: int, *, role: str = "MEMBER",
               status: str = "ACTIVE"):
    return await pool.fetchrow(
        """
        INSERT INTO agents (agent_did, display_name, governance_role, status, created_at)
        VALUES ($1, $2, $3::governance_role, $4::agent_status, NOW() - make_interval(days => $5))
        RETURNING agent_did, agent_id
        """,
        did, display, role, status, days_old,
    )


async def _cohorts(pool, name: str):
    """The production shape: three registrations of one persona, after 038."""
    title = name.capitalize()
    old = await _row(pool, f"did:agentx:{name}-seed-001", title, 30)
    two = await _row(pool, f"did:agentx:{name}-002", f"{title}_-002", 20)
    three = await _row(pool, f"did:agentx:{name}-003", f"{title}_-003", 10)
    return old, two, three


async def _post(pool, author_did: str, parent=None):
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, parent_post_id) "
        "VALUES ($1, 'UPDATE', 'Update', $2, $3) RETURNING post_id",
        author_did, f"post {uuid4().hex}", parent,
    )


async def _follow(pool, follower: str, following: str) -> None:
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)", follower, following)


async def _cells_holding(pool, value) -> set[str]:
    """Every table.column holding *value*; written apart from the script's own scan."""
    kind = ("uuid",) if not isinstance(value, str) else ("text", "character varying")
    found = set()
    for r in await pool.fetch(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c "
        "JOIN information_schema.tables t USING (table_schema, table_name) "
        "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
        "AND c.data_type = ANY($1::text[])", list(kind),
    ):
        if await pool.fetchval(
            f'SELECT EXISTS (SELECT 1 FROM "{r["table_name"]}" WHERE "{r["column_name"]}" = $1)',
            value,
        ):
            found.add(f'{r["table_name"]}.{r["column_name"]}')
    return found


_FINGERPRINTED = ("agents", "posts", "follows", "post_likes", "token_balances", "wallets",
                  "transactions", "stakes", "votes", "audit_logs", "agent_trust_breakdown")


async def _fingerprint(pool) -> dict[str, str]:
    return {
        t: await pool.fetchval(f"SELECT md5(COALESCE(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x")
        for t in _FINGERPRINTED
    }


async def _run(pool, name: str, **kwargs):
    kwargs.setdefault("founders", {name: SPEC})
    async with pool.acquire() as conn:
        report = await mod.run(conn, **kwargs)
    return {f.name: f for f in report}


async def _dids(pool, name: str) -> list[str]:
    return [r["agent_did"] for r in await pool.fetch(
        "SELECT agent_did FROM agents WHERE agent_did LIKE $1 ORDER BY 1", f"did:agentx:{name}-%")]


# ── The merge ─────────────────────────────────────────────────────────────────

async def _busy_cohorts(pool, agents, name: str):
    """Three registrations that each did things, some of them the same things."""
    old, two, three = await _cohorts(pool, name)
    x, y = await agents("xavier"), await agents("yolanda")
    x_post, y_post = await _post(pool, x.did), await _post(pool, y.did)

    await _post(pool, old["agent_did"])
    await _post(pool, two["agent_did"])
    await _post(pool, two["agent_did"])
    await _post(pool, two["agent_did"], parent=x_post)          # a reply: not counted
    await _post(pool, three["agent_did"])
    await pool.execute("UPDATE agents SET posts_count = 1 WHERE agent_did = $1", old["agent_did"])

    await _follow(pool, x.did, two["agent_did"])                # moves
    await _follow(pool, y.did, three["agent_did"])              # moves
    await _follow(pool, two["agent_did"], y.did)                # clash with the next one
    await _follow(pool, old["agent_did"], y.did)
    await _follow(pool, three["agent_did"], old["agent_did"])   # would follow itself

    for did, post in ((old["agent_did"], x_post), (two["agent_did"], x_post),
                      (three["agent_did"], y_post)):
        await pool.execute("INSERT INTO post_likes (post_id, agent_did) VALUES ($1, $2)", post, did)

    await pool.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message) VALUES ($1, $2, 'hi')",
        two["agent_did"], x.did)
    await pool.execute(
        "INSERT INTO notifications (to_did, from_did, notif_type) "
        "VALUES ($1, $2, (enum_range(NULL::notif_type))[1])", three["agent_did"], x.did)
    await pool.execute(
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_value, counterparty_did) "
        "VALUES ($1, $2, 'task_completed', 0.05, $3)", two["agent_id"], two["agent_did"], x.did)
    for r, points in ((old, 100), (two, 100), (three, 50)):
        await pool.execute(
            "INSERT INTO token_balances (agent_did, token_type, balance) VALUES ($1, 'REP', $2)",
            r["agent_did"], points)
        await pool.execute(
            "INSERT INTO agent_trust_breakdown (agent_did) VALUES ($1) ON CONFLICT DO NOTHING",
            r["agent_did"])
    await pool.execute(
        "INSERT INTO agent_capabilities (agent_did, capability_id) VALUES "
        "($1, 'infrastructure.docker.advanced'), ($2, 'infrastructure.docker.advanced'), "
        "($3, 'infrastructure.cicd.advanced')",
        old["agent_did"], two["agent_did"], three["agent_did"])
    await pool.execute(
        "INSERT INTO capability_endorsements (agent_did, capability_id, endorser_did) VALUES "
        "($1, 'infrastructure.cicd.advanced', $2), "        # x endorsed a duplicate: moves
        "($3, 'infrastructure.docker.advanced', $4)",       # a duplicate endorsed the kept row
        three["agent_did"], x.did, old["agent_did"], two["agent_did"])
    return old, two, three, x, y, x_post, y_post


async def test_dry_run_changes_nothing_and_reports_the_merge(pool, agents):
    name = _name()
    old, two, three, *_ = await _busy_cohorts(pool, agents, name)
    before = await _fingerprint(pool)

    f = (await _run(pool, name))[name]

    assert await _fingerprint(pool) == before
    assert f.canonical == old["agent_did"] and not f.created
    assert [m.did for m in f.merged] == [two["agent_did"], three["agent_did"]]
    assert "DRY RUN" in mod.render([f], apply=False)


async def test_everything_the_duplicates_own_moves_to_the_kept_row(pool, agents):
    name = _name()
    old, two, three, x, y, x_post, y_post = await _busy_cohorts(pool, agents, name)
    keep = old["agent_did"]

    f = (await _run(pool, name, apply=True))[name]

    # One row: the oldest (there is no <name>-001), under its own DID, id and name.
    assert await _dids(pool, name) == [keep]
    row = await pool.fetchrow("SELECT * FROM agents WHERE agent_did = $1", keep)
    assert row["agent_id"] == old["agent_id"] and row["display_name"] == name.capitalize()
    assert any("runners expect" in n for n in f.notes)

    # Nothing in the database names a duplicate any more (the audit record does, on purpose).
    for dup in (two, three):
        assert await _cells_holding(pool, dup["agent_did"]) <= {"audit_logs.resource_id"}
        assert await _cells_holding(pool, dup["agent_id"]) == set()

    # Posts: all five rows are the kept agent's; four are top-level.
    assert await pool.fetchval("SELECT count(*) FROM posts WHERE author_did = $1", keep) == 5
    assert row["posts_count"] == 4

    # Follows: x → keep, y → keep, keep → y once; never keep → keep.
    follows = {tuple(r) for r in await pool.fetch(
        "SELECT follower_did, following_did FROM follows "
        "WHERE follower_did = ANY($1::text[]) OR following_did = ANY($1::text[])",
        [keep, x.did, y.did])}
    assert follows == {(x.did, keep), (y.did, keep), (keep, y.did)}
    assert (row["followers_count"], row["following_count"]) == (2, 1)
    assert await pool.fetchval(
        "SELECT followers_count FROM agents WHERE agent_did = $1", y.did) == 1

    # Likes: two registrations liking one post is one like.
    assert await pool.fetchval("SELECT like_count FROM posts WHERE post_id = $1", x_post) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM post_likes WHERE agent_did = $1", keep) == 2

    # The rest moved as it was.
    assert await pool.fetchval(
        "SELECT count(*) FROM messages WHERE sender_agent_did = $1", keep) == 1
    assert await pool.fetchval("SELECT count(*) FROM notifications WHERE to_did = $1", keep) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM trust_events WHERE agent_id = $1 AND agent_did = $2",
        old["agent_id"], keep) == 1
    assert await pool.fetchval(
        "SELECT balance FROM token_balances WHERE agent_did = $1 AND token_type = 'REP'",
        keep) == 250

    # Capabilities: both of them, once; x's endorsement followed the capability;
    # the duplicate's endorsement of the kept row would be self-praise and is gone.
    assert {r["capability_id"] for r in await pool.fetch(
        "SELECT capability_id FROM agent_capabilities WHERE agent_did = $1", keep)} == {
        "infrastructure.docker.advanced", "infrastructure.cicd.advanced"}
    assert [tuple(r) for r in await pool.fetch(
        "SELECT capability_id, endorser_did FROM capability_endorsements WHERE agent_did = $1",
        keep)] == [("infrastructure.cicd.advanced", x.did)]

    # What was dropped is reported, and each merge is on record.
    dropped = {k for m in f.merged for k in m.dropped}
    assert {"follows.follower_did", "post_likes.agent_did", "agent_trust_breakdown.agent_did",
            "capability_endorsements.endorser_did"} <= dropped
    assert {r["resource_id"] for r in await pool.fetch(
        "SELECT resource_id FROM audit_logs WHERE agent_did = $1 AND resource_type = 'agent'",
        keep)} == {two["agent_did"], three["agent_did"]}

    # A second run has nothing to do.
    before = await _fingerprint(pool)
    again = (await _run(pool, name, apply=True))[name]
    assert again.merged == [] and not again.created
    assert await _fingerprint(pool) == before


async def test_the_runner_did_is_kept_when_it_exists_and_gets_the_bare_name_back(pool):
    name = _name()
    title = name.capitalize()
    old = await _row(pool, f"did:agentx:{name}-seed-001", title, 30)
    runner = await _row(pool, mod.canonical_did(name), f"{title}_-001", 5)
    await _post(pool, old["agent_did"])

    f = (await _run(pool, name, apply=True))[name]

    assert await _dids(pool, name) == [runner["agent_did"]]
    assert f.canonical == runner["agent_did"] and f.notes == []
    assert await pool.fetchval(
        "SELECT display_name FROM agents WHERE agent_did = $1", runner["agent_did"]) == title
    assert await pool.fetchval(
        "SELECT posts_count FROM agents WHERE agent_did = $1", runner["agent_did"]) == 1


# ── Tokens ────────────────────────────────────────────────────────────────────

async def test_two_wallets_become_one_and_no_token_is_made_or_lost(pool, agents):
    name = _name()
    old, two, _ = await _cohorts(pool, name)
    x = await agents("xavier", balance=10)
    for r, tokens in ((old, 300), (two, 200)):
        await pool.execute(
            "INSERT INTO wallets (agent_id, balance) VALUES ($1, $2)", r["agent_id"], tokens)
    dup_wallet = await pool.fetchval(
        "SELECT wallet_id FROM wallets WHERE agent_id = $1", two["agent_id"])
    x_wallet = await pool.fetchval("SELECT wallet_id FROM wallets WHERE agent_id = $1", x.agent_id)
    tx = await pool.fetchval(
        "INSERT INTO transactions (from_wallet, to_wallet, amount, type) "
        "VALUES ($1, $2, 10, 'transfer') RETURNING transaction_id", dup_wallet, x_wallet)
    stake = await pool.fetchval(
        "INSERT INTO stakes (agent_id, amount) VALUES ($1, 40) RETURNING stake_id",
        two["agent_id"])
    total = await total_tokens(pool)

    await _run(pool, name, apply=True)

    keep_wallet = await pool.fetchrow(
        "SELECT wallet_id, balance FROM wallets WHERE agent_id = $1", old["agent_id"])
    assert keep_wallet["balance"] == 500
    assert await pool.fetchval("SELECT count(*) FROM wallets WHERE wallet_id = $1", dup_wallet) == 0
    assert await pool.fetchval(
        "SELECT from_wallet FROM transactions WHERE transaction_id = $1", tx,
    ) == keep_wallet["wallet_id"]
    assert await pool.fetchval(
        "SELECT agent_id FROM stakes WHERE stake_id = $1", stake) == old["agent_id"]
    assert await total_tokens(pool) == total


async def test_a_duplicates_only_wallet_is_handed_over_whole(pool):
    name = _name()
    old, two, _ = await _cohorts(pool, name)
    wallet = await pool.fetchval(
        "INSERT INTO wallets (agent_id, balance) VALUES ($1, 70) RETURNING wallet_id",
        two["agent_id"])
    total = await total_tokens(pool)

    await _run(pool, name, apply=True)

    assert tuple(await pool.fetchrow(
        "SELECT wallet_id, balance FROM wallets WHERE agent_id = $1", old["agent_id"],
    )) == (wallet, 70)
    assert await total_tokens(pool) == total


# ── Fails closed ──────────────────────────────────────────────────────────────

async def test_a_role_is_never_inherited_from_a_duplicate(pool):
    name = _name()
    title = name.capitalize()
    old = await _row(pool, f"did:agentx:{name}-seed-001", title, 30)
    await _row(pool, f"did:agentx:{name}-002", f"{title}_-002", 1, role="FOUNDER")

    await _run(pool, name, apply=True)

    assert [tuple(r) for r in await pool.fetch(
        "SELECT agent_did, governance_role::text FROM agents WHERE agent_did LIKE $1",
        f"did:agentx:{name}-%")] == [(old["agent_did"], "MEMBER")]


async def test_look_alikes_are_reported_and_never_touched(pool):
    name = _name()
    title = name.capitalize()
    old, two, _ = await _cohorts(pool, name)
    by_name = await _row(pool, f"did:agentx:{name}-fan-123", f"{title}_abcd", 3)
    by_did = await _row(pool, f"did:agentx:{name}-004", f"someone-{uuid4().hex[:8]}", 3)
    await _post(pool, by_name["agent_did"])
    await _post(pool, by_did["agent_did"])

    f = (await _run(pool, name, apply=True))[name]

    assert await _dids(pool, name) == sorted(
        [old["agent_did"], by_name["agent_did"], by_did["agent_did"]])
    assert {did for did, _ in f.left_alone} == {by_name["agent_did"], by_did["agent_did"]}
    for r in (by_name, by_did):
        assert await pool.fetchval(
            "SELECT count(*) FROM posts WHERE author_did = $1", r["agent_did"]) == 1


async def test_excluded_and_inactive_rows_are_left_alone(pool):
    name = _name()
    old, two, three = await _cohorts(pool, name)
    await pool.execute(
        "UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", three["agent_did"])

    f = (await _run(pool, name, apply=True, exclude=frozenset({two["agent_did"]})))[name]
    assert f.merged == []
    assert await _dids(pool, name) == sorted(r["agent_did"] for r in (old, two, three))
    assert {did for did, _ in f.left_alone} == {two["agent_did"], three["agent_did"]}

    f = (await _run(pool, name, apply=True, include_inactive=True))[name]
    assert {m.did for m in f.merged} == {two["agent_did"], three["agent_did"]}
    assert await _dids(pool, name) == [old["agent_did"]]


async def test_a_clash_the_script_may_not_settle_stops_the_run_with_nothing_changed(pool, agents):
    """Both registrations voted on one post. Which vote stands is not for a
    cleanup script to decide: the whole run stops, --apply or not."""
    name, other = _name(), _name()
    old, two, _ = await _cohorts(pool, name)
    await _cohorts(pool, other)                         # a clean merge in the same run
    x = await agents("xavier")
    post = await _post(pool, x.did)
    for r, choice in ((old, "FOR"), (two, "AGAINST")):
        await pool.execute(
            "INSERT INTO votes (post_id, voter_did, choice) VALUES ($1, $2, $3::vote_choice)",
            post, r["agent_did"], choice)
    before = await _fingerprint(pool)

    with pytest.raises(mod.DedupeError, match="votes.voter_did"):
        await _run(pool, name, apply=True, founders={other: SPEC, name: SPEC})

    assert await _fingerprint(pool) == before
    assert len(await _dids(pool, other)) == 3           # the clean merge was undone too


async def test_a_login_that_row_security_hides_rows_from_is_refused(pool):
    """Such a login would not see a duplicate's rows in the protected tables,
    and deleting the duplicate would then cascade over them unseen."""
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("CREATE ROLE dedupe_probe_not_owner")
            await conn.execute("SET LOCAL ROLE dedupe_probe_not_owner")
            with pytest.raises(mod.DedupeError, match="row-level security"):
                await mod._preflight(conn)
        finally:
            await tr.rollback()          # the role goes with it
        await mod._preflight(conn)       # the owner is fine


# ── Creating a founder that has no row ────────────────────────────────────────

async def test_a_missing_founder_is_created_once_as_a_member(pool):
    name, sibling = _name(), _name()
    await _row(pool, f"did:agentx:{sibling}-seed-001", sibling.capitalize(), 30)
    founders = {name: SPEC, sibling: SPEC}

    assert (await _run(pool, name, apply=True, founders=founders, create=False))[name].canonical is None
    assert (await _run(pool, name, apply=True, founders={name: {}}))[name].canonical is None
    assert await _dids(pool, name) == []

    f = (await _run(pool, name, apply=True, founders=founders))[name]

    assert f.created and f.canonical == mod.canonical_did(name)
    row = await pool.fetchrow(
        "SELECT display_name, governance_role::text AS role, status::text AS status, "
        "tier::text AS tier, bio, trust_score FROM agents WHERE agent_did = $1", f.canonical)
    # Spelled like the founders already there ("Nova" → "Bruno"); least privilege.
    assert (row["display_name"], row["role"], row["status"], row["tier"]) == (
        name.capitalize(), "MEMBER", "ACTIVE", "BOOTSTRAP")
    assert row["bio"] == SPEC["bio"] and float(row["trust_score"]) == 0.44
    assert await pool.fetchval(
        "SELECT count(*) FROM agent_trust_breakdown WHERE agent_did = $1", f.canonical) == 1

    before = await _fingerprint(pool)
    again = (await _run(pool, name, apply=True, founders=founders))[name]
    assert not again.created and again.canonical == f.canonical
    assert await _fingerprint(pool) == before


async def test_a_founder_is_not_created_over_a_look_alike_holding_the_name(pool):
    name = _name()
    squatter = await _row(pool, f"did:agentx:{name}-fan-123", name.upper(), 3)

    f = (await _run(pool, name, apply=True))[name]

    assert not f.created and f.canonical is None
    assert await _dids(pool, name) == [squatter["agent_did"]]
    assert any("not created" in n for n in f.notes)


# ── The real founders ─────────────────────────────────────────────────────────

async def test_a_fresh_database_has_the_eight_founders_once_under_the_runner_dids(pool):
    """init-db.sql seeds the same DIDs the runners register, so there is
    nothing to merge, nothing to create and nothing to note."""
    before = await _fingerprint(pool)
    async with pool.acquire() as conn:
        report = await mod.run(conn, apply=True)

    assert [f.name for f in report] == sorted(mod.FOUNDERS) and len(report) == 8
    for f in report:
        assert f.canonical == mod.canonical_did(f.name), f
        assert (f.created, f.merged, f.notes) == (False, [], []), f
    assert await _fingerprint(pool) == before


# ── Command line ──────────────────────────────────────────────────────────────

async def test_command_line_end_to_end(pool, escrow_db):
    name = _name()
    old, two, three = await _cohorts(pool, name)
    dsn = f"postgresql://{PG_USER}@{smoke.DB_HOST}:{PG_PORT}/{escrow_db}"

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--dsn", dsn, "--extra-name", name, *argv],
            capture_output=True, text=True, timeout=120,
        )

    out = run()
    assert out.returncode == 0, out.stderr
    assert f"MERGE {two['agent_did']}" in out.stdout and "DRY RUN" in out.stdout
    assert len(await _dids(pool, name)) == 3

    out = run("--exclude", three["agent_did"], "--apply")
    assert out.returncode == 0, out.stderr
    assert "Written to the database" in out.stdout
    assert await _dids(pool, name) == sorted([old["agent_did"], three["agent_did"]])
