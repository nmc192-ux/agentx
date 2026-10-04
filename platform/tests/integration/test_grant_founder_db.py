"""
Integration tests: scripts/grant_founder.py against REAL local Postgres.
PLAN step P-8 (H20): the only way an agent becomes a FOUNDER in production.

What is proven:
  • grant: a dry run changes nothing; --apply makes exactly the named agent a
    FOUNDER, changes no other row, and writes one audit row
  • grant fails closed, changing nothing, for: a malformed or unknown
    address, a wrong display name, an agent that is not ACTIVE, not a MEMBER,
    one of the eight founding agents or a look-alike, an old account, a
    stretched --max-age-hours, and while any other FOUNDER exists
  • if the audit row cannot be written, the role is not changed
  • revoke: FOUNDER -> MEMBER for the named agent only, logged; refused for an
    agent that is not a FOUNDER; allowed for a founding agent
  • the role takes effect through the real login check at once, both ways
  • the command line runs end to end (dry run, --apply, refusal exit code)

The shared test database is full of FOUNDERs other tests made, so each test
runs inside a transaction that first makes them MEMBERs and is rolled back at
the end; the script's own transaction becomes a savepoint inside it.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration   # skipped unless --db is given

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "grant_founder.py"
_spec = importlib.util.spec_from_file_location("grant_founder", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


@pytest_asyncio.fixture
async def conn(pool):
    """A connection in a transaction where nobody is a FOUNDER (production
    today); everything is rolled back afterwards."""
    async with pool.acquire() as c:
        tr = c.transaction()
        await tr.start()
        try:
            await c.execute(
                "UPDATE agents SET governance_role = 'MEMBER' WHERE governance_role = 'FOUNDER'"
            )
            yield c
        finally:
            await tr.rollback()


async def _make(c, did: str | None = None, name: str | None = None, role: str = "MEMBER",
                status: str = "ACTIVE", age_hours: float = 0) -> tuple[str, str]:
    did = did or f"did:agentx:admin-{uuid4().hex[:8]}-001"
    name = name or f"Admin {uuid4().hex[:8]}"
    await c.execute(
        """
        INSERT INTO agents (agent_did, display_name, governance_role, status, created_at)
        VALUES ($1, $2, $3::governance_role, $4::agent_status,
                NOW() - make_interval(secs => $5))
        """,
        did, name, role, status, age_hours * 3600,
    )
    return did, name


async def _roles(c) -> dict[str, str]:
    return await mod._roles(c)


async def _audit(c, did: str) -> list[tuple[str, dict]]:
    rows = await c.fetch(
        "SELECT action::text, details FROM audit_logs "
        "WHERE resource_type = 'AGENT_ROLE' AND resource_id = $1 ORDER BY created_at",
        did,
    )
    return [(r["action"], json.loads(r["details"])) for r in rows]


async def _refused(c, reason: str, call) -> None:
    """*call* raises GrantRefused(reason) and leaves every role and the log as they were."""
    before = await _roles(c)
    logged = await c.fetchval("SELECT COUNT(*) FROM audit_logs WHERE resource_type = 'AGENT_ROLE'")
    with pytest.raises(mod.GrantRefused) as exc:
        await call
    assert exc.value.reason == reason, exc.value
    assert await _roles(c) == before
    assert await c.fetchval(
        "SELECT COUNT(*) FROM audit_logs WHERE resource_type = 'AGENT_ROLE'") == logged


def test_founder_names_match_the_personas():
    from src.founders.personas import PERSONAS
    assert set(mod.FOUNDER_NAMES) == set(PERSONAS)


async def test_grant_dry_run_then_apply_changes_one_row(conn):
    did, name = await _make(conn)
    bystander, _ = await _make(conn)
    before = await _roles(conn)

    result = await mod.grant(conn, did, name)
    assert result["role"] == "FOUNDER"                     # what it would do
    assert await _roles(conn) == before                    # and did not
    assert await _audit(conn, did) == []

    await mod.grant(conn, did, name, by="drj", apply=True)
    after = await _roles(conn)
    assert after[did] == "FOUNDER" and after[bystander] == "MEMBER"
    assert {d for d in after if after[d] != before[d]} == {did}
    assert [d for d, r in after.items() if r == "FOUNDER"] == [did]
    assert await _audit(conn, did) == [("ASSIGN", {
        "why": "scripts/grant_founder.py", "by": "drj",
        "from": "MEMBER", "to": "FOUNDER", "display_name": name,
    })]
    assert [a["agent_did"] for a in await mod.show(conn) if a["role"] == "FOUNDER"] == [did]

    # A second grant, of the same agent or another, is refused.
    await _refused(conn, "not_member", mod.grant(conn, did, name, apply=True))
    bystander_name = await conn.fetchval(
        "SELECT display_name FROM agents WHERE agent_did = $1", bystander)
    await _refused(conn, "other_founder_exists",
                   mod.grant(conn, bystander, bystander_name, apply=True))


@pytest.mark.parametrize("did", [
    "", "did:agentx:admin", "did:agentx:Admin-001", "did:web:admin-001",
    "did:agentx:admin-001' OR '1'='1", "did:agentx:admin-001\n", None, "%",
])
async def test_grant_refuses_a_malformed_address(conn, did):
    await _refused(conn, "bad_did", mod.grant(conn, did, "x", apply=True))


async def test_grant_refuses_unknown_agent_and_wrong_name(conn):
    did, name = await _make(conn)
    await _refused(conn, "not_found",
                   mod.grant(conn, f"did:agentx:ghost-{uuid4().hex[:8]}-001", name, apply=True))
    for wrong in ("", name.lower(), name + " ", name[:-1], "%", None):
        await _refused(conn, "name_mismatch", mod.grant(conn, did, wrong, apply=True))


@pytest.mark.parametrize("status", ["SUSPENDED", "DEACTIVATED"])
async def test_grant_refuses_an_agent_that_is_not_active(conn, status):
    did, name = await _make(conn, status=status)
    await _refused(conn, "not_active", mod.grant(conn, did, name, apply=True))


@pytest.mark.parametrize("role", ["OBSERVER", "DELEGATE", "OPERATOR"])
async def test_grant_refuses_any_role_but_member(conn, role):
    did, name = await _make(conn, role=role)
    await _refused(conn, "not_member", mod.grant(conn, did, name, apply=True))


@pytest.mark.parametrize("founder", mod.FOUNDER_NAMES)
async def test_grant_refuses_every_founding_agent(conn, founder):
    """The seeded did:agentx:<name>-001 rows, whatever role the seed gave them."""
    did = f"did:agentx:{founder}-001"
    name = await conn.fetchval("SELECT display_name FROM agents WHERE agent_did = $1", did)
    assert name is not None
    await conn.execute(
        "UPDATE agents SET governance_role = 'MEMBER', status = 'ACTIVE', created_at = NOW() "
        "WHERE agent_did = $1", did,
    )
    await _refused(conn, "founding_agent", mod.grant(conn, did, name, apply=True))


@pytest.mark.parametrize("stem, shown", [
    ("nova-seed", "Somebody"),          # a founder address, any display name
    ("nova-{u}", "Somebody"),
    ("helper-{u}", "NOVA"),             # any address, a founder's display name
    ("helper-{u}", "Nova_{u4}"),        # migration 038's suffix
    ("helper-{u}", " atlas "),
    ("helper-{u}", "Bruno-2"),
])
async def test_grant_refuses_founder_lookalikes(conn, stem, shown):
    u = uuid4().hex[:8]
    did = f"did:agentx:{stem.format(u=u)}-777"
    name = shown.format(u=u, u4=u[:4])
    # Display names are unique among active agents: move the seeded founder's aside.
    await conn.execute(
        "UPDATE agents SET display_name = display_name || '_was' "
        "WHERE lower(display_name) = lower($1)", name,
    )
    did, name = await _make(conn, did=did, name=name)
    await _refused(conn, "founding_agent", mod.grant(conn, did, name, apply=True))


def test_lookalike_rule_leaves_ordinary_names_alone():
    assert mod.founding_agent_lookalike("did:agentx:drj-admin-001", "DrJ Admin") is None
    assert mod.founding_agent_lookalike("did:agentx:novella-001", "Novella") is None
    assert mod.founding_agent_lookalike("did:agentx:supernova-001", "Supernova") is None
    assert mod.founding_agent_lookalike("did:agentx:nova-001", "x") == "nova"
    assert mod.founding_agent_lookalike("did:agentx:x-001", "THEA") == "thea"


async def test_grant_refuses_an_old_account_and_a_stretched_window(conn):
    old, old_name = await _make(conn, age_hours=25)
    await _refused(conn, "too_old", mod.grant(conn, old, old_name, apply=True))
    ancient, ancient_name = await _make(conn, age_hours=24 * 30)
    for bad in (0, -1, 169, 10_000, float("inf"), float("nan"), None, "24"):
        await _refused(conn, "bad_max_age",
                       mod.grant(conn, ancient, ancient_name, apply=True, max_age_hours=bad))
    await _refused(conn, "too_old",
                   mod.grant(conn, ancient, ancient_name, apply=True, max_age_hours=168))
    # An account dated in the future is not "new".
    future, future_name = await _make(conn, age_hours=-2)
    await _refused(conn, "too_old", mod.grant(conn, future, future_name, apply=True))
    # Inside a window DrJ widened on purpose it goes through.
    await mod.grant(conn, old, old_name, apply=True, max_age_hours=48)
    assert (await _roles(conn))[old] == "FOUNDER"


@pytest.mark.parametrize("other", ["did:agentx:atlas-001", None])
async def test_grant_refuses_while_another_founder_exists(conn, other):
    if other is None:
        other, _ = await _make(conn, role="FOUNDER")
    else:
        await conn.execute(
            "UPDATE agents SET governance_role = 'FOUNDER' WHERE agent_did = $1", other)
    did, name = await _make(conn)
    await _refused(conn, "other_founder_exists", mod.grant(conn, did, name, apply=True))


async def test_no_audit_row_means_no_grant(conn):
    """The log insert fails (the table is gone inside this transaction): the
    role change is rolled back with it."""
    did, name = await _make(conn)
    sp = conn.transaction()
    await sp.start()
    try:
        await conn.execute("ALTER TABLE audit_logs RENAME TO audit_logs_gone")
        with pytest.raises(Exception) as exc:
            await mod.grant(conn, did, name, apply=True)
        assert "audit_logs" in str(exc.value)
        assert (await _roles(conn))[did] == "MEMBER"
    finally:
        await sp.rollback()
    assert (await _roles(conn))[did] == "MEMBER"


async def test_revoke_dry_run_then_apply(conn):
    did, name = await _make(conn)
    await mod.grant(conn, did, name, apply=True)
    other, other_name = await _make(conn)
    before = await _roles(conn)

    await _refused(conn, "not_founder", mod.revoke(conn, other, other_name, apply=True))
    await _refused(conn, "name_mismatch", mod.revoke(conn, did, other_name, apply=True))
    await _refused(conn, "bad_did", mod.revoke(conn, "did:agentx:nope", name, apply=True))

    assert (await mod.revoke(conn, did, name))["role"] == "MEMBER"
    assert await _roles(conn) == before                    # dry run

    await mod.revoke(conn, did, name, by="drj", apply=True)
    after = await _roles(conn)
    assert {d for d in after if after[d] != before[d]} == {did} and after[did] == "MEMBER"
    assert [a for a, _ in await _audit(conn, did)] == ["ASSIGN", "UPDATE"]
    assert (await _audit(conn, did))[1][1]["to"] == "MEMBER"

    # With the old admin revoked, the next one can be granted.
    await mod.grant(conn, other, other_name, apply=True)
    assert [d for d, r in (await _roles(conn)).items() if r == "FOUNDER"] == [other]


async def test_revoke_works_on_a_founding_agent(conn):
    """Taking the role away is never refused for who the agent is (the seed
    makes ATLAS a FOUNDER; DrJ must be able to undo that)."""
    did = "did:agentx:atlas-001"
    name = await conn.fetchval("SELECT display_name FROM agents WHERE agent_did = $1", did)
    await conn.execute("UPDATE agents SET governance_role = 'FOUNDER' WHERE agent_did = $1", did)
    await mod.revoke(conn, did, name, apply=True)
    assert (await _roles(conn))[did] == "MEMBER"


async def test_role_reaches_the_real_login_check_at_once(conn):
    """auth.did.resolve_did_active is what every request's role comes from."""
    from src.auth.did import resolve_did_active
    from src.auth.middleware import AgentRecord

    did, name = await _make(conn)

    async def role() -> str:
        return AgentRecord(await resolve_did_active(did, conn), claims=None).role

    assert await role() == "MEMBER"
    await mod.grant(conn, did, name)                       # dry run grants nothing
    assert await role() == "MEMBER"
    await mod.grant(conn, did, name, apply=True)
    assert await role() == "FOUNDER"
    await mod.revoke(conn, did, name, apply=True)
    assert await role() == "MEMBER"


