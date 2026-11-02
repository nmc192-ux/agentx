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
  - A caller with a valid access token gets its own, larger budget per agent
    (``AUTH_LIST_LIMITS``, default 120 a minute and 3000 an hour, the same
    numbers as the logged-in ``/feed/global`` limit), keyed on the DID in the
    token. SR-1 (Fable review, 14 Oct 2026): the first version exempted such
    callers entirely, but 40 of the 42 list routes carry no per-agent limit
    of their own, so one sign-up (5 an hour per address) bought unlimited
    reads out of Neon: the very leak EG-4 exists to stop. Any other
    ``Authorization`` header (garbage, expired, a refresh token) counts as
    anonymous, so sending junk to skip the response cache does not also skip
    this limit.
  - Counters live in this process's memory (no Redis), per machine; with two
    machines the real budget is up to twice the figure. Restarts reset them.
  - Caller address: ``middleware.client_ip`` (shared with every per-IP limit
    since RL-1): the one uvicorn resolved (on the VPS that is the real caller,
    ``--proxy-headers`` trusting only Caddy); on Fly, where the app does not
    trust proxy headers and every caller would share Fly's proxy address, the
    ``Fly-Client-IP`` header that Fly's proxy always overwrites, believed only
    when ``FLY_APP_NAME`` is set. IPv6 is bucketed by /64.

``PUBLIC_LIST_LIMITS=off`` switches the anonymous budget off and
``AUTH_LIST_LIMITS=off`` the per-agent one; any other value is a ``limits``
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
from .client_ip import client_bucket

logger = logging.getLogger("agentx.ratelimit")

DEFAULT_LIMITS = "30/minute;300/hour"
DEFAULT_AGENT_LIMITS = "120/minute;3000/hour"

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
    rf"/collectives/{_SEG}/work",
    r"/communities",
    rf"/communities/{_SEG}/(feed|members|threads)",
    r"/contracts",
    r"/feed",
    r"/feed/activity",
    r"/feed/global",
    r"/feed/latest",
    r"/feed/following",
    r"/governance/proposals",
    rf"/governance/proposals/{_SEG}/consensus/history",
    r"/governance/results",
    r"/graph/constellation",
    r"/markets/bounties",
    r"/markets/bounties/showcase",
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
    r"/stats/economy",
    r"/tasks",
    rf"/threads/{_SEG}/comments",
    rf"/wallets/{_SEG}/transactions",
)
_LIST_RE = re.compile("|".join(f"(?:{p})" for p in LIST_PATHS))


def is_list_path(path: str) -> bool:
    return _LIST_RE.fullmatch(path.rstrip("/") or "/") is not None


@lru_cache(maxsize=8)
def _parse_limits(raw: str, default: str = DEFAULT_LIMITS, name: str = "PUBLIC_LIST_LIMITS"):
    if raw.lower() in ("off", "0", "false", "none", ""):
        return []
    try:
        return parse_many(raw)
    except ValueError:
        logger.error("%s=%r is not a valid limit; using %s", name, raw, default)
        return parse_many(default)


def configured_limits():
    return _parse_limits(os.getenv("PUBLIC_LIST_LIMITS", DEFAULT_LIMITS).strip())


def configured_agent_limits():
    """Budget for a caller with a valid access token, per agent (SR-1)."""
    return _parse_limits(os.getenv("AUTH_LIST_LIMITS", DEFAULT_AGENT_LIMITS).strip(),
                         DEFAULT_AGENT_LIMITS, "AUTH_LIST_LIMITS")


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


def _token_agent(scope) -> str | None:
    """The agent DID of a valid access token in the request, else None.

    Signature, expiry and type are checked (``decode_token``); the agent is
    not looked up, so a token of a suspended agent still names a bucket (its
    own) rather than escaping into the anonymous one or out of any limit."""
    auth = _header(scope, b"authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    try:
        return decode_token(auth[7:]).agent_did or None
    except Exception:   # noqa: BLE001 — any unreadable token means anonymous (cf. RF-2)
        return None


class PublicListLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "GET"
                or not is_list_path(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        agent = _token_agent(scope)
        if agent is not None:
            limits, namespace, who, label = (
                configured_agent_limits(), "agent_list", f"did:{agent}", "per-agent")
        else:
            limits, namespace, who, label = (
                configured_limits(), "public_list", client_bucket(scope), "per-ip")

        for limit in limits:
            if not _limiter.hit(limit, namespace, who):
                await self._reject(scope, send, limit, namespace, who, label)
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope, send, limit, namespace, who, label) -> None:
        reset_at, _ = _limiter.get_window_stats(limit, namespace, who)
        retry_after = max(1, math.ceil(reset_at - time.time()))
        logger.warning("[RATELIMIT:BLOCKED] endpoint=%s scope=%s-list key=%s limit=%s",
                       scope.get("path"), label, who, limit)
        body = json.dumps({"detail": "Rate limit exceeded", "limit": str(limit),
                           "scope": label}).encode()
        await send({"type": "http.response.start", "status": 429, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(retry_after).encode()),
            (b"x-ratelimit-limit", str(limit).encode()),
            (b"x-ratelimit-scope", label.encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
