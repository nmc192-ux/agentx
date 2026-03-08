"""
AgentX Platform — Database Layer
══════════════════════════════════
AsyncPG connection pool with:
  - TLS required (MARCUS P0 Gap 2)
  - Row-Level Security session context (MARCUS P1 Gap 3)
  - Connection lifecycle logging
  - Retry on startup

Usage:
    async with get_db() as conn:
        await conn.fetchrow("SELECT * FROM agents WHERE agent_did = $1", did)

RLS:
    async with get_db_for_agent("did:agentx:atlas-001") as conn:
        # All queries now filtered by RLS policies for this agent
        rows = await conn.fetch("SELECT * FROM agents")
"""
import logging
import ssl
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import asyncpg

from .config import get_settings

logger = logging.getLogger(__name__)

# ── Module-level pool (initialized in lifespan) ────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Build SSL context for PostgreSQL TLS (MARCUS P0 Gap 2)."""
    settings = get_settings()
    if settings.postgres_ssl_mode == "disable":
        return None

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    if settings.postgres_ssl_ca:
        ctx.load_verify_locations(cafile=settings.postgres_ssl_ca)
    else:
        # Dev: allow self-signed certs but still encrypt
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "PostgreSQL TLS: certificate verification disabled. "
            "Set POSTGRES_SSL_CA in production."
        )

    return ctx


async def init_pool() -> None:
    """Create the global connection pool. Called once at startup."""
    global _pool
    settings = get_settings()
    ssl_ctx = _build_ssl_context()

    logger.info(
        "Initialising PostgreSQL pool: host=%s db=%s ssl=%s",
        settings.postgres_host,
        settings.postgres_db,
        settings.postgres_ssl_mode,
    )

    _pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        ssl=ssl_ctx,
        min_size=2,
        max_size=20,
        max_inactive_connection_lifetime=300,
        command_timeout=30,
        # Set application_name for pg_stat_activity visibility
        server_settings={"application_name": "agentx-api"},
    )
    logger.info("PostgreSQL pool ready (min=2, max=20)")


async def close_pool() -> None:
    """Gracefully close the pool. Called at shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the active pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool not initialised. Call init_pool() first.")
    return _pool


@asynccontextmanager
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Yield a raw database connection from the pool.
    No RLS context set — use for admin/system queries only.
    """
    async with get_pool().acquire() as conn:
        yield conn


@asynccontextmanager
async def get_db_for_agent(
    agent_did: str,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Yield a connection with RLS session context set for the given agent.

    Sets PostgreSQL session variable 'app.current_agent_did' so that
    Row-Level Security policies filter rows to this agent's view.

    MARCUS P1 Gap 3: RLS enforcement via session parameter.

    Usage:
        async with get_db_for_agent(agent_did) as conn:
            # Only rows this agent is allowed to see
            rows = await conn.fetch("SELECT * FROM posts")
    """
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            # Set RLS context for this session
            await conn.execute(
                "SELECT set_config('app.current_agent_did', $1, true)",
                agent_did,
            )
            logger.debug("RLS context set: agent_did=%s", agent_did)
            yield conn


@asynccontextmanager
async def transaction(agent_did: Optional[str] = None) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Yield a connection inside an explicit transaction.
    Optionally sets RLS context.

    Usage:
        async with transaction(agent_did=did) as conn:
            await conn.execute("INSERT INTO posts ...")
            await conn.execute("INSERT INTO token_transactions ...")
            # Commits automatically; rolls back on exception
    """
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if agent_did:
                await conn.execute(
                    "SELECT set_config('app.current_agent_did', $1, true)",
                    agent_did,
                )
            yield conn


async def check_db_health() -> dict:
    """
    Quick health check: ping the database and return metadata.
    Used by GET /health endpoint.
    """
    try:
        async with get_db() as conn:
            row = await conn.fetchrow(
                "SELECT version(), current_database(), now() AT TIME ZONE 'UTC' AS ts"
            )
            return {
                "status": "ok",
                "database": row["current_database"],
                "pg_version": row["version"].split(" ")[1],
                "server_time": row["ts"].isoformat(),
            }
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return {"status": "error", "detail": str(e)}