async def test_command_line_end_to_end(pool, escrow_db):
    """Committed for real: other tests' FOUNDERs are set aside and put back."""
    dsn = f"postgresql://{PG_USER}@{smoke.DB_HOST}:{PG_PORT}/{escrow_db}"

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--dsn", dsn, *argv],
            capture_output=True, text=True, timeout=60,
        )

    async def role(did: str) -> str:
        return await pool.fetchval(
            "SELECT governance_role::text FROM agents WHERE agent_did = $1", did)

    async with pool.acquire() as c:
        did, name = await _make(c)
    target = (did, "--name", name)

    # As the database stands (FOUNDERs exist): refused, exit code 1, no change.
    blocked = run("grant", *target, "--apply")
    assert blocked.returncode == 1 and "REFUSED, nothing was changed (other_founder_exists)" in blocked.stderr
    assert await role(did) == "MEMBER"

    set_aside = [r["agent_did"] for r in await pool.fetch(
        "UPDATE agents SET governance_role = 'MEMBER' WHERE governance_role = 'FOUNDER' "
        "RETURNING agent_did")]
    try:
        assert "Agents with a role above MEMBER" in run("show").stdout

        dry = run("grant", *target)
        assert dry.returncode == 0 and "DRY RUN" in dry.stdout, dry.stderr
        assert await role(did) == "MEMBER"

        wrong = run("grant", did, "--name", "Somebody Else", "--apply")
        assert wrong.returncode == 1 and "name_mismatch" in wrong.stderr
        assert await role(did) == "MEMBER"

        done = run("grant", *target, "--apply")
        assert done.returncode == 0 and f"{did} is now FOUNDER" in done.stdout, done.stderr
        assert await role(did) == "FOUNDER"
        shown = run("show").stdout
        assert did in shown and shown.count("FOUNDER ") == 1

        again = run("grant", *target, "--apply")
        assert again.returncode == 1 and "not_member" in again.stderr

        back = run("revoke", *target, "--apply")
        assert back.returncode == 0 and f"{did} is now MEMBER" in back.stdout, back.stderr
        assert await role(did) == "MEMBER"
        assert [r["action"] for r in await pool.fetch(
            "SELECT action::text FROM audit_logs WHERE resource_type = 'AGENT_ROLE' "
            "AND resource_id = $1 ORDER BY created_at", did)] == ["ASSIGN", "UPDATE"]
    finally:
        await pool.execute(
            "UPDATE agents SET governance_role = 'FOUNDER' WHERE agent_did = ANY($1::text[])",
            set_aside)
        await pool.execute(
            "UPDATE agents SET governance_role = 'MEMBER' WHERE agent_did = $1", did)

    unreachable = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dsn", "postgresql://127.0.0.1:1/nope", "show"],
        capture_output=True, text=True, timeout=60,
    )
    assert unreachable.returncode != 0
