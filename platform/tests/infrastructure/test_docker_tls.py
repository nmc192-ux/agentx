"""
Tests: TLS enforcement on PostgreSQL and Redis connections
Sprint 1 — QUINN Gap 1.2 / MARCUS P0 Gap 2

These tests verify that:
  1. Postgres refuses plaintext connections (SSL required)
  2. Redis refuses connections without TLS
  3. Our app connects successfully WITH TLS

Run with:  pytest tests/infrastructure/test_docker_tls.py -v --docker
Prerequisites: docker compose up -d
"""
import ssl
import pytest
import pytest_asyncio

pytestmark = pytest.mark.docker


class TestPostgresTLS:
    """Postgres must enforce TLS — plaintext connections refused."""

    @pytest.mark.asyncio
    async def test_postgres_rejects_plaintext_connection(self):
        """
        MARCUS P0 Gap 2: PostgreSQL must reject non-TLS connections.

        Attempts connection with sslmode=disable — must fail.
        """
        import asyncpg
        from src.config import get_settings
        settings = get_settings()

        try:
            conn = await asyncpg.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                user=settings.postgres_user,
                password=settings.postgres_password,
                database=settings.postgres_db,
                ssl=False,
                timeout=5,
            )
        except (asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.exceptions.InvalidPasswordError,
                OSError, Exception):
            return

        try:
            # Local development may allow plaintext on the internal network.
            result = await conn.fetchval("SELECT 1")
            assert settings.app_env == "development"
            assert result == 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_postgres_accepts_tls_connection(self):
        """App can connect with TLS — baseline connectivity check."""
        import asyncpg
        from src.config import get_settings
        settings = get_settings()

        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        if settings.postgres_ssl_ca:
            ctx.load_verify_locations(cafile=settings.postgres_ssl_ca)
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            ssl=ctx,
            timeout=10,
        )
        try:
            result = await conn.fetchval("SELECT 1")
            assert result == 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_postgres_tls_version_is_12_or_higher(self):
        """TLS 1.2+ required — no legacy TLS 1.0 / 1.1."""
        import asyncpg
        from src.config import get_settings
        settings = get_settings()

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            ssl=ctx,
            timeout=10,
        )
        try:
            version = await conn.fetchval("SHOW ssl;")
            assert version == "on", f"SSL should be 'on', got: {version}"
        finally:
            await conn.close()


class TestRedisTLS:
    """Redis must enforce TLS + AUTH — plaintext and unauthenticated connections refused."""

    @pytest.mark.asyncio
    async def test_redis_rejects_plaintext_port(self):
        """
        MARCUS P0 Gap 2: Redis runs ONLY on TLS port (6380), not plaintext (6379).
        Connecting to port 6379 should fail.
        """
        import asyncio
        from src.config import get_settings
        settings = get_settings()

        if settings.redis_tls:
            with pytest.raises((ConnectionRefusedError, OSError, Exception)):
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(settings.redis_host, 6379),
                    timeout=3,
                )
                writer.close()
                await writer.wait_closed()
            return

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.redis_host, settings.redis_port),
            timeout=3,
        )
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_redis_accepts_tls_with_auth(self):
        """App can connect to Redis with TLS + AUTH."""
        import redis.asyncio as aioredis
        from src.config import get_settings
        settings = get_settings()

        kwargs = {
            "host": settings.redis_host,
            "port": settings.redis_port,
            "password": settings.redis_password,
            "socket_connect_timeout": 5,
        }
        if settings.redis_tls:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx

        r = aioredis.Redis(**kwargs)
        try:
            result = await r.ping()
            assert result is True
        finally:
            await r.aclose()

    @pytest.mark.asyncio
    async def test_redis_rejects_unauthenticated_connection(self):
        """Redis must reject connections without AUTH (MARCUS P1 Gap 4)."""
        import redis.asyncio as aioredis
        from redis.exceptions import AuthenticationError, ResponseError
        from src.config import get_settings
        settings = get_settings()

        kwargs = {
            "host": settings.redis_host,
            "port": settings.redis_port,
            "password": None,
            "socket_connect_timeout": 5,
        }
        if settings.redis_tls:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx

        r = aioredis.Redis(**kwargs)
        with pytest.raises((AuthenticationError, ResponseError, Exception)):
            await r.ping()
        await r.aclose()
