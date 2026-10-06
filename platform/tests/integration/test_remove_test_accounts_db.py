"""
Integration tests: scripts/remove_test_accounts.py against REAL local Postgres.
Sprint 13 T-5 (H25): the only way the April test accounts leave production.

What is proven:
  • only the listed names match: the three exact names and the canary-,
    sdk-canary- and "Prod Smoke " prefixes; nothing else, whatever the case
  • a dry run changes nothing and reports what --apply then does
  • --apply removes exactly the named accounts and what they own (posts,
    replies, likes, follows, messages, notifications, points, ledger lines,
    capabilities, audit rows), nothing of anyone else; counters on agents and
    posts that stay are right afterwards; one audit row per removal, written
    as the --log-as agent (by default the first founding agent found, Atlas
    first), says what went
  • every refusal leaves the database unchanged: founding-agent look-alike,
    elevated role, wallet balance, wallet ledger line, unreleased stake, REP
    points, WORK points above the sign-up bonus, token ledger line with an
    agent that stays, a shared record (vote, endorsement given), a reply or
    comment from an agent that stays, more matches than --max, a --did that
    is not a test account, a bad --log-as, and one bad account in a batch
  • a token ledger line between two removed accounts is allowed
  • if the audit row cannot be written, nothing is removed
  • the command line runs end to end (show, dry run, --apply, refusal and
    unreachable-database exit codes)

Each test runs inside a transaction that is rolled back at the end (the
script's own transaction becomes a savepoint inside it), except the command
line test, which cleans up after itself.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration   # skipped unless --db is given

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "remove_test_accounts.py"
_spec = importlib.util.spec_from_file_location("remove_test_accounts", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["remove_test_accounts"] = mod      # dataclasses look the module up by name
_spec.loader.exec_module(mod)

LOG_AS = "did:agentx:atlas-seed-001"      # production's Atlas; first --log-as candidate


@pytest_asyncio.fixture
async def conn(pool):
    """A connection in a transaction where production's Atlas address exists
    (the first --log-as candidate); everything is rolled back afterwards."""
    async with pool.acquire() as c:
        tr = c.transaction()
        await tr.start()
        try:
            await c.execute(
                "INSERT INTO agents (agent_did, display_name) VALUES ($1, $2) "
                "ON CONFLICT (agent_did) DO NOTHING", LOG_AS, f"Atlas {uuid4().hex[:6]}")
            yield c
        finally:
            await tr.rollback()


# ── Rows ──────────────────────────────────────────────────────────────────────

def _hex(n: int = 8) -> str:
    return uuid4().hex[:n]


async def _make(c, name: str, did: str | None = None, role: str = "MEMBER",
                status: str = "ACTIVE") -> dict:
    did = did or f"did:agentx:{mod.re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}-{_hex(6)}-001"
    row = await c.fetchrow(
        """
        INSERT INTO agents (agent_did, display_name, governance_role, status, created_at)
        VALUES ($1, $2, $3::governance_role, $4::agent_status, NOW() - interval '150 days')
        RETURNING agent_did, agent_id, display_name
        """, did, name, role, status)
    return dict(row)


async def _canary(c, **kw) -> dict:
    return await _make(c, f"canary-{_hex()}", **kw)


async def _post(c, a: dict, parent=None):
    return await c.fetchval(
        "INSERT INTO posts (author_did, agent_id, post_type, title, content, parent_post_id) "
        "VALUES ($1, $2, 'UPDATE', 'Update', $3, $4) RETURNING post_id",
        a["agent_did"], a["agent_id"], f"post {_hex()}", parent)


async def _welcome(c, a: dict) -> None:
    """What /onboard leaves behind: 100 WORK points and a treasury grant line."""
    await c.execute(
        "INSERT INTO token_balances (agent_did, token_type, balance) VALUES ($1, 'WORK', 100)",
        a["agent_did"])
    await c.execute(
        "INSERT INTO token_transactions (from_did, to_did, token_type, transaction_type, amount, memo) "
        "VALUES (NULL, $1, 'WORK', 'TREASURY_GRANT', 100, 'Welcome bonus')", a["agent_did"])


async def _snapshot(c) -> dict:
    """Every table's row count, and every agent row."""
    counts = await mod._row_counts(c, await mod._tables(c))
    agents = {r["agent_did"]: tuple(r) for r in await c.fetch("SELECT * FROM agents")}
    return {"counts": counts, "agents": agents}


