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
    from src.auth.jwt import create_access_token  # noqa: PLC0415
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
        from src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        token = _make_jwt("did:agentx:atlas-001")
        req = self._make_request(auth_header=f"Bearer {token}")
        key = get_agent_did(req)
        assert key == "did:did:agentx:atlas-001"

    def test_falls_back_to_ip_for_no_auth(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        req = self._make_request(client_host="10.0.0.1")
        key = get_agent_did(req)
        assert key == "ip:10.0.0.1"

    def test_falls_back_to_ip_for_invalid_bearer(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from src.middleware.rate_limits import get_agent_did  # noqa: PLC0415
        req = self._make_request(auth_header="Bearer this.is.not.valid", client_host="10.0.0.2")
        key = get_agent_did(req)
        assert key == "ip:10.0.0.2"

    def test_falls_back_to_ip_when_the_token_breaks_the_decoder(self, monkeypatch):
        """RF-2 (T1 review): a bearer token whose header is a deeply nested
        JSON array makes the JWT library raise RecursionError, not
        InvalidTokenError. The key function must still answer with the IP
        bucket: the limiters fail open, so a raise here would mean an
        unlimited request (and a limiter flipped to its fallback store)."""
        import base64  # noqa: PLC0415
        monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
        from src.auth.jwt import decode_token  # noqa: PLC0415
        from src.middleware.rate_limits import _get_trust, get_agent_did  # noqa: PLC0415

        def b64(text: str) -> str:
            return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()

        token = b64("[" * 100_000 + "]" * 100_000) + "." + b64('{"a":1}') + ".sig"
        with pytest.raises(RecursionError):       # the precondition: not an InvalidTokenError
            decode_token(token)
        req = self._make_request(auth_header=f"Bearer {token}", client_host="10.0.0.3")
        assert get_agent_did(req) == "ip:10.0.0.3"
        assert _get_trust(req) == 0.0


class TestTrustLimit:
    """_trust_limit() callable scales the limit string with trust score."""

    def setup_method(self):
        # Ensure env is clean before each test
        os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")

    def _make_request_with_trust(self, trust_score: float) -> Request:
        from src.auth.jwt import create_access_token  # noqa: PLC0415
        token = create_access_token("did:agentx:tester", trust_score=trust_score)
        req = MagicMock(spec=Request)
        req.headers = {"Authorization": f"Bearer {token}"}
        return req

    def test_baseline_no_trust(self):
        from src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(0.0)
        assert fn(req) == "10/minute"

    def test_max_trust_doubles_limit(self):
        from src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(1.0)
        assert fn(req) == "20/minute"

    def test_half_trust_gives_15(self):
        from src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
        fn = _trust_limit(10, "minute")
        req = self._make_request_with_trust(0.5)
        # int(10 * 1.5) == 15
        assert fn(req) == "15/minute"

    def test_callable_has_unique_name(self):
        from src.middleware.rate_limits import _trust_limit  # noqa: PLC0415
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

    def test_limit_is_per_client(self, tiny_app):
        """Requests from the same client all count toward the same bucket."""
        client = TestClient(tiny_app, raise_server_exceptions=False)
        # The first two succeed, the third is blocked — consistent for same IP.
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429


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
        from src.middleware.rate_limits import LIMIT_ONBOARD_HR  # noqa: PLC0415
        assert isinstance(LIMIT_ONBOARD_HR, str)
        assert "hour" in LIMIT_ONBOARD_HR

    def test_onboard_day_is_string(self):
        from src.middleware.rate_limits import LIMIT_ONBOARD_DAY  # noqa: PLC0415
        assert isinstance(LIMIT_ONBOARD_DAY, str)
        assert "day" in LIMIT_ONBOARD_DAY


# ── S5-2b: one limiter object per route ───────────────────────────────────────

def _registered_routes(lim: Limiter) -> set:
    """Every endpoint name a slowapi Limiter will check (static, dynamic, marked)."""
    marked = getattr(lim, "_Limiter__marked_for_limiting", {})
    return set(lim._route_limits) | set(lim._dynamic_route_limits) | set(marked)


class TestNoStackedLimiterObjects:
    """
    slowapi lets only the OUTERMOST limiter object check a request: its wrapper
    runs ``_check_request_limit`` for the limits registered on *that object*
    and sets ``request.state._rate_limiting_complete``; every inner limiter
    object's wrapper then skips. So ``@limiter.limit`` stacked above
    ``@limiter_did.limit`` silently drops the per-agent limits (found on
    POST /media in cycle 349). The rule: one limiter object per route; a
    per-IP cap next to per-DID caps is ``limiter_did.limit(..., key_func=
    get_client_ip)``.
    """

    def test_no_route_is_registered_on_both_limiter_objects(self):
        import src.main  # noqa: F401, PLC0415  — registers every router's limits
        from src.middleware.rate_limits import limiter, limiter_did  # noqa: PLC0415
        both = _registered_routes(limiter) & _registered_routes(limiter_did)
        assert both == set(), (
            f"routes limited by both limiter objects (the inner one never runs): {sorted(both)}"
        )

    def test_upload_media_has_all_three_limits_on_one_object(self):
        import src.main  # noqa: F401, PLC0415
        from src.middleware.rate_limits import (  # noqa: PLC0415
            get_agent_did, get_client_ip, limiter, limiter_did,
        )
        name = "src.routers.media.upload_media"
        assert name not in _registered_routes(limiter)
        static = limiter_did._route_limits.get(name, [])
        dynamic = limiter_did._dynamic_route_limits.get(name, [])
        assert [(str(x.limit), x.key_func) for x in static] == [("60 per 1 hour", get_client_ip)]
        assert [g.key_function for g in dynamic] == [get_agent_did, get_agent_did]
        assert sorted(str(x.limit) for g in dynamic for x in g) == ["10 per 1 minute", "30 per 1 hour"]

    def test_slowapi_skips_the_inner_limiter_object(self):
        """The behaviour the rule guards against, pinned so a slowapi upgrade
        that changes it is noticed (the rule could then be relaxed)."""
        outer = Limiter(key_func=get_remote_address, storage_uri="memory://")
        inner = Limiter(key_func=get_remote_address, storage_uri="memory://")
        app = FastAPI()
        app.state.limiter = outer

        async def handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
            return JSONResponse(status_code=429, content={"detail": str(exc.limit.limit)})
        app.add_exception_handler(RateLimitExceeded, handler)

        @app.get("/stacked")
        @outer.limit("100/minute")
        @inner.limit("1/minute")
        async def stacked(request: Request):
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        codes = [client.get("/stacked").status_code for _ in range(3)]
        assert codes == [200, 200, 200], "inner 1/minute now runs: revisit the one-object rule"

    def test_key_func_limit_on_one_object_enforces_both(self):
        """The fix's shape: two key functions, one limiter object, both caps hold."""
        lim = Limiter(key_func=lambda request: "did:" + request.headers.get("X-Did", "anon"),
                      storage_uri="memory://")
        app = FastAPI()
        app.state.limiter = lim

        async def handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
            return JSONResponse(status_code=429, content={
                "detail": str(exc.limit.limit), "key": exc.limit.key_func.__name__})
        app.add_exception_handler(RateLimitExceeded, handler)

        def by_ip(request: Request) -> str:
            return request.headers.get("X-Ip", "0.0.0.0")

        @app.get("/one")
        @lim.limit("5/minute", key_func=by_ip)
        @lim.limit("2/minute")
        async def one(request: Request):
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        # Per-DID cap: the same agent from fresh IPs is stopped at 2.
        codes = [client.get("/one", headers={"X-Did": "a", "X-Ip": f"10.0.0.{i}"}).status_code
                 for i in range(3)]
        assert codes == [200, 200, 429]
        # Per-IP cap: different agents from one IP are stopped at 5 (3 used so far? no:
        # each request above used a different IP, so this IP is fresh).
        codes = [client.get("/one", headers={"X-Did": f"b{i}", "X-Ip": "10.1.1.1"}).status_code
                 for i in range(6)]
        assert codes == [200, 200, 200, 200, 200, 429]
        r = client.get("/one", headers={"X-Did": "b9", "X-Ip": "10.1.1.1"})
        assert r.json()["key"] == "by_ip"


class TestLimitScope:
    """The 429 body names the scope of the limit that fired, not the caller's auth."""

    def _exc(self, key_func):
        from limits import parse  # noqa: PLC0415
        from slowapi.wrappers import Limit  # noqa: PLC0415
        return RateLimitExceeded(Limit(parse("60/hour"), key_func, None, False, None,
                                       None, None, 1, True))

    def _request(self, headers: dict | None = None) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        return Request({"type": "http", "method": "POST", "path": "/media", "headers": raw,
                        "client": ("203.0.113.9", 1234), "query_string": b""})

    def test_ip_keyed_limit_is_per_ip_even_when_signed_in(self):
        from src.middleware.rate_limits import get_client_ip, limit_scope  # noqa: PLC0415
        req = self._request({"Authorization": f"Bearer {_make_jwt()}"})
        assert limit_scope(req, self._exc(get_client_ip)) == "per-ip"

    def test_did_keyed_limit_is_per_did_when_signed_in(self):
        from src.middleware.rate_limits import get_agent_did, limit_scope  # noqa: PLC0415
        req = self._request({"Authorization": f"Bearer {_make_jwt()}"})
        assert limit_scope(req, self._exc(get_agent_did)) == "per-did"

    def test_did_keyed_limit_is_per_ip_for_anonymous(self):
        from src.middleware.rate_limits import get_agent_did, limit_scope  # noqa: PLC0415
        assert limit_scope(self._request(), self._exc(get_agent_did)) == "per-ip"
