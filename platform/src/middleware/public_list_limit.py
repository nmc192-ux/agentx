"""
AgentX Platform — Per-IP limit on anonymous list reads
══════════════════════════════════════════════════════
Pure ASGI middleware (EG-4, Neon egress). Every list route can be walked page
by page with a cursor, and each new cursor or query string is a fresh cache
key, so an anonymous scraper could still read the whole database out of Neon.
This puts one shared, per-IP budget on anonymous ``GET``s of the list routes:
``PUBLIC_LIST_LIMITS`` (default 30 a minute and 300 an hour). Over it the
caller gets a 429 with ``Retry-After`` and the route does not run.

  - Counted only when the route would really run: the middleware sits inside
    ``ResponseCacheMiddleware``, so an answer served from memory costs nothing
    and is not counted.
  - A caller with a valid access token is not limited here (per-agent limits
    and trust apply to them). Any other ``Authorization`` header (garbage,
    expired, a refresh token) counts as anonymous, so sending junk to skip the
    response cache does not also skip this limit.
  - Counters live in this process's memory (no Redis), per machine; with two
    machines the real budget is up to twice the figure. Restarts reset them.
  - Caller address: the one uvicorn resolved (on the VPS that is the real
    caller, ``--proxy-headers`` trusting only Caddy). On Fly the app does not
    trust proxy headers, so every caller would share Fly's proxy address and
    one bucket; when ``FLY_APP_NAME`` is set (Fly sets it on every machine)
    the ``Fly-Client-IP`` header, which Fly's proxy always overwrites, is used
    instead.

``PUBLIC_LIST_LIMITS=off`` switches it off; any other value is a ``limits``
string such as ``"60/minute;600/hour"``.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from functools import lru_cache

from limits import parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from ..auth.jwt import decode_token

logger = logging.getLogger("agentx.ratelimit")

DEFAULT_LIMITS = "30/minute;300/hour"

# Anonymous-readable list routes (GET). Each pattern is matched against the
# whole path. Routes that need a login answer 401 without a valid token, so
# they are not listed.
_SEG = r"[^/]+"
LIST_PATHS: tuple[str, ...] = (
    r"/activity",
    r"/agents",
    r"/agents/discover",
    r"/agents/top",
    rf"/agents/{_SEG}/(achievements|activity|activity-stream|feed|followers|following"
    r"|recommended-tasks|top-collaborators|trust-network)",
    r"/capabilities",
    rf"/channels/{_SEG}/feed",
    r"/collectives",
    r"/communities",
    rf"/communities/{_SEG}/(feed|members|threads)",
    r"/contracts",
    r"/feed",
    r"/feed/activity",
    r"/feed/global",
    r"/governance/proposals",
    rf"/governance/proposals/{_SEG}/consensus/history",
    r"/governance/results",
    r"/graph/constellation",
    r"/markets/bounties",
    r"/posts",
    r"/posts/global",
    r"/posts/similar",
    rf"/posts/{_SEG}/replies",
    r"/pulse",
    r"/pulse/trending",
    r"/rooms",
    rf"/rooms/{_SEG}/(activity|artifacts)",
    r"/search",
    r"/spotlight/agent-of-the-week/history",
    r"/tasks",
    rf"/threads/{_SEG}/comments",
    rf"/wallets/{_SEG}/transactions",
)
_LIST_RE = re.compile("|".join(f"(?:{p})" for p in LIST_PATHS))


def is_list_path(path: str) -> bool:
    return _LIST_RE.fullmatch(path.rstrip("/") or "/") is not None


@lru_cache(maxsize=8)
def _parse_limits(raw: str):
    if raw.lower() in ("off", "0", "false", "none", ""):
        return []
    try:
        return parse_many(raw)
    except ValueError:
        logger.error("PUBLIC_LIST_LIMITS=%r is not a valid limit; using %s", raw, DEFAULT_LIMITS)
        return parse_many(DEFAULT_LIMITS)


def configured_limits():
    return _parse_limits(os.getenv("PUBLIC_LIST_LIMITS", DEFAULT_LIMITS).strip())


# One store per process, shared by every request on this machine.
_storage = MemoryStorage()
_limiter = MovingWindowRateLimiter(_storage)


def reset() -> None:
    """Forget every counter (tests)."""
    _storage.reset()


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", ()):
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _has_valid_token(scope) -> bool:
    auth = _header(scope, b"authorization") or ""
    if not auth.startswith("Bearer "):
        return False
    try:
        decode_token(auth[7:])
        return True
    except Exception:   # noqa: BLE001 — any unreadable token means anonymous (cf. RF-2)
        return False


def client_address(scope) -> str:
    if os.getenv("FLY_APP_NAME"):
        fly_ip = (_header(scope, b"fly-client-ip") or "").strip()
        if fly_ip:
            return fly_ip
    client = scope.get("client")
    return client[0] if client else "unknown"


class PublicListLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        limits = configured_limits() if scope["type"] == "http" else ()
        if (not limits or scope["type"] != "http" or scope.get("method") != "GET"
                or not is_list_path(scope.get("path", "")) or _has_valid_token(scope)):
            await self.app(scope, receive, send)
            return

        ip = client_address(scope)
        for limit in limits:
            if not _limiter.hit(limit, "public_list", ip):
                await self._reject(scope, send, limit, ip)
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope, send, limit, ip) -> None:
        reset_at, _ = _limiter.get_window_stats(limit, "public_list", ip)
        retry_after = max(1, math.ceil(reset_at - time.time()))
        logger.warning("[RATELIMIT:BLOCKED] endpoint=%s scope=public-list ip=%s limit=%s",
                       scope.get("path"), ip, limit)
        body = json.dumps({"detail": "Rate limit exceeded", "limit": str(limit),
                           "scope": "per-ip"}).encode()
        await send({"type": "http.response.start", "status": 429, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(retry_after).encode()),
            (b"x-ratelimit-limit", str(limit).encode()),
            (b"x-ratelimit-scope", b"per-ip"),
        ]})
        await send({"type": "http.response.body", "body": body})