async def _audit(c, did: str) -> list[dict]:
    rows = await c.fetch(
        "SELECT agent_did, details FROM audit_logs "
        "WHERE action = 'DELETE' AND resource_type = 'agent' AND resource_id = $1", did)
    return [{"as": r["agent_did"], **json.loads(r["details"])} for r in rows]


async def _refused(c, before: dict, needle: str, **kw) -> mod.RemoveRefused:
    """remove() must refuse mentioning *needle*, and change nothing."""
    with pytest.raises(mod.RemoveRefused) as exc:
        await mod.remove(c, **kw)
    assert needle in str(exc.value), str(exc.value)
    assert await _snapshot(c) == before
    # --apply refuses the same way
    with pytest.raises(mod.RemoveRefused):
        await mod.remove(c, apply=True, **kw)
    assert await _snapshot(c) == before
    return exc.value


# ── Matching ──────────────────────────────────────────────────────────────────

def test_only_the_listed_names_match():
    assert mod.is_test_account("A189_-002")
    assert mod.is_test_account("A386_-002")
    assert mod.is_test_account("A652_-002")
    assert mod.is_test_account("canary-abc")
    assert mod.is_test_account("sdk-canary-1")
    assert mod.is_test_account("Prod Smoke 2026-04-03")
    for name in ("A189", "A189_-003", "a189_-002", "Canary-abc", "canary", "canaryx",
                 "my-canary-1", "prod smoke 1", "Prod Smoke", "ProdSmoke 1", "Atlas",
                 "", None, 5):
        assert not mod.is_test_account(name), name


def test_founder_names_match_the_personas():
    from src.founders.personas import PERSONAS
    assert set(mod.FOUNDER_NAMES) == set(PERSONAS)


async def test_show_lists_only_test_accounts(conn):
    wanted = [await _make(conn, n) for n in (
        f"canary-{_hex()}", f"sdk-canary-{_hex()}", f"Prod Smoke {_hex()}", "A189_-002")]
    for n in (f"Canary-{_hex()}", f"my-canary-{_hex()}", f"prod smoke {_hex()}",
              f"canary{_hex()}", "A189_-003"):
        await _make(conn, n)
    shown = {a["agent_did"] for a in await mod.show(conn)}
    assert {a["agent_did"] for a in wanted} <= shown
    others = {a["agent_did"] for a in await conn.fetch("SELECT agent_did FROM agents")} - shown
    assert all(not mod.is_test_account(a["display_name"])
               for a in await conn.fetch("SELECT display_name FROM agents WHERE agent_did = ANY($1)",
                                         sorted(others)))


# ── Dry run, apply ────────────────────────────────────────────────────────────

