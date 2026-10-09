"""
Tests: Redis fails open (after the 9 Oct 2026 production outage).

Upstash ran out of requests and every API request crashed on the Redis error
(the rate limiter raised). Production now runs with REDIS_URL=memory://, and
a Redis error must never fail a request or startup.

What is proven:
  • the API starts and answers, in production mode, with REDIS_URL=memory://
    and with REDIS_URL pointing at a dead Redis (the outage, reproduced: before
    the fix the dead-Redis case raised ConnectionError on the first request)
  • the scheduler module imports and builds its jobs with REDIS_URL=memory://
    (it is run end to end against Postgres in tests/integration/test_scheduler_db.py)
  • with a dead Redis the rate limits still apply, counted in memory
  • a missing REDIS_PASSWORD does not stop the app
  • every cache helper returns quietly when the Redis client raises
  • the agent bus SSE stream ends quietly when Redis refuses the subscribe
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]

_PROBE_API = """
import asyncio
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
import src.main as m

async def go():
    # No database here: only Redis is under test.
    with patch.object(m, "init_pool", new=AsyncMock()), \\
         patch.object(m, "close_pool", new=AsyncMock()), \\
         patch("src.services.economy_service.initialize_treasury", new=AsyncMock()):
        async with m.app.router.lifespan_context(m.app):
            async with AsyncClient(transport=ASGITransport(app=m.app),
                                   base_url="http://t") as c:
                codes = [(await c.get("/health")).status_code for _ in range(3)]
    print("CODES", codes)

