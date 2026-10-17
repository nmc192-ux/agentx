"""
EL-1: scripts/bootstrap_db.py builds an EMPTY database with the production founder DIDs.

Pure parts (roster, SQL rewrite) run everywhere. The rest is rehearsed against local Postgres
on a scratch database (agentx_smoke_bootstrap), never any other one:
empty DB -> bootstrap -> 8 founders ACTIVE with the given DIDs, roster resolves all 8,
alembic at head; a second run refuses; a bad FOUNDER_DIDS writes nothing; --check.
"""
from __future__ import annotations

import getpass
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[2]
SCRIPT = PLATFORM / "scripts" / "bootstrap_db.py"
DB = "agentx_smoke_bootstrap"
PG_USER = getpass.getuser()

PROD_DIDS = {
    "atlas": "did:agentx:atlas-seed-001", "bruno": "did:agentx:bruno-001",
    "daria": "did:agentx:daria-seed-001", "gia": "did:agentx:gia-seed-001",
    "marcus": "did:agentx:marcus-seed-001", "nova": "did:agentx:nova-seed-001",
    "quinn": "did:agentx:quinn-seed-001", "thea": "did:agentx:thea-seed-001",
}
PROD_ROSTER = ",".join(f"{k}={v}" for k, v in PROD_DIDS.items())

_spec = importlib.util.spec_from_file_location("bootstrap_db", SCRIPT)
bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap)


# ── Pure parts ────────────────────────────────────────────────────────────────

def test_full_roster_needs_all_eight():
    assert bootstrap.full_roster(PROD_ROSTER) == PROD_DIDS
    with pytest.raises(bootstrap.BootstrapRefused, match="missing: thea"):
        bootstrap.full_roster(PROD_ROSTER.replace(",thea=did:agentx:thea-seed-001", ""))
    with pytest.raises(bootstrap.BootstrapRefused, match="missing"):
        bootstrap.full_roster("")


@pytest.mark.parametrize("bad", [
    PROD_ROSTER.replace("nova-seed-001", "atlas-seed-001"),       # another founder's address
    PROD_ROSTER + ",atlas=did:agentx:atlas-002",                    # listed twice
    PROD_ROSTER.replace("quinn=did", "quinn did"),                  # not name=did
    PROD_ROSTER + ",mallory=did:agentx:mallory-001",                # not a founder
    PROD_ROSTER.replace("gia-seed-001", "gia-seed-001'); DROP TABLE agents; --"),  # injection
])
def test_full_roster_rejects_bad_values(bad):
    with pytest.raises(bootstrap.BootstrapRefused):
        bootstrap.full_roster(bad)


def test_seed_sql_rewrites_every_founder_literal():
    sql = bootstrap.seed_sql(bootstrap.INIT_SQL.read_text(), PROD_DIDS)
    for name, did in PROD_DIDS.items():
        assert f"'{did}'" in sql
        if did != f"did:agentx:{name}-001":
            assert f"did:agentx:{name}-001" not in sql
    # Only the founder literals changed: same statements otherwise.
    original = bootstrap.INIT_SQL.read_text()
    assert sql.count("INSERT INTO") == original.count("INSERT INTO")


def test_seed_sql_refuses_when_a_founder_is_not_seeded():
    with pytest.raises(bootstrap.BootstrapRefused, match="does not seed"):
        bootstrap.seed_sql("SELECT 1;", PROD_DIDS)


def test_image_ships_the_script_and_init_sql():
    dockerfile = (PLATFORM / "Dockerfile.fly").read_text()
    assert "COPY scripts/init-db.sql ./scripts/init-db.sql" in dockerfile
    assert "COPY scripts/bootstrap_db.py ./scripts/bootstrap_db.py" in dockerfile


# ── Against local Postgres ────────────────────────────────────────────────────

needs_pg = pytest.mark.skipif(shutil.which("psql") is None, reason="Postgres client tools not installed")


