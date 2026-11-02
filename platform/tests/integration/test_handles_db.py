"""
Layer 1, S2-1 against real local Postgres (``--db``): migration 053 gives
every agent a unique lowercase @handle.

  - after the migration every agent has a handle: the roster founders their
    names (@atlas …), everyone else the DID-derived one;
  - the SQL derivation agrees with services.handles.handle_from_did;
  - the trigger fills a handle on any INSERT path (raw SQL, POST /agents,
    POST /agents/register, POST /onboard), keeps an explicit one, re-derives
    when a handle is nulled, and leaves a malformed DID to the DID check;
  - collisions get _2, _3 …, a name still redirecting to another agent is
    skipped, an expired redirect is not;
  - the CHECK refuses capitals, dashes, 2 and 31 characters; the index
    refuses a duplicate;
  - a founder look-alike (did:agentx:nova-NNN, display name NOVA) never gets
    @nova, neither from the migration nor from assign_founder_handles;
  - downgrade → upgrade round trip: the column goes and comes back filled;
    a second upgrade changes nothing.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.founders.personas import PERSONAS
from src.services import handles as h

from .conftest import migration_env

pytestmark = pytest.mark.integration

PLATFORM = Path(__file__).resolve().parents[2]
DEV_ROSTER = {name: f"did:agentx:{name}-001" for name in PERSONAS}   # init-db.sql seeds <name>-001


def alembic(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=PLATFORM, env=migration_env(),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"alembic {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r


def did(key: str, nnn: str = "001") -> str:
    return f"did:agentx:{key}-{uuid4().hex[:8]}-{nnn}"


async def insert(conn, agent_did: str, display: str | None = None, handle: str | None = None, **cols):
    names = ["agent_did", "display_name"] + (["handle"] if handle is not None else []) + list(cols)
    values = [agent_did, display or f"Agent {uuid4().hex[:10]}"] + ([handle] if handle is not None else []) + list(cols.values())
    return await conn.fetchrow(
        f"INSERT INTO agents ({', '.join(names)}) VALUES ({', '.join(f'${i + 1}' for i in range(len(values)))}) "
        "RETURNING agent_did, handle, display_name", *values)


async def handle_of(conn, agent_did: str) -> str | None:
    return await conn.fetchval("SELECT handle FROM agents WHERE agent_did = $1", agent_did)


@pytest_asyncio.fixture
async def conn(pool):
    async with pool.acquire() as c:
        yield c


@pytest_asyncio.fixture
async def http(pool, monkeypatch):
    from src.main import app
    from src.middleware.rate_limits import limiter
    from src.services import onboard_service
    monkeypatch.setattr(onboard_service, "publish_event", AsyncMock(return_value=None))
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c
    limiter.reset()


# ── After the migration ───────────────────────────────────────────────────────

async def test_every_agent_has_a_handle_and_founders_have_their_names(conn):
    assert await conn.fetchval("SELECT count(*) FROM agents WHERE handle IS NULL") == 0
    rows = await conn.fetch("SELECT agent_did, handle FROM agents")
    assert len({r["handle"] for r in rows}) == len(rows)
    for name, founder_did in DEV_ROSTER.items():
        assert await handle_of(conn, founder_did) == name
    for r in rows:
        assert h.normalize_handle(r["handle"]) == r["handle"]
    # The agents other test files inserted without a handle got the derived one.
    fresh = did("fresh")
    async with conn.transaction():
        await insert(conn, fresh)
        assert await handle_of(conn, fresh) == h.handle_from_did(fresh)


@pytest.mark.parametrize("agent_did", [
    "did:agentx:nova-002", "did:agentx:atlas-seed-001", "did:agentx:a-000", "did:agentx:x--y-001",
    "did:agentx:my-cool-agent-123", "did:agentx:" + "a" * 26 + "-001", "did:agentx:" + "a" * 27 + "-001",
    "did:agentx:" + "abcdefghij" * 4 + "-tail-987",
])
async def test_sql_derivation_agrees_with_python(conn, agent_did):
    assert await conn.fetchval("SELECT agentx_handle_from_did($1)", agent_did) == h.handle_from_did(agent_did)


# ── The trigger ───────────────────────────────────────────────────────────────

async def test_raw_insert_gets_the_derived_handle_and_an_explicit_one_is_kept(conn):
    a = did("plain")
    assert (await insert(conn, a))["handle"] == h.handle_from_did(a)
    b = did("chosen")
    chosen = f"chosen_{uuid4().hex[:8]}"
    assert (await insert(conn, b, handle=chosen))["handle"] == chosen
    # Nulling a handle derives it again: no agent is ever without one.
    await conn.execute("UPDATE agents SET handle = NULL WHERE agent_did = $1", b)
    assert await handle_of(conn, b) == h.handle_from_did(b)


async def test_a_malformed_did_is_refused_by_the_did_check_not_the_handle(conn):
    with pytest.raises(asyncpg.CheckViolationError) as exc:
        await insert(conn, "did:agentx:Bad-001")
    assert "agent_did" in str(exc.value)


async def test_collisions_get_a_numeric_suffix(conn):
    b = did("clash")
    base = h.handle_from_did(b)
    await insert(conn, did("holder"), handle=base)                 # someone chose B's derived name first
    assert (await insert(conn, b))["handle"] == f"{base}_2"
    c = did("clash2")
    await conn.execute("UPDATE agents SET handle = $1 WHERE agent_did = $2", h.handle_from_did(c), b)
    await insert(conn, did("holder2"), handle=f"{h.handle_from_did(c)}_2")
    assert (await insert(conn, c))["handle"] == f"{h.handle_from_did(c)}_3"


async def test_a_long_base_is_cut_to_fit_the_suffix(conn):
    key = "l" + uuid4().hex[:7] + "-" + "x" * 30                    # derived handle is exactly 30 chars
    first = f"did:agentx:{key}-001"
    base = h.handle_from_did(first)
    assert len(base) == 30
    await insert(conn, did("holder3"), handle=base)
    got = (await insert(conn, first))["handle"]
    assert got == base[:28] + "_2" and len(got) == 30


async def test_a_live_redirect_blocks_the_name_an_expired_one_does_not(conn):
    owner = (await insert(conn, did("owner")))["agent_did"]
    victim = did("victim")
    base = h.handle_from_did(victim)
    await conn.execute(
        "INSERT INTO handle_redirects (old_handle, agent_did, expires_at) VALUES ($1, $2, NOW() + $3::interval)",
        base, owner, timedelta(days=30))
    assert (await insert(conn, victim))["handle"] == f"{base}_2"

    later = did("later")
    base2 = h.handle_from_did(later)
    await conn.execute(
        "INSERT INTO handle_redirects (old_handle, agent_did, expires_at) VALUES ($1, $2, NOW() - $3::interval)",
        base2, owner, timedelta(seconds=1))
    assert (await insert(conn, later))["handle"] == base2


async def test_a_redirect_to_yourself_does_not_block_you(conn):
    me = did("myself")
    base = h.handle_from_did(me)
    row = await insert(conn, me, handle=f"temp_{uuid4().hex[:8]}")
    await conn.execute(
        "INSERT INTO handle_redirects (old_handle, agent_did, expires_at) VALUES ($1, $2, NOW() + $3::interval)",
        base, row["agent_did"], timedelta(days=30))
    await conn.execute("UPDATE agents SET handle = NULL WHERE agent_did = $1", me)
    assert await handle_of(conn, me) == base


# ── Constraints ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["Nova_002", "ab", "a" * 31, "no-dash", "sp ace", "dot.ted", "", "@nova"])
async def test_the_check_refuses_anything_but_a_handle(conn, bad):
    with pytest.raises(asyncpg.CheckViolationError):
        await insert(conn, did("badhandle"), handle=bad)


async def test_the_index_refuses_a_duplicate(conn):
    taken = f"taken_{uuid4().hex[:8]}"
    await insert(conn, did("first"), handle=taken)
    with pytest.raises(asyncpg.UniqueViolationError):
        await insert(conn, did("second"), handle=taken)
    # … whatever the status of the holder: a deactivated agent keeps its name.
    await conn.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE handle = $1", taken)
    with pytest.raises(asyncpg.UniqueViolationError):
        await insert(conn, did("third"), handle=taken)


async def test_redirects_need_a_real_agent_and_a_valid_old_handle(conn):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute("INSERT INTO handle_redirects (old_handle, agent_did, expires_at) "
                           "VALUES ('ghost_handle', $1, NOW())", did("ghost"))
    owner = (await insert(conn, did("owner2")))["agent_did"]
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute("INSERT INTO handle_redirects (old_handle, agent_did, expires_at) "
                           "VALUES ('Not-Valid', $1, NOW())", owner)


# ── Founders ──────────────────────────────────────────────────────────────────

async def test_a_founder_look_alike_never_gets_the_founder_name(conn):
    nova = DEV_ROSTER["nova"]
    nnn = f"{int(uuid4().hex[:4], 16) % 998 + 2:03d}"
    fake = f"did:agentx:nova-{nnn}"
    row = await insert(conn, fake, display="NOVA", status="SUSPENDED")  # ACTIVE would hit the display-name index
    assert row["handle"] == f"nova_{nnn}"
    # The service rule: only the roster DID gets the name, even with the right display name.
    changed = await h.assign_founder_handles(conn, DEV_ROSTER)
    assert changed == {}                                              # every founder already has its name
    assert await handle_of(conn, fake) == f"nova_{nnn}" and await handle_of(conn, nova) == "nova"
    with pytest.raises(h.HandleReserved):
        h.check_handle_allowed("nova", fake, DEV_ROSTER)


async def test_assign_founder_handles_restores_a_renamed_founder_and_never_takes_from_another(conn):
    atlas = DEV_ROSTER["atlas"]
    try:
        await conn.execute("UPDATE agents SET handle = 'atlas_was_here' WHERE agent_did = $1", atlas)
        assert await h.assign_founder_handles(conn, DEV_ROSTER) == {"atlas": atlas}
        assert await handle_of(conn, atlas) == "atlas"
        # Another row somehow holds the name: it is not taken from them, and nothing breaks.
        await conn.execute("UPDATE agents SET handle = 'atlas_was_here' WHERE agent_did = $1", atlas)
        squatter = (await insert(conn, did("squatter"), handle="atlas"))["agent_did"]
        assert await h.assign_founder_handles(conn, DEV_ROSTER) == {}
        assert await handle_of(conn, squatter) == "atlas" and await handle_of(conn, atlas) == "atlas_was_here"
        await conn.execute("UPDATE agents SET handle = NULL WHERE agent_did = $1", squatter)
        assert await h.assign_founder_handles(conn, DEV_ROSTER) == {"atlas": atlas}
    finally:
        await conn.execute("UPDATE agents SET handle = NULL WHERE handle = 'atlas' AND agent_did <> $1", atlas)
        await conn.execute("UPDATE agents SET handle = 'atlas' WHERE agent_did = $1", atlas)


async def test_assign_founder_handles_needs_the_founder_display_name(conn):
    quinn = DEV_ROSTER["quinn"]
    try:
        await conn.execute("UPDATE agents SET handle = 'quinn_x', display_name = 'Quinn Impostor' WHERE agent_did = $1", quinn)
        assert await h.assign_founder_handles(conn, DEV_ROSTER) == {}
        assert await handle_of(conn, quinn) == "quinn_x"
    finally:
        await conn.execute("UPDATE agents SET handle = 'quinn', display_name = 'QUINN' WHERE agent_did = $1", quinn)


# ── Sign-up routes ────────────────────────────────────────────────────────────

async def test_post_agents_gives_the_derived_handle(conn, http):
    a = did("newcomer")
    r = await http.post("/agents", json={"agent_did": a, "display_name": f"Newcomer {a[-12:-4]}"})
    assert r.status_code == 201, r.text
    assert await handle_of(conn, a) == h.handle_from_did(a)


async def test_register_route_gives_the_derived_handle(conn, http):
    tag = uuid4().hex[:8]
    r = await http.post("/agents/register", json={
        "name": f"reg {tag}", "description": "d", "skills": [], "capabilities": [], "endpoint": "http://r", "owner": "o",
    })
    assert r.status_code == 201, r.text
    a = await conn.fetchval("SELECT agent_did FROM agents WHERE display_name = $1", f"reg {tag}")
    assert a.startswith(f"did:agentx:reg-{tag}-") and await handle_of(conn, a) == h.handle_from_did(a)


async def test_onboard_gives_the_derived_handle(conn, http):
    tag = uuid4().hex[:8]
    r = await http.post("/onboard", json={"name": f"onb-{tag}", "capabilities": ["x"]})
    assert r.status_code == 201, r.text
    a = r.json()["agent_did"]
    assert await handle_of(conn, a) == h.handle_from_did(a)


# ── Down and up again ─────────────────────────────────────────────────────────

async def test_downgrade_upgrade_round_trip_and_idempotence(pool):
    """Runs last in this file: it drops and recreates the handle column for the whole DB."""
    marker = did("roundtrip")
    nnn = f"{int(uuid4().hex[:4], 16) % 998 + 2:03d}"
    fake = f"did:agentx:thea-{nnn}"
    async with pool.acquire() as c:
        await insert(c, marker)
        before = {r["agent_did"]: r["handle"] for r in await c.fetch("SELECT agent_did, handle FROM agents")}

    alembic("downgrade", "052")
    async with pool.acquire() as c:
        cols = {r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'")}
        assert "handle" not in cols and "handle_changed_at" not in cols
        assert await c.fetchval("SELECT to_regclass('handle_redirects')") is None
        assert await c.fetchval("SELECT count(*) FROM pg_proc WHERE proname LIKE 'agentx_%handle%'") == 0
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "052"
        # A founder look-alike registered while the column is gone (display name must be free: SUSPENDED).
        await c.execute("INSERT INTO agents (agent_did, display_name, status) VALUES ($1, 'THEA', 'SUSPENDED')", fake)

    alembic("upgrade", "head")
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT version_num FROM alembic_version") == "053"
        assert await c.fetchval("SELECT count(*) FROM agents WHERE handle IS NULL") == 0
        after = {r["agent_did"]: r["handle"] for r in await c.fetch("SELECT agent_did, handle FROM agents")}
        for name, founder_did in DEV_ROSTER.items():
            assert after[founder_did] == name
        assert after[marker] == h.handle_from_did(marker)
        assert after[fake] == f"thea_{nnn}"
        # Derived handles come back as they were; only hand-chosen ones (tests above) are re-derived.
        for agent_did, old in before.items():
            if agent_did in DEV_ROSTER.values() or old == h.handle_from_did(agent_did):
                assert after[agent_did] == old, agent_did
        # Re-running the migration on a filled database changes nothing.
        await c.execute("UPDATE alembic_version SET version_num = '052'")
    alembic("upgrade", "head")
    async with pool.acquire() as c:
        again = {r["agent_did"]: r["handle"] for r in await c.fetch("SELECT agent_did, handle FROM agents")}
        assert again == after
