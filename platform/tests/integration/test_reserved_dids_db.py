"""
EL-2 against real local Postgres (``--db``): the old agents' addresses are held
in `reserved_dids` until the 1 Nov import, and no sign-up path can take one.

  - the loader: dry run writes nothing; --apply reserves; a second apply is
    idempotent; registered DIDs are skipped; one bad line refuses the file;
    status / release;
  - POST /agents with a reserved DID → 409 and no row; after release → 201;
  - /onboard and /agents/register re-roll a reserved draw; when every draw is
    held they give up (503) and write nothing;
  - the race with the import: a sign-up waits for an import that is releasing
    the address and then loses to the primary key (409); an import waits for a
    sign-up in flight;
  - fail closed: with the table gone, sign-up is refused (500) and writes nothing.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from .conftest import DB_NAME, PG_PORT, PG_USER

pytestmark = pytest.mark.integration

PLATFORM = Path(__file__).resolve().parents[2]
SCRIPT = PLATFORM / "scripts" / "reserve_dids.py"
DSN = f"postgresql://{PG_USER}@localhost:{PG_PORT}/{DB_NAME}"

_spec = importlib.util.spec_from_file_location("reserve_dids", SCRIPT)
reserve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reserve)

FOUNDER_SEEDED = "did:agentx:atlas-001"   # init-db.sql seeds the founders as <name>-001 locally


@pytest.fixture
def OLD() -> list[str]:
    """Three "old" DIDs, unique per test (agent rows stay: audit_logs reference them)."""
    tag = uuid4().hex[:8]
    return [f"did:agentx:oldtimer-{tag}-042", f"did:agentx:veteran-{tag}-007", f"did:agentx:nova-{tag}-seed-001"]


def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")},
           "APP_ENV": "development", "REDIS_URL": "memory://", "JWT_SECRET": "x" * 40,
           "POSTGRES_PASSWORD": "local-trust"}
    return subprocess.run([sys.executable, str(SCRIPT), "--dsn", DSN, *args],
                          cwd=PLATFORM, env=env, capture_output=True, text=True, input=stdin, timeout=120)


@pytest_asyncio.fixture(autouse=True)
async def _clean(pool, monkeypatch):
    from src.middleware.rate_limits import limiter
    from src.services import onboard_service
    monkeypatch.setattr(onboard_service, "publish_event", AsyncMock(return_value=None))
    limiter.reset()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM reserved_dids")
    yield
    limiter.reset()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM reserved_dids")


@pytest_asyncio.fixture
async def http(pool):
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c


async def _reserved(pool) -> set[str]:
    async with pool.acquire() as conn:
        return {r["agent_did"] for r in await conn.fetch("SELECT agent_did FROM reserved_dids")}


async def _agent_exists(pool, did: str) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM agents WHERE agent_did = $1", did))


# ── The loader ────────────────────────────────────────────────────────────────

async def test_load_dry_run_writes_nothing_then_apply_is_idempotent(pool, tmp_path, OLD):
    listing = tmp_path / "old_dids.txt"
    listing.write_text("# from Neon\n" + "\n".join([OLD[0].upper(), f"  {OLD[1]} ", OLD[1], FOUNDER_SEEDED]) + "\n")

    dry = run("load", str(listing))
    assert dry.returncode == 0, dry.stderr
    assert "2 to reserve" in dry.stdout and "1 already registered" in dry.stdout
    assert "dry run: nothing written" in dry.stdout
    assert await _reserved(pool) == set()

    applied = run("load", str(listing), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert "OK: reserved 2" in applied.stdout
    assert await _reserved(pool) == {OLD[0], OLD[1]}       # normalised, deduped, founder skipped

    again = run("load", "-", "--apply", stdin=listing.read_text())   # via stdin, like the VPS command
    assert again.returncode == 0 and "OK: reserved 0" in again.stdout
    assert "2 already reserved" in again.stdout

    st = run("status")
    assert st.returncode == 0 and st.stdout.startswith("2 address(es) reserved")

    rel = run("release", OLD[0].upper())
    assert rel.returncode == 0 and "released 1" in rel.stdout
    assert await _reserved(pool) == {OLD[1]}
    assert run("release", "--all").returncode == 0
    assert await _reserved(pool) == set()


async def test_load_refuses_the_whole_file_on_one_bad_line(pool, tmp_path, OLD):
    listing = tmp_path / "bad.txt"
    listing.write_text(f"{OLD[0]}\ndid:agentx:x-001'); DROP TABLE agents; --\n{OLD[1]}\n")
    result = run("load", str(listing), "--apply")
    assert result.returncode == reserve.EXIT_REFUSED
    assert "line 2" in result.stderr and "nothing written" in result.stderr
    assert await _reserved(pool) == set()
    assert run("load", str(tmp_path / "missing.txt")).returncode != 0


# ── POST /agents (caller-chosen DID) ──────────────────────────────────────────

async def test_post_agents_refuses_a_reserved_did_until_released(pool, http, OLD):
    assert run("load", "-", "--apply", stdin="\n".join(OLD)).returncode == 0

    for did in OLD:
        r = await http.post("/agents", json={"agent_did": did, "display_name": f"Impostor {did[-3:]}"})
        assert r.status_code == 409, r.text
        assert "reserved" in r.json()["detail"]
        assert not await _agent_exists(pool, did)

    for variant in (OLD[0].upper(), f" {OLD[0]}", f"{OLD[0]}\n"):
        r = await http.post("/agents", json={"agent_did": variant, "display_name": "Impostor"})
        assert r.status_code == 422, (variant, r.text)
    assert not await _agent_exists(pool, OLD[0])

    free = f"did:agentx:newcomer-{uuid4().hex[:8]}-001"
    r = await http.post("/agents", json={"agent_did": free, "display_name": "Newcomer"})
    assert r.status_code == 201, r.text

    assert run("release", OLD[0]).returncode == 0
    r = await http.post("/agents", json={"agent_did": OLD[0], "display_name": "Returned"})
    assert r.status_code == 201, r.text


# ── Random-DID paths ──────────────────────────────────────────────────────────

async def test_onboard_rerolls_a_reserved_draw(pool, http, OLD):
    from src.services import onboard_service
    assert run("load", "-", "--apply", stdin="\n".join(OLD)).returncode == 0
    draws = iter([OLD[0], OLD[0], OLD[0][:-3] + "043"])   # slug "oldtimer"
    with patch.object(onboard_service, "_candidate_did", side_effect=lambda slug: next(draws)):
        r = await http.post("/onboard", json={"name": OLD[0][11:], "capabilities": ["x"]})
    assert r.status_code == 201, r.text
    assert r.json()["agent_did"] == OLD[0][:-3] + "043"
    assert not await _agent_exists(pool, OLD[0])


async def test_onboard_gives_up_and_writes_nothing_when_every_draw_is_held(pool, http, OLD):
    from src.services import onboard_service
    assert run("load", "-", "--apply", stdin="\n".join(OLD)).returncode == 0
    with patch.object(onboard_service, "_candidate_did", side_effect=lambda slug: OLD[1]):
        r = await http.post("/onboard", json={"name": OLD[1][11:], "capabilities": ["x"]})
    assert r.status_code == 503, r.text
    assert not await _agent_exists(pool, OLD[1])
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM agents WHERE display_name = $1", OLD[1][11:]) == 0


async def test_onboard_rechecks_inside_its_transaction(pool, http, OLD):
    """A reservation that lands between the draw and the insert makes /onboard draw again."""
    from src.services import onboard_service
    first = OLD[0]
    draws = iter([first, OLD[0][:-3] + "044"])
    real = onboard_service.assert_not_reserved
    calls = 0

    async def late_reservation(conn, did):
        nonlocal calls
        calls += 1
        if calls == 1:
            # The loader runs on its own connection while the sign-up is between draw and insert.
            other = await asyncpg.connect(DSN)
            try:
                await reserve.apply_load(other, [first])
            finally:
                await other.close()
        await real(conn, did)

    with patch.object(onboard_service, "_candidate_did", side_effect=lambda slug: next(draws)), \
         patch.object(onboard_service, "assert_not_reserved", side_effect=late_reservation):
        r = await http.post("/onboard", json={"name": OLD[0][11:], "capabilities": ["x"]})
    assert r.status_code == 201, r.text
    assert r.json()["agent_did"] == OLD[0][:-3] + "044"
    assert not await _agent_exists(pool, first) and first in await _reserved(pool)


async def test_register_route_never_lands_on_a_reserved_draw(pool, http, OLD):
    from src.routers import agents as agents_router
    assert run("load", "-", "--apply", stdin="\n".join(OLD)).returncode == 0
    draws = iter([OLD[1], OLD[2], OLD[1][:-3] + "008"])
    with patch.object(agents_router, "_make_agent_did", side_effect=lambda name: next(draws)):
        r = await http.post("/agents/register", json={
            "name": "veteran", "description": "d", "skills": [], "capabilities": [], "endpoint": "http://v", "owner": "o",
        })
    assert r.status_code == 201, r.text
    assert await _agent_exists(pool, OLD[1][:-3] + "008")
    assert not await _agent_exists(pool, OLD[1]) and not await _agent_exists(pool, OLD[2])


# ── The race with the import ──────────────────────────────────────────────────

async def test_signup_waits_for_an_import_releasing_the_address_then_loses(pool, http, OLD):
    """The import (exclusive lock) is mid-way: reservation deleted, agent row inserted,
    not committed. A sign-up for that DID must block, then get 409, never a row of its own."""
    assert run("load", "-", "--apply", stdin="\n".join(OLD)).returncode == 0
    importer = await asyncpg.connect(DSN)
    tx = importer.transaction()
    await tx.start()
    try:
        await reserve.lock_exclusive(importer)
        await importer.execute("DELETE FROM reserved_dids WHERE agent_did = $1", OLD[0])
        await importer.execute(
            "INSERT INTO agents (agent_did, display_name) VALUES ($1, 'The Real One')", OLD[0])

        signup = asyncio.create_task(
            http.post("/agents", json={"agent_did": OLD[0], "display_name": "Impostor"}))
        await asyncio.sleep(0.5)
        assert not signup.done(), "the sign-up must wait for the import"
        await tx.commit()
        r = await asyncio.wait_for(signup, 10)
    finally:
        await importer.close()      # rolls back if the commit above was never reached
    assert r.status_code == 409, r.text
    assert "already registered" in r.json()["detail"]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT display_name FROM agents WHERE agent_did = $1", OLD[0]) == "The Real One"


async def test_import_waits_for_a_signup_in_flight(pool, OLD):
    """A sign-up holding the shared lock (row inserted, not committed) keeps the loader
    waiting; once it commits, the loader sees the DID registered and does not reserve it."""
    did = OLD[1]
    signup = await asyncpg.connect(DSN)
    tx = signup.transaction()
    await tx.start()
    try:
        from src.services.reserved_dids import assert_not_reserved
        await assert_not_reserved(signup, did)
        await signup.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, 'Fast')", did)

        loader = await asyncpg.connect(DSN)
        try:
            load = asyncio.create_task(reserve.apply_load(loader, [did]))
            await asyncio.sleep(0.5)
            assert not load.done(), "the loader must wait for the sign-up"
            await tx.commit()
            assert await asyncio.wait_for(load, 10) == 0
        finally:
            await loader.close()
    finally:
        await signup.close()
    assert await _reserved(pool) == set()
    assert await _agent_exists(pool, did)


# ── Fail closed ───────────────────────────────────────────────────────────────

async def test_signup_is_refused_when_the_table_is_gone(pool, http, OLD):
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE reserved_dids")
    try:
        r = await http.post("/agents", json={"agent_did": OLD[0], "display_name": "Impostor"})
        assert r.status_code == 500, r.text
        assert not await _agent_exists(pool, OLD[0])
        r = await http.post("/onboard", json={"name": OLD[1][11:], "capabilities": ["x"]})
        assert r.status_code == 500, r.text
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM agents WHERE display_name = $1", OLD[1][11:]) == 0
    finally:
        # Put the table back exactly as migration 052 makes it (it is idempotent SQL).
        src = (PLATFORM / "alembic" / "versions" / "052_reserved_dids.py").read_text()
        ddl = src.split('op.execute("""', 1)[1].split('""")', 1)[0]
        async with pool.acquire() as conn:
            await conn.execute(ddl)