def _psql(*args: str, db: str = "postgres") -> str:
    out = subprocess.run(
        ["psql", "-X", "-At", "-h", "localhost", "-U", PG_USER, "-d", db, "-v", "ON_ERROR_STOP=1", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def empty_db():
    _psql("-c", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    _psql("-c", f"CREATE DATABASE {DB}")
    yield DB
    _psql("-c", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")


def run(*args: str, founder_dids: str | None = PROD_ROSTER) -> subprocess.CompletedProcess:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_") and k != "FOUNDER_DIDS"},
        "APP_ENV": "development", "REDIS_URL": "memory://", "JWT_SECRET": "x" * 40,
        "POSTGRES_PASSWORD": "local-trust",   # local Postgres trusts; the settings want a value
    }
    if founder_dids is not None:
        env["FOUNDER_DIDS"] = founder_dids
    dsn = f"postgresql://{PG_USER}@localhost:5432/{DB}"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dsn", dsn, *args],
        cwd=PLATFORM, env=env, capture_output=True, text=True, timeout=600,
    )


def _tables(db: str) -> int:
    return int(_psql("-c", "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'", db=db))


def _head() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=PLATFORM, capture_output=True, text=True,
        env={**os.environ, "APP_ENV": "development", "JWT_SECRET": "x" * 40, "REDIS_URL": "memory://",
             "POSTGRES_PASSWORD": "local-trust"},
        check=True,
    )
    return out.stdout.split()[0]


@pytest.mark.integration
@needs_pg
def test_bootstrap_empty_db_then_refuses_a_second_run(empty_db):
    assert run("--check").returncode == bootstrap.EXIT_EMPTY

    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: bootstrap complete" in result.stdout

    rows = _psql("-F", "|", "-c",
                 "SELECT agent_did, display_name, status FROM agents ORDER BY agent_did", db=empty_db)
    assert sorted(line.split("|")[0] for line in rows.splitlines()) == sorted(PROD_DIDS.values())
    assert all(line.endswith("|ACTIVE") for line in rows.splitlines())
    for did in PROD_DIDS.values():
        assert f"founder {[k for k, v in PROD_DIDS.items() if v == did][0]}={did} ACTIVE" in result.stdout
    # Everything the seed hangs off a founder followed the new address.
    orphans = _psql("-c", """
        SELECT count(*) FROM (
          SELECT agent_did FROM token_balances UNION ALL SELECT agent_did FROM agent_capabilities
          UNION ALL SELECT agent_did FROM collective_members UNION ALL SELECT agent_did FROM agent_trust_breakdown
        ) x WHERE agent_did NOT IN (SELECT agent_did FROM agents)""", db=empty_db)
    assert orphans == "0"
    assert _psql("-c", "SELECT version_num FROM alembic_version", db=empty_db) == _head()

    assert run("--check").returncode == 0
    tables = _tables(empty_db)
    again = run()
    assert again.returncode == bootstrap.EXIT_REFUSED
    assert "not empty" in again.stderr
    assert _tables(empty_db) == tables


@pytest.mark.integration
@needs_pg
@pytest.mark.parametrize("bad", [
    None,                                                            # not set at all
    "",                                                              # empty
    PROD_ROSTER.replace(",thea=did:agentx:thea-seed-001", ""),       # seven founders
    PROD_ROSTER.replace("nova-seed-001", "atlas-seed-001"),          # wrong founder's address
])
def test_bad_founder_dids_writes_nothing(empty_db, bad):
    result = run(founder_dids=bad)
    assert result.returncode == bootstrap.EXIT_REFUSED, result.stdout + result.stderr
    assert "FOUNDER_DIDS" in result.stderr
    assert _tables(empty_db) == 0


@pytest.mark.integration
@needs_pg
def test_foreign_tables_are_never_touched(empty_db):
    _psql("-c", "CREATE TABLE notes (x int); INSERT INTO notes VALUES (1)", db=empty_db)
    assert run("--check").returncode == bootstrap.EXIT_REFUSED
    result = run()
    assert result.returncode == bootstrap.EXIT_REFUSED
    assert _tables(empty_db) == 1
    assert _psql("-c", "SELECT count(*) FROM notes", db=empty_db) == "1"


@pytest.mark.integration
@needs_pg
def test_failure_inside_the_seed_rolls_everything_back(empty_db, monkeypatch, tmp_path):
    """A founder check that fails after the SQL ran leaves the database empty."""
    import asyncio
    import asyncpg

    async def go():
        conn = await asyncpg.connect(f"postgresql://{PG_USER}@localhost:5432/{DB}")
        try:
            sql = bootstrap.seed_sql(bootstrap.INIT_SQL.read_text(), PROD_DIDS)
            # A roster that disagrees with the seeded rows: resolve_founder refuses.
            wrong = {**PROD_DIDS, "atlas": "did:agentx:atlas-007"}
            with pytest.raises(bootstrap.FounderRefused):
                await bootstrap.seed(conn, wrong, sql)
        finally:
            await conn.close()

    asyncio.run(go())
    assert _tables(empty_db) == 0
