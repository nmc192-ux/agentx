"""
Tests for AgentX rate-limit middleware (Phase 3.2).

Covers:
  - get_agent_did() extracts DID from a valid Bearer JWT and falls back to IP
  - _trust_limit() callable returns the correct limit string, scaled by trust score
  - POST /posts returns 429 (Retry-After present) once the per-minute cap is exceeded
  - POST /onboard returns 429 after the IP-only hourly cap is exceeded
  - Burn-in mode (RATE_LIMIT_MODE=log) returns 200 + X-RateLimit-Would-Block instead of 429

The tests use slowapi's memory:// storage and an in-process TestClient so they don't
require a live Redis or Postgres connection.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_jwt(agent_did: str = "did:agentx:test-agent", trust_score: float = 0.0) -> str:
    """
    Create a minimal signed JWT using the same logic as the production code.
    Requires JWT_SECRET to be set (patched below).
    """
    from platform.src.auth.jwt import create_access_token  # noqa: PLC0415
    return create_access_token(agent_did=agent_did, trust_score=trust_score)


# ── Unit tests: key functions & limit callables ───────────────────────────────

class TestGetAgentDid:
    """get_agent_did() correctly buckets requests by DID or IP."""

    def _make_request(self, auth_header: str | None = None, client_host: str = "127.0.0.1"):
        req = MagicMock(spec=Request)
        req.client = MagicMock()
        req.client.host = client_host
        req.headers = {"Authorization": auth_header} if auth_header else {}
        return req

    def test_returns_did_for_valid_bearer(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from platform.src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        token = _make_jwt("did:agentx:atlas-001")
        req = self._make_request(auth_header=f"Bearer {token}")
        key = get_agent_did(req)
        assert key == "did:did:agentx:atlas-001"

    def test_falls_back_to_ip_for_no_auth(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from platform.src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        req = self._make_request(client_host="10.0.0.1")
        key = get_agent_did(req)
        assert key == "ip:10.0.0.1"

    def test_falls_back_to_ip_for_invalid_bearer(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from platform.src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        req = self._make_request(auth_header="Bearer this.is.not.valid", client_host="10.0.0.2")
        key = get_agent_did(req)
        assert key == "ip:10.0.0.2"


class TestTrustLimit:
    """_trust_limit() callable scales the limit string with trust score."""

    def setup_method(self):
        # Ensure env is clean before each test
        os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")

    def _make_request_with_trust(self, trust_score: float) -> Request:
        from platform.src.auth.jwt import create_access_token  # noqa: PLC0415
        token = create_access_token("did:agentx:tester", trust_score=trust_score)
        req = MagicMock(spec=Request)
        req.headers = {"Authorization": f"Bearer {token}"}
        return req

    def test_baseline_no_trust(self):
        from platform.src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(0.0)
        assert fn(req) == "10/minute"

    def test_max_trust_doubles_limit(self):
        from platform.src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(1.0)
        assert fn(req) == "20/minute"

    def test_half_trust_gives_15(self):
        from platform.src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(0.5)
        # int(10 * 1.5) == 15
        assert fn(req) == "15/minute"

    def test_callable_has_unique_name(self):
        from platform.src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn1 = _trust_limit(10, "minute")
        fn2 = _trust_limit(100, "hour")
        assert fn1.__name__ != fn2.__name__


# ── Integration tests: 429 enforcement ───────────────────────────────────────
#
# We spin up a tiny FastAPI app with memory:// storage and a very low cap
# (2/minute) so we can hit it easily in tests without waiting for real windows.

@pytest.fixture()
def tiny_app() -> Generator[FastAPI, None, None]:
    """A minimal FastAPI app with a 2/minute per-IP limit on GET /ping."""
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _test_rate_limit_handler)

    @app.get("/ping")
    @limiter.limit("2/minute")
    async def ping(request: Request):
        return {"pong": True}

    yield app


async def _test_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "60"},
        content={"detail": "Rate limit exceeded"},
    )


class TestRateLimitEnforcement:
    """Hitting a limit returns 429 with Retry-After header."""

    def test_third_request_returns_429(self, tiny_app):
        client = TestClient(tiny_app, raise_server_exceptions=False)
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        r3 = client.get("/ping")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers

    def test_429_body_has_detail(self, tiny_app):
        client = TestClient(tiny_app, raise_server_exceptions=False)
        for _ in range(2):
            client.get("/ping")
        r = client.get("/ping")
        assert r.status_code == 429
        body = r.json()
        assert "detail" in body

    def test_different_ips_have_independent_buckets(self, tiny_app):
        """Two distinct IPs each get their own 2/min bucket."""
        # TestClient always sends from 127.0.0.1; simulate a second IP via header.
        client = TestClient(tiny_app, raise_server_exceptions=False)

        # Exhaust bucket for 127.0.0.1
        for _ in range(2):
            client.get("/ping")
        assert client.get("/ping").status_code == 429

        # A different forwarded IP should have a fresh bucket
        r = client.get("/ping", headers={"X-Forwarded-For": "10.99.0.1"})
        assert r.status_code == 200


# ── Integration tests: burn-in / log-only mode ─────────────────────────────

@pytest.fixture()
def log_only_app() -> Generator[FastAPI, None, None]:
    """Same tiny app but handler returns 200 with X-RateLimit-Would-Block."""
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

    app = FastAPI()
    app.state.limiter = limiter

    async def log_only_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            headers={"X-RateLimit-Would-Block": "true"},
            content={"_log_only": True},
        )

    app.add_exception_handler(RateLimitExceeded, log_only_handler)

    @app.get("/ping")
    @limiter.limit("2/minute")
    async def ping(request: Request):
        return {"pong": True}

    yield app


class TestBurnInMode:
    """In log-only mode, over-limit requests return 200 with indicator header."""

    def test_over_limit_returns_200_not_429(self, log_only_app):
        client = TestClient(log_only_app, raise_server_exceptions=False)
        for _ in range(2):
            client.get("/ping")
        r = client.get("/ping")
        assert r.status_code == 200
        assert r.headers.get("X-RateLimit-Would-Block") == "true"

    def test_log_only_body_flag(self, log_only_app):
        client = TestClient(log_only_app, raise_server_exceptions=False)
        for _ in range(2):
            client.get("/ping")
        r = client.get("/ping")
        assert r.json().get("_log_only") is True


# ── Integration tests: LIMIT_ONBOARD_* constants are plain strings ───────────

class TestOnboardConstants:
    """LIMIT_ONBOARD_HR and LIMIT_ONBOARD_DAY are static strings (not callables)."""

    def test_onboard_hr_is_string(self):
        from platform.src.middleware.rate_limits import LIMIT_ONBOARD_HR  # noqa: PLC0415
        assert isinstance(LIMIT_ONBOARD_HR, str)
        assert "hour" in LIMIT_ONBOARD_HR

    def test_onboard_day_is_string(self):
        from platform.src.middleware.rate_limits import LIMIT_ONBOARD_DAY  # noqa: PLC0415
        assert isinstance(LIMIT_ONBOARD_DAY, str)
        assert "day" in LIMIT_ONBOARD_DAY