async def _world(c):
    """Two test accounts with everything a smoke test leaves, next to a kept
    agent they interacted with."""
    kept = await _make(c, f"keeper-{_hex()}")
    kept_post = await _post(c, kept)
    one, two = await _canary(c), await _make(c, "A386_-002")
    for a in (one, two):
        await _welcome(c, a)
        await c.execute("INSERT INTO agent_capabilities (agent_did, capability_id) VALUES ($1, $2)",
                        a["agent_did"], "infrastructure.docker.advanced")
    p1 = await _post(c, one)
    await _post(c, two, parent=p1)                       # reply between removed accounts
    await _post(c, one, parent=kept_post)                # reply to the kept agent
    await c.execute("INSERT INTO post_likes (post_id, agent_did) VALUES ($1, $2)",
                    kept_post, one["agent_did"])
    await c.execute("INSERT INTO post_likes (post_id, agent_did) VALUES ($1, $2)",
                    p1, kept["agent_did"])               # the kept agent liked a test post
    await c.execute("INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                    one["agent_did"], kept["agent_did"])
    await c.execute("INSERT INTO follows (follower_did, following_did) VALUES ($1, $2)",
                    kept["agent_did"], two["agent_did"])
    await c.execute(
        "INSERT INTO messages (sender_agent_did, receiver_agent_did, message) VALUES ($1, $2, 'hi')",
        one["agent_did"], kept["agent_did"])
    await c.execute(
        "INSERT INTO notifications (to_did, from_did, notif_type) VALUES ($1, $2, 'FOLLOW')",
        kept["agent_did"], one["agent_did"])
    await c.execute(
        "INSERT INTO trust_events (agent_id, agent_did, event_type, event_value, counterparty_did) "
        "VALUES ($1, $2, 'task_completed', 0.05, $3)",
        kept["agent_id"], kept["agent_did"], one["agent_did"])   # stays: a text mention
    await c.execute(
        "INSERT INTO audit_logs (agent_did, action, resource_type, resource_id) "
        "VALUES ($1, 'CREATE', 'agent', $1)", one["agent_did"])
    return kept, kept_post, one, two


async def test_dry_run_changes_nothing(conn):
    kept, kept_post, one, two = await _world(conn)
    before = await _snapshot(conn)

    report = await mod.remove(conn)
    assert await _snapshot(conn) == before
    assert await _audit(conn, one["agent_did"]) == []
    assert not report.applied
    dids = {r.agent_did for r in report.removed}
    assert {one["agent_did"], two["agent_did"]} <= dids
    r1 = next(r for r in report.removed if r.agent_did == one["agent_did"])
    assert r1.own["posts.author_did"] == 2 and r1.own["messages.sender_agent_did"] == 1
    assert r1.own["token_transactions.to_did"] == 1 and r1.own["audit_logs.agent_did"] == 1
    assert r1.cascade["follows.follower_did"] == 1 and r1.cascade["post_likes.agent_did"] == 1
    assert r1.points == {"WORK": 100}
    assert "DRY RUN" in mod.render(report)
    assert report.rows_removed["agents"] >= 2 and report.rows_removed["posts"] >= 3


async def test_apply_removes_only_the_targets(conn):
    kept, kept_post, one, two = await _world(conn)
    bystander = await _make(conn, f"bystander-{_hex()}")
    before = await _snapshot(conn)

    report = await mod.remove(conn, apply=True)
    assert report.applied
    gone = {r.agent_did for r in report.removed}
    assert {one["agent_did"], two["agent_did"]} <= gone

    after = await _snapshot(conn)
    assert set(after["agents"]) == set(before["agents"]) - gone
    assert not await conn.fetch("SELECT 1 FROM posts WHERE author_did = ANY($1)", sorted(gone))
    assert not await conn.fetch("SELECT 1 FROM token_balances WHERE agent_did = ANY($1)", sorted(gone))
    assert not await conn.fetch("SELECT 1 FROM token_transactions WHERE to_did = ANY($1)", sorted(gone))
    assert not await conn.fetch(
        "SELECT 1 FROM follows WHERE follower_did = ANY($1) OR following_did = ANY($1)", sorted(gone))
    # no cell but the trust event's text mention still holds a removed id
    for r in report.removed:
        assert set(r.mentions) <= {"trust_events.counterparty_did", "audit_logs.resource_id"}, r.mentions
    # the kept agent's rows and counters are right
    kp = await conn.fetchrow("SELECT like_count, reply_count FROM posts WHERE post_id = $1", kept_post)
    assert (kp["like_count"], kp["reply_count"]) == (0, 0)
    ka = await conn.fetchrow(
        "SELECT followers_count, following_count FROM agents WHERE agent_did = $1", kept["agent_did"])
    assert (ka["followers_count"], ka["following_count"]) == (0, 0)
    assert await conn.fetchval(
        "SELECT count(*) FROM trust_events WHERE agent_did = $1", kept["agent_did"]) == 1
    assert after["agents"][bystander["agent_did"]] == before["agents"][bystander["agent_did"]]
    # one audit row per removal, written as the --log-as agent
    for a in (one, two):
        (row,) = await _audit(conn, a["agent_did"])
        assert row["as"] == LOG_AS and row["by"] == mod.DEFAULT_ACTOR
        assert row["display_name"] == a["display_name"] and row["role"] == "MEMBER"
    assert await _audit(conn, one["agent_did"]) and "Written" in mod.render(report)


async def test_named_dids_remove_only_those(conn):
    one, two = await _canary(conn), await _canary(conn)
    report = await mod.remove(conn, [one["agent_did"]], apply=True)
    assert [r.agent_did for r in report.removed] == [one["agent_did"]]
    assert await conn.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", two["agent_did"])
    assert await conn.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", one["agent_did"]) is None


async def test_ledger_between_removed_accounts_is_allowed(conn):
    one, two = await _canary(conn), await _canary(conn)
    await conn.execute(
        "INSERT INTO token_transactions (from_did, to_did, token_type, transaction_type, amount) "
        "VALUES ($1, $2, 'WORK', 'TRANSFER', 5)", one["agent_did"], two["agent_did"])
    report = await mod.remove(conn, [one["agent_did"], two["agent_did"]], apply=True)
    assert len(report.removed) == 2
    assert not await conn.fetch(
        "SELECT 1 FROM token_transactions WHERE from_did = $1 OR to_did = $2",
        one["agent_did"], two["agent_did"])


async def test_nothing_to_remove(conn):
    await conn.execute(
        "DELETE FROM agents WHERE display_name = ANY($1) OR display_name LIKE 'canary-%' "
        "OR display_name LIKE 'sdk-canary-%' OR display_name LIKE 'Prod Smoke %'",
        sorted(mod.EXACT_NAMES))
    report = await mod.remove(conn, apply=True)
    assert report.removed == [] and "nothing to remove" in mod.render(report)


# ── Refusals ──────────────────────────────────────────────────────────────────

async def test_refuses_founding_agent_lookalike(conn):
    await _make(conn, f"canary-{_hex()}", did=f"did:agentx:atlas-{_hex(4)}-777")
    await _refused(conn, await _snapshot(conn), "founding agent ATLAS")


@pytest.mark.parametrize("role", ["FOUNDER", "OPERATOR", "DELEGATE"])
async def test_refuses_elevated_role(conn, role):
    await _canary(conn, role=role)
    await _refused(conn, await _snapshot(conn), f"role is {role}")


async def test_refuses_wallet_balance(conn):
    a = await _canary(conn)
    await conn.execute("INSERT INTO wallets (agent_id, balance) VALUES ($1, 7)", a["agent_id"])
    await _refused(conn, await _snapshot(conn), "wallet holds 7 tokens")


async def test_refuses_wallet_ledger_line(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    w = await conn.fetchval(
        "INSERT INTO wallets (agent_id, balance) VALUES ($1, 0) RETURNING wallet_id", a["agent_id"])
    kw = await conn.fetchval(
        "INSERT INTO wallets (agent_id, balance) VALUES ($1, 3) RETURNING wallet_id", kept["agent_id"])
    await conn.execute(
        "INSERT INTO transactions (from_wallet, to_wallet, amount, type) VALUES ($1, $2, 3, 'transfer')",
        w, kw)
    await _refused(conn, await _snapshot(conn), "ledger line(s) in transactions")


async def test_refuses_unreleased_stake(conn):
    a = await _canary(conn)
    await conn.execute("INSERT INTO stakes (agent_id, amount) VALUES ($1, 40)", a["agent_id"])
    await _refused(conn, await _snapshot(conn), "40 tokens staked")


async def test_released_stake_is_allowed(conn):
    a = await _canary(conn)
    await conn.execute(
        "INSERT INTO stakes (agent_id, amount, released_at) VALUES ($1, 40, NOW())", a["agent_id"])
    report = await mod.remove(conn, [a["agent_did"]], apply=True)
    assert report.removed[0].cascade["stakes.agent_id"] == 1


@pytest.mark.parametrize("token, points, needle", [
    ("REP", 10, "10 REP points"), ("GOV", 1, "1 GOV points"), ("WORK", 101, "101 WORK points"),
])
async def test_refuses_points(conn, token, points, needle):
    a = await _canary(conn)
    await conn.execute(
        "INSERT INTO token_balances (agent_did, token_type, balance) VALUES ($1, $2::token_type, $3)",
        a["agent_did"], token, points)
    await _refused(conn, await _snapshot(conn), needle)


async def test_refuses_ledger_line_with_an_agent_who_stays(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    await conn.execute(
        "INSERT INTO token_transactions (from_did, to_did, token_type, transaction_type, amount) "
        "VALUES ($1, $2, 'WORK', 'TRANSFER', 5)", kept["agent_did"], a["agent_did"])
    await _refused(conn, await _snapshot(conn), f"token ledger line(s) with {kept['agent_did']}")


async def test_refuses_shared_record_vote(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    post = await _post(conn, kept)
    await conn.execute(
        "INSERT INTO votes (post_id, voter_did, choice) VALUES ($1, $2, 'FOR')", post, a["agent_did"])
    await _refused(conn, await _snapshot(conn), "votes.voter_did (shared record")


async def test_refuses_endorsement_given(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    await conn.execute("INSERT INTO agent_capabilities (agent_did, capability_id) VALUES ($1, $2)",
                       kept["agent_did"], "infrastructure.docker.advanced")
    await conn.execute(
        "INSERT INTO capability_endorsements (agent_did, capability_id, endorser_did) VALUES ($1, $2, $3)",
        kept["agent_did"], "infrastructure.docker.advanced", a["agent_did"])
    await _refused(conn, await _snapshot(conn), "capability_endorsements.endorser_did (shared")


async def test_refuses_reply_from_an_agent_who_stays(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    post = await _post(conn, a)
    await _post(conn, kept, parent=post)
    await _refused(conn, await _snapshot(conn), f"reply(ies) to its posts by {kept['agent_did']}")


async def test_refuses_comment_from_an_agent_who_stays(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    post = await _post(conn, a)
    thread = await conn.fetchval(
        "INSERT INTO threads (post_id, creator_did, title) VALUES ($1, $2, 't') RETURNING thread_id",
        post, kept["agent_did"])
    await conn.execute(
        "INSERT INTO comments (thread_id, author_did, content) VALUES ($1, $2, 'c')",
        thread, kept["agent_did"])
    await _refused(conn, await _snapshot(conn), f"comment(s) on its posts by {kept['agent_did']}")


async def test_refuses_reply_to_its_comment_from_an_agent_who_stays(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    post = await _post(conn, kept)
    thread = await conn.fetchval(
        "INSERT INTO threads (post_id, creator_did, title) VALUES ($1, $2, 't') RETURNING thread_id",
        post, kept["agent_did"])
    mine = await conn.fetchval(
        "INSERT INTO comments (thread_id, author_did, content) VALUES ($1, $2, 'c') RETURNING comment_id",
        thread, a["agent_did"])
    await conn.execute(
        "INSERT INTO comments (thread_id, parent_comment_id, author_did, content) VALUES ($1, $2, $3, 'r')",
        thread, mine, kept["agent_did"])
    await _refused(conn, await _snapshot(conn), f"reply(ies) to its comments by {kept['agent_did']}")


async def test_refuses_vote_on_its_post_from_an_agent_who_stays(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    post = await _post(conn, a)
    await conn.execute(
        "INSERT INTO votes (post_id, voter_did, choice) VALUES ($1, $2, 'FOR')", post, kept["agent_did"])
    await _refused(conn, await _snapshot(conn), f"vote(s) on its posts by {kept['agent_did']}")


async def test_refuses_proposal_with_debate_rounds(conn):
    a = await _canary(conn)
    post = await _post(conn, a)
    await conn.execute(
        "INSERT INTO debate_rounds (proposal_id, round_number, phase) VALUES ($1, 1, 'OPENING')", post)
    await _refused(conn, await _snapshot(conn), "debate_rounds on its proposal")


async def test_refuses_room_it_created(conn):
    a = await _canary(conn)
    await conn.execute("INSERT INTO rooms (name, creator_did) VALUES ('r', $1)", a["agent_did"])
    await _refused(conn, await _snapshot(conn), "rooms.creator_did (shared record")


async def test_refuses_more_than_max_unless_named(conn):
    one = await _canary(conn)
    await _canary(conn)
    await _refused(conn, await _snapshot(conn), "more than --max 1", max_count=1)
    report = await mod.remove(conn, [one["agent_did"]], max_count=1)    # named: allowed
    assert [r.agent_did for r in report.removed] == [one["agent_did"]]
    with pytest.raises(mod.RemoveRefused):
        await mod.remove(conn, max_count=0)


async def test_refuses_a_did_that_is_not_a_test_account(conn):
    a, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    before = await _snapshot(conn)
    await _refused(conn, before, "not a test account", dids=[a["agent_did"], kept["agent_did"]])
    await _refused(conn, before, "no agent has this address",
                   dids=[a["agent_did"], "did:agentx:nobody-000"])


async def test_refuses_bad_log_as(conn):
    a = await _canary(conn)
    before = await _snapshot(conn)
    await _refused(conn, before, "not an existing agent", log_as="did:agentx:nobody-000")
    await _refused(conn, before, "not an existing agent", log_as="")
    await _refused(conn, before, "is itself being removed", log_as=a["agent_did"])


async def test_log_as_defaults_to_the_first_founding_agent(conn):
    assert mod.LOG_AS_CANDIDATES[:2] == ("did:agentx:atlas-seed-001", "did:agentx:atlas-001")
    a = await _canary(conn)
    report = await mod.remove(conn, [a["agent_did"]], apply=True)
    assert report.log_as == LOG_AS
    (row,) = await _audit(conn, a["agent_did"])
    assert row["as"] == LOG_AS
    # an explicit --log-as wins, any existing agent will do
    b, kept = await _canary(conn), await _make(conn, f"keeper-{_hex()}")
    report = await mod.remove(conn, [b["agent_did"]], apply=True, log_as=kept["agent_did"])
    assert report.log_as == kept["agent_did"]
    (row,) = await _audit(conn, b["agent_did"])
    assert row["as"] == kept["agent_did"]


async def test_one_bad_account_blocks_the_batch(conn):
    good, bad = await _canary(conn), await _canary(conn)
    await conn.execute("INSERT INTO wallets (agent_id, balance) VALUES ($1, 9)", bad["agent_id"])
    exc = await _refused(conn, await _snapshot(conn), "wallet holds 9 tokens",
                         dids=[good["agent_did"], bad["agent_did"]])
    assert all(bad["agent_did"] in p for p in exc.problems)
    assert await conn.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", good["agent_did"])


async def test_no_audit_row_means_no_removal(conn):
    a = await _canary(conn)
    before = await _snapshot(conn)
    await conn.execute("ALTER TABLE audit_logs RENAME TO audit_logs_gone")
    try:
        with pytest.raises(asyncpg.PostgresError) as exc:
            await mod.remove(conn, [a["agent_did"]], apply=True)
        assert "audit_logs" in str(exc.value)
    finally:
        await conn.execute("ALTER TABLE audit_logs_gone RENAME TO audit_logs")
    assert await _snapshot(conn) == before


# ── Command line ──────────────────────────────────────────────────────────────

async def test_command_line(pool, escrow_db):
    dsn = f"postgresql://{PG_USER}@{smoke.DB_HOST}:{PG_PORT}/{escrow_db}"
    made_atlas = await pool.fetchval(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Atlas CLI') "
        "ON CONFLICT (agent_did) DO NOTHING RETURNING agent_id", LOG_AS)
    name = f"sdk-canary-{_hex()}"
    did = f"did:agentx:sdk-canary-{_hex(6)}-001"
    await pool.execute(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", did, name)
    held = await pool.fetchrow(
        "INSERT INTO agents (agent_did, display_name) VALUES ($1, $2) RETURNING agent_id",
        f"did:agentx:canary-{_hex(6)}-001", f"canary-{_hex()}")
    await pool.execute("INSERT INTO wallets (agent_id, balance) VALUES ($1, 2)", held["agent_id"])

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--dsn", dsn, *argv],
            capture_output=True, text=True, timeout=120)

    try:
        shown = run("show")
        assert shown.returncode == 0 and did in shown.stdout, shown.stderr

        refused = run("remove")                       # the wallet-holder blocks the batch
        assert refused.returncode == 1 and "REFUSED" in refused.stderr, refused.stderr
        assert "wallet holds 2 tokens" in refused.stderr

        dry = run("remove", "--did", did)
        assert dry.returncode == 0 and "DRY RUN" in dry.stdout, dry.stderr
        assert await pool.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", did)

        done = run("remove", "--did", did, "--apply", "--by", "DrJ")
        assert done.returncode == 0 and "Written to the database: 1" in done.stdout, done.stderr
        assert await pool.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", did) is None
        (row,) = await _audit(pool, did)
        assert row["by"] == "DrJ" and row["as"] == LOG_AS

        bad = subprocess.run(
            [sys.executable, str(_SCRIPT), "--dsn", "postgresql://127.0.0.1:1/nope", "show"],
            capture_output=True, text=True, timeout=120)
        assert bad.returncode == 1 and "STOPPED" in bad.stderr
    finally:
        await pool.execute("DELETE FROM audit_logs WHERE resource_id = $1", did)
        await pool.execute("DELETE FROM agents WHERE agent_did = $1", did)
        await pool.execute("DELETE FROM agents WHERE agent_id = $1", held["agent_id"])
        if made_atlas:
            await pool.execute("DELETE FROM agents WHERE agent_id = $1", made_atlas)
