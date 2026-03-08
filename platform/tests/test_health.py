"""
Tests: GET /health and GET /health/ready
Sprint 1 — QUINN Gap 1.6 (CI gates) + acceptance criteria DoD item 4.

These are the first tests written for the platform.
Run with:  pytest tests/test_health.py -v
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from src.main import app


@pytest.fixture
async def client():
    """Async test client using ASGITransport (no real server needed)."""
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Liveness ─────────────────────────────────────────────────────────────────

class TestHealthLiveness:
    """GET /health — always returns 200 if process is alive."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_ok_status(self, client):
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_returns_version(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "version" in data
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_health_returns_env(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "env" in data

    @pytest.mark.asyncio
    async def test_health_request_id_in_response(self, client):
        """Every response must include X-Request-ID header (tracing)."""
        response = await client.get("/health")
        assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_health_custom_request_id_preserved(self, client):
        """If client sends X-Request-ID, it must echo back the same value."""
        custom_id = "test-request-abc-123"
        response = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers["X-Request-ID"] == custom_id

    @pytest.mark.asyncio
    async def test_health_not_rate_limited_at_reasonable_volume(self, client):
        """
        /health should handle high-frequency monitoring polls without 429.
        (QUINN Gap 1.5: health check is excluded from rate limiting)
        """
        for _ in range(20):
            response = await client.get("/health")
            assert response.status_code == 200, f"Got {response.status_code} on poll"


# ── Readiness ────────────────────────────────────────────────────────────────

class TestHealthReadiness:
    """GET /health/ready — checks DB and cache are reachable."""

    @pytest.mark.asyncio
    async def test_ready_returns_200_when_all_healthy(self, client):
        """When DB and cache are both healthy, returns 200."""
        with (
            patch("src.main.check_db_health",    new=AsyncMock(return_value={"status": "ok", "pg_version": "16.1"})),
            patch("src.main.check_cache_health",  new=AsyncMock(return_value={"status": "ok", "redis_version": "7.2"})),
        ):
            response = await client.get("/health/ready")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ready_returns_ok_status(self, client):
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value={"status": "ok"})),
            patch("src.main.check_cache_health", new=AsyncMock(return_value={"status": "ok"})),
        ):
            data = (await client.get("/health/ready")).json()
            assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ready_returns_503_when_db_down(self, client):
        """QUINN Gap 3.1: Dependency failure must return 503, not 200."""
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value={"status": "error", "detail": "connection refused"})),
            patch("src.main.check_cache_health", new=AsyncMock(return_value={"status": "ok"})),
        ):
            response = await client.get("/health/ready")
            assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_ready_returns_503_when_cache_down(self, client):
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value={"status": "ok"})),
            patch("src.main.check_cache_health", new=AsyncMock(return_value={"status": "error", "detail": "NOAUTH"})),
        ):
            response = await client.get("/health/ready")
            assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_ready_returns_503_when_both_down(self, client):
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value={"status": "error"})),
            patch("src.main.check_cache_health", new=AsyncMock(return_value={"status": "error"})),
        ):
            response = await client.get("/health/ready")
            assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_ready_response_includes_dependency_details(self, client):
        """Response body must name each dependency and its status."""
        db_info    = {"status": "ok", "pg_version": "16.1"}
        cache_info = {"status": "ok", "redis_version": "7.2"}
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value=db_info)),
            patch("src.main.check_cache_health", new=AsyncMock(return_value=cache_info)),
        ):
            data = (await client.get("/health/ready")).json()
            assert "dependencies" in data
            assert "database" in data["dependencies"]
            assert "cache" in data["dependencies"]

    @pytest.mark.asyncio
    async def test_ready_degraded_status_when_partially_down(self, client):
        """When one dependency is down, status should be 'degraded'."""
        with (
            patch("src.main.check_db_health",   new=AsyncMock(return_value={"status": "error"})),
            patch("src.main.check_cache_health", new=AsyncMock(return_value={"status": "ok"})),
        ):
            data = (await client.get("/health/ready")).json()
            assert data["status"] == "degraded"