asyncio.run(go())
"""

_PROBE_SCHEDULER = """
from src.jobs import scheduler
print("JOBS", [j.name for j in scheduler.JOBS])
"""


def _env(redis_url: str | None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(PLATFORM),
        "APP_ENV": "production",
        "CORS_ORIGINS": '["https://app.example"]',
        "POSTGRES_PASSWORD": "probe-not-a-secret",
        "JWT_SECRET": "probe-not-a-secret-" + "0" * 48,
        "SENTRY_DSN": "",
    }
    if redis_url is not None:
        env["REDIS_URL"] = redis_url
    return env


def _run(code: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=PLATFORM, env=env,
        capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("redis_url", ["memory://", "redis://127.0.0.1:1/0"])
def test_api_starts_and_answers_without_redis(redis_url):
    result = _run(_PROBE_API, _env(redis_url))
    assert result.returncode == 0, result.stderr[-3000:]
    assert "CODES [200, 200, 200]" in result.stdout


def test_scheduler_loads_with_memory_redis_url():
    result = _run(_PROBE_SCHEDULER, _env("memory://"))
    assert result.returncode == 0, result.stderr[-3000:]
    assert "JOBS ['scheduled_maintenance', 'auto_release', 'founder_heartbeat', 'agent_of_week']" in result.stdout


def test_missing_redis_password_does_not_stop_the_app(monkeypatch):
    from src.config import Settings
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("REDIS_PASSWORD_FILE", "/nonexistent/redis_password")
    settings = Settings(_env_file=None)   # no ValueError
    # An empty password when none is mounted (unless this machine has
    # /run/secrets/redis_password).
    if not Path("/run/secrets/redis_password").exists():
        assert settings.redis_password == ""


# ── Rate limits with a dead Redis ────────────────────────────────────────────

async def test_dead_redis_rate_limits_fall_back_to_memory():
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    from src.middleware import rate_limits

    assert rate_limits._LIMITER_FAIL_OPEN == {
        "in_memory_fallback_enabled": True, "swallow_errors": True,
    }
    for lim in (rate_limits.limiter, rate_limits.limiter_did):
        assert lim._in_memory_fallback_enabled is True and lim._swallow_errors is True

    dead = Limiter(key_func=get_remote_address, storage_uri="redis://127.0.0.1:1/0",
                   **rate_limits._LIMITER_FAIL_OPEN)
    app = FastAPI()
    app.state.limiter = dead
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/x")
    @dead.limit("2/minute")
    async def x(request: Request):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.get("/x")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ── Cache helpers with a failing client ──────────────────────────────────────

class _BrokenRedis:
    def __getattr__(self, name):
        async def fail(*a, **kw):
            raise ConnectionError("ERR max requests limit exceeded")
        return fail


async def test_cache_helpers_swallow_redis_errors(monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, "_redis", _BrokenRedis())
    monkeypatch.setattr(cache, "_redis_disabled", False)
    assert await cache.cache_get("k") is None
    await cache.cache_set("k", {"a": 1}, ttl=5)
    await cache.cache_delete("k")
    await cache.enqueue_task("t")
    await cache.init_cache()
    health = await cache.check_cache_health()
    assert health["status"] == "error"


async def test_unusable_redis_url_disables_the_cache(monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, "_redis", None)
    monkeypatch.setattr(cache, "_redis_disabled", False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "notascheme://what")
    assert cache.get_cache() is None
    assert (await cache.check_cache_health())["status"] == "disabled"


async def test_memory_redis_url_disables_the_cache(monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, "_redis", None)
    monkeypatch.setattr(cache, "_redis_disabled", False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("REDIS_URL", "memory://")
    assert cache.get_cache() is None


async def test_agentbus_stream_ends_quietly_when_subscribe_fails(monkeypatch):
    from src.services import agentbus_service

    class _PubSub:
        async def subscribe(self, *a):
            raise ConnectionError("ERR max requests limit exceeded")

    class _Redis:
        def pubsub(self):
            return _PubSub()

    monkeypatch.setattr(agentbus_service, "get_cache", lambda: _Redis())
    frames = [f async for f in agentbus_service.stream_messages("did:agentx:x-001")]
    assert frames == [": keepalive\n\n"]


# ── RF-2 (T1 review, 10 Oct 2026): fail-open must not become a bypass ────────

def _bad_bearer() -> str:
    """A token whose header is a deeply nested JSON array: python-jose raises
    RecursionError on it, which is not an InvalidTokenError."""
    import base64

    def b64(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()

    return "Bearer " + b64("[" * 100_000 + "]" * 100_000) + "." + b64('{"a":1}') + ".sig"


async def test_key_function_failure_cannot_bypass_the_limit(monkeypatch):
    """Before the fix, this header made get_agent_did raise; with
    swallow_errors the limiter then let the request through unlimited (and
    marked its storage dead for everyone). Now the request lands in the IP
    bucket and the limit holds; the storage is never marked dead."""
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from src.middleware import rate_limits

    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    lim = Limiter(key_func=rate_limits.get_agent_did, storage_uri="memory://",
                  **rate_limits._LIMITER_FAIL_OPEN)
    app = FastAPI()
    app.state.limiter = lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    hits = []

    @app.get("/x")
    @lim.limit("2/minute")
    async def x(request: Request):
        hits.append(1)
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.get("/x", headers={"Authorization": _bad_bearer()})).status_code
                 for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    assert len(hits) == 2                      # the handler never ran over the limit
    assert lim._storage_dead is False


async def test_half_up_storage_allows_at_most_two_windows():
    """Redis "half-up" (answers some calls, errors on others, as Upstash did
    over quota): the limiter flips to its in-memory fallback on the first
    error and back when the storage answers again. Each store counts on its
    own, so the worst case is two windows' worth, never unlimited."""
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from limits.storage.memory import MemoryStorage
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    from src.middleware import rate_limits

    class FlakyStorage(MemoryStorage):
        STORAGE_SCHEME = ["flaky"]
        calls = 0

        def incr(self, *a, **kw):
            FlakyStorage.calls += 1
            if FlakyStorage.calls % 2 == 0:
                raise ConnectionError("ERR max requests limit exceeded")
            return super().incr(*a, **kw)

    lim = Limiter(key_func=get_remote_address, storage_uri="flaky://",
                  **rate_limits._LIMITER_FAIL_OPEN)
    app = FastAPI()
    app.state.limiter = lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/x")
    @lim.limit("2/minute")
    async def x(request: Request):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.get("/x")).status_code for _ in range(12)]
    assert 500 not in codes
    assert 2 <= codes.count(200) <= 4, codes
    assert codes[-1] == 429
