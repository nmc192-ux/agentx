"""
EL-2: the old agents' addresses are held in `reserved_dids` until the 1 Nov import.

Runs everywhere (no database): the pure parts, the loader's parser, and the two
routes with a mocked connection. Both sign-up routes must refuse a reserved DID
and must NOT swallow a database error (fail closed). The real behaviour, the
race with the import and `/onboard` are in tests/integration/test_reserved_dids_db.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services import reserved_dids as rd

PLATFORM = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("reserve_dids", PLATFORM / "scripts" / "reserve_dids.py")
reserve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reserve)

OLD = "did:agentx:oldtimer-042"


# ── Pure parts ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [OLD, f"  {OLD}  ", OLD.upper(), f"\t{OLD}\n", "DID:AgentX:OldTimer-042"])
def test_normalize_did_folds_case_and_whitespace(raw):
    assert rd.normalize_did(raw) == OLD


@pytest.mark.parametrize("raw", [
    "", "   ", "oldtimer-042", "did:agentx:oldtimer", "did:agentx:oldtimer-42", "did:agentx:oldtimer-0042",
    "did:agentx:old timer-042", "did:agentx:old_timer-042", "did:web:oldtimer-042",
    "did:agentx:oldtimer-042'; DROP TABLE agents; --", "did:agentx:oldtimer-042\x00",
    "did:agentx:ôldtimer-042",
])
def test_normalize_did_refuses_anything_else(raw):
    with pytest.raises(ValueError):
        rd.normalize_did(raw)


def test_parse_did_list_normalises_dedupes_and_skips_comments_and_a_csv_header():
    text = f"agent_did\n# exported from Neon\n\n  {OLD.upper()} \n{OLD}\ndid:agentx:other-001\r\n"
    assert reserve.parse_did_list(text) == [OLD, "did:agentx:other-001"]


def test_parse_did_list_refuses_the_whole_file_on_one_bad_line():
    text = f"{OLD}\nnot a did\ndid:agentx:fine-001\n"
    with pytest.raises(reserve.ReserveRefused, match="line 2"):
        reserve.parse_did_list(text)


def test_image_ships_the_loader():
    assert "COPY scripts/reserve_dids.py ./scripts/reserve_dids.py" in (PLATFORM / "Dockerfile.fly").read_text()


def test_release_needs_dids_or_all(capsys):
    with pytest.raises(SystemExit):
        reserve.main(["release"])
    with pytest.raises(SystemExit):
        reserve.main(["release", "--all", OLD])


# ── Service helpers with a mocked connection ──────────────────────────────────

async def test_assert_not_reserved_takes_the_shared_lock_then_checks():
    conn = AsyncMock()
    conn.fetchval.return_value = None
    await rd.assert_not_reserved(conn, f" {OLD.upper()} ")
    assert conn.execute.await_args.args == ("SELECT pg_advisory_xact_lock_shared($1)", rd.LOCK_KEY)
    assert conn.fetchval.await_args.args[1] == OLD          # normalised before the query

    conn.fetchval.return_value = 1
    with pytest.raises(rd.DidReservedError):
        await rd.assert_not_reserved(conn, OLD)


async def test_database_errors_are_not_swallowed():
    conn = AsyncMock()
    conn.fetchval.side_effect = asyncpg.UndefinedTableError("relation reserved_dids does not exist")
    with pytest.raises(asyncpg.UndefinedTableError):
        await rd.assert_not_reserved(conn, OLD)
    with pytest.raises(asyncpg.UndefinedTableError):
        await rd.pick_free_did(conn, lambda: OLD)


async def test_pick_free_did_rerolls_until_free_then_gives_up():
    conn = AsyncMock()
    conn.fetchval.side_effect = [False, False, True]
    draws = iter(["did:agentx:a-001", "did:agentx:a-002", "did:agentx:a-003"])
    assert await rd.pick_free_did(conn, lambda: next(draws)) == "did:agentx:a-003"

    conn.fetchval.side_effect = None
    conn.fetchval.return_value = False
    with pytest.raises(RuntimeError):
        await rd.pick_free_did(conn, lambda: OLD, attempts=4)
    assert conn.fetchval.await_count == 3 + 4


# ── Routes ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from src.middleware.rate_limits import limiter
    limiter.reset()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c


def _mock_tx(conn):
    tx = patch("src.routers.agents.transaction")
    m = tx.start()
    m.return_value.__aenter__ = AsyncMock(return_value=conn)
    m.return_value.__aexit__ = AsyncMock(return_value=False)
    return tx


def _inserted_agents(conn) -> list:
    return [c for c in conn.execute.await_args_list if "INSERT INTO agents" in c.args[0]]


async def test_post_agents_refuses_a_reserved_did_without_writing(client):
    conn = AsyncMock()
    # 1st fetchval: uniqueness (free); 2nd: reserved_dids (held).
    conn.fetchval.side_effect = [None, 1]
    tx = _mock_tx(conn)
    try:
        r = await client.post("/agents", json={"agent_did": OLD, "display_name": "Impostor"})
    finally:
        tx.stop()
    assert r.status_code == 409, r.text
    assert "reserved" in r.json()["detail"]
    assert _inserted_agents(conn) == []


async def test_post_agents_fails_closed_when_the_table_is_unreadable(client):
    conn = AsyncMock()
    conn.fetchval.side_effect = [None, asyncpg.UndefinedTableError("no reserved_dids")]
    tx = _mock_tx(conn)
    try:
        r = await client.post("/agents", json={"agent_did": OLD, "display_name": "Impostor"})
    finally:
        tx.stop()
    assert r.status_code == 500
    assert _inserted_agents(conn) == []


async def test_post_agents_maps_a_lost_race_with_the_import_to_409(client):
    """Check passed, then the import committed this DID: the primary key wins, 409 not 500."""
    conn = AsyncMock()
    conn.fetchval.side_effect = [None, None]

    async def execute(sql, *args):
        if "INSERT INTO agents" in sql:
            raise asyncpg.UniqueViolationError("agents_pkey")
    conn.execute.side_effect = execute
    tx = _mock_tx(conn)
    try:
        r = await client.post("/agents", json={"agent_did": OLD, "display_name": "Late"})
    finally:
        tx.stop()
    assert r.status_code == 409
    assert "already registered" in r.json()["detail"]


@pytest.mark.parametrize("variant", [OLD.upper(), f" {OLD}", f"{OLD} ", f"{OLD}\n"])
async def test_post_agents_rejects_case_and_whitespace_variants_before_any_query(client, variant):
    conn = AsyncMock()
    tx = _mock_tx(conn)
    try:
        r = await client.post("/agents", json={"agent_did": variant, "display_name": "Impostor"})
    finally:
        tx.stop()
    assert r.status_code == 422
    assert conn.fetchval.await_count == 0 and conn.execute.await_count == 0


async def test_register_route_rerolls_a_reserved_or_taken_draw(client):
    conn = AsyncMock()
    conn.fetchval.side_effect = [False, False, True]     # two draws taken, third free
    conn.fetchrow.return_value = {
        "agent_id": "11111111-1111-1111-1111-111111111111", "name": "w", "description": "d",
        "skills": [], "capabilities": [], "endpoint": "http://w", "owner": "o",
        "display_name": "w", "bio": "d", "trust_score": 0.5,
        "created_at": __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
    }
    tx = _mock_tx(conn)
    try:
        with patch("src.routers.agents._make_agent_did",
                   side_effect=["did:agentx:w-001", "did:agentx:w-002", "did:agentx:w-003"]):
            r = await client.post("/agents/register", json={
                "name": "w", "description": "d", "skills": [], "capabilities": [], "endpoint": "http://w", "owner": "o",
            })
    finally:
        tx.stop()
    assert r.status_code == 201, r.text
    assert _inserted_agents(conn)[0].args[2] == "did:agentx:w-003"


async def test_register_route_gives_up_with_503_when_every_draw_is_held(client):
    conn = AsyncMock()
    conn.fetchval.return_value = False
    tx = _mock_tx(conn)
    try:
        r = await client.post("/agents/register", json={
            "name": "w", "description": "d", "skills": [], "capabilities": [], "endpoint": "http://w", "owner": "o",
        })
    finally:
        tx.stop()
    assert r.status_code == 503
    assert _inserted_agents(conn) == []
