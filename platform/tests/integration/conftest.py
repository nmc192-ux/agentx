"""
Fixtures for the integration tests that run against REAL local Postgres
(Sprint 9, S9-6a / S9-6b). Skipped unless pytest is given ``--db``.

Every request goes HTTP → router → service → Postgres. Only the JWT check is
replaced (the caller is set per request) and the Redis event bus is silenced;
no money path is mocked.

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration -v --db

The tests build their own throwaway database, `agentx_smoke_escrow` (same
init-db.sql → alembic chain as scripts/smoke_routers.py and CI), on localhost
only, and never touch any other database.
"""
from __future__ import annotations

import getpass
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient

from .support import Agent

_PLATFORM_DIR = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "smoke_routers", _PLATFORM_DIR / "scripts" / "smoke_routers.py"
)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

DB_NAME = f"{smoke.DB_PREFIX}_escrow"
PG_USER = getpass.getuser()
PG_PORT = os.getenv("ESCROW_TEST_PG_PORT", "5432")


# ── Database ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def escrow_db():
    """Rebuild the throwaway database once per test run (localhost only)."""
    env = {
        **{k: v for k, v in os.environ.items()
           if not k.startswith(("POSTGRES_", "REDIS_", "DISABLED_ROUTERS"))},
        "APP_ENV": "development",
        "POSTGRES_HOST": smoke.DB_HOST,
        "POSTGRES_PORT": PG_PORT,
        "POSTGRES_USER": PG_USER,
        "POSTGRES_DB": DB_NAME,
        "POSTGRES_PASSWORD": smoke.SMOKE_DB_PASSWORD,
        "POSTGRES_SSL_MODE": "disable",
        "REDIS_URL": smoke.SMOKE_REDIS_URL,
        "REDIS_PASSWORD": "smoke-unused",
        "JWT_SECRET": smoke.SMOKE_JWT_SECRET,
        "SENTRY_DSN": "",
    }
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return DB_NAME


@pytest_asyncio.fixture
async def pool(escrow_db, monkeypatch):
    """A real pool on the throwaway DB, installed as the app's pool."""
    import src.database as database
    from src.services import contract_service, task_service, verification_service

    pg_pool = await asyncpg.create_pool(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=escrow_db,
        min_size=2, max_size=20, command_timeout=30,
    )
    monkeypatch.setattr(database, "_pool", pg_pool)
    # Redis event bus: not under test, keep the run DB-only.
    for service in (task_service, contract_service, verification_service):
        monkeypatch.setattr(service, "publish_event", AsyncMock(return_value=None))
    yield pg_pool
    await pg_pool.close()


@pytest_asyncio.fixture
async def client(pool):
    from src.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as c:
        yield c


# ── Callers ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def agents(pool):
    """Factory: create an agent (optionally with a funded wallet)."""
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord, get_current_agent
    from src.main import app

    registry: dict[str, Agent] = {}

    async def make(name: str, balance: int | None = None, role: str = "MEMBER") -> Agent:
        did = f"did:agentx:{name}-{uuid4().hex[:8]}-001"
        async with pool.acquire() as conn:
            agent_id = await conn.fetchval(
                """
                INSERT INTO agents (agent_did, display_name, governance_role)
                VALUES ($1, $2, $3::governance_role)
                RETURNING agent_id
                """,
                did, f"{name}-{uuid4().hex[:10]}", role,
            )
            if balance is not None:
                await conn.execute(
                    "INSERT INTO wallets (agent_id, balance) VALUES ($1, $2)",
                    agent_id, balance,
                )
        registry[did] = Agent(did, agent_id, role)
        return registry[did]

    # Stand-in for JWT validation ONLY: the caller is whoever X-Test-Caller
    # names (must be an agent made above); no header → 401, like a missing token.
    async def _current_agent(request: Request) -> AgentRecord:
        did = request.headers.get("X-Test-Caller")
        if did not in registry:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        claims = MagicMock(spec=TokenClaims)
        claims.agent_did = did
        return AgentRecord(
            row={
                "agent_did": did, "display_name": did, "governance_role": registry[did].role,
                "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5,
            },
            claims=claims,
        )

    app.dependency_overrides[get_current_agent] = _current_agent
    try:
        yield make
    finally:
        app.dependency_overrides.pop(get_current_agent, None)
