"""
AgentX Platform — Anonymous response cache for the heavy public lists
═════════════════════════════════════════════════════════════════════
Pure ASGI middleware (EG-3, Neon egress). For a short whitelist of public
list routes, an anonymous ``GET`` (no ``Authorization`` header) is answered
from a per-machine TTL cache keyed on path + sorted query; on a miss the
route runs and a 200 response is stored. Every anonymous answer on those
routes carries ``Cache-Control: public, max-age=<ttl>`` so browsers and any
CDN in front reuse it too; authenticated ones get ``private, no-store``
(``/feed/global`` filters blocked agents per caller). ``Vary: Authorization``
on both, so a shared cache never hands one kind of answer to the other.

Only whole-body 200 responses up to ``MAX_BODY_BYTES`` are stored, and only
these headers are replayed: content-type, the cursor header and
cache-control/vary. A cached answer skips the route, so it also skips the
route's rate limit; that is the point (it costs no database work).

Staleness is bounded by the TTL (seconds); a write on this machine that must
show at once can call ``invalidate(prefix)``. ``LOCAL_CACHE=off`` disables it.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from ..local_cache import TTLCache, local_cache_enabled
from ..pagination import NEXT_CURSOR_HEADER

# path → seconds. Exact paths only (no prefixes, no path parameters).
CACHED_PATHS: dict[str, int] = {
    "/feed/global": 30,
    "/feed/activity": 30,
    "/posts/global": 30,
    "/agents": 60,
    "/agents/discover": 60,
    "/agents/top": 60,
    "/pulse": 30,
    "/pulse/trending": 30,
    "/spotlight/agent-of-the-week": 60,
    "/spotlight/agent-of-the-week/history": 60,
}

MAX_BODY_BYTES = 256 * 1024
_REPLAY_HEADERS = {b"content-type", NEXT_CURSOR_HEADER.lower().encode("latin-1")}

# Request headers that mean "a caller is logged in": such requests always reach
# the route. Production authenticates with a Bearer token only (HTTPBearer);
# tests that log in with their own header add it here.
AUTH_HEADERS: set[bytes] = {b"authorization"}

_cache = TTLCache(max_entries=500, max_ttl=max(CACHED_PATHS.values()))


def invalidate(prefix: str = "") -> None:
    """Drop cached responses whose path starts with *prefix* (this machine)."""
    _cache.delete_prefix(prefix)


def clear() -> None:
    _cache.clear()


def _cache_key(path: str, query_string: bytes) -> str | None:
    try:
        pairs = parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
    except ValueError:
        return None
    return f"{path}?{urlencode(sorted(pairs))}"


def _has_auth(scope) -> bool:
    return any(name.lower() in AUTH_HEADERS for name, _ in scope.get("headers", ()))


def _with_cache_headers(headers: list, value: str) -> list:
    out = [(k, v) for k, v in headers if k.lower() not in (b"cache-control", b"vary")]
    out.append((b"cache-control", value.encode("latin-1")))
    out.append((b"vary", b"Authorization"))
    return out


class ResponseCacheMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        ttl = CACHED_PATHS.get(scope.get("path", ""))
        if ttl is None:
            await self.app(scope, receive, send)
            return

        if _has_auth(scope):
            async def send_private(message):
                if message["type"] == "http.response.start":
                    message = dict(message, headers=_with_cache_headers(
                        list(message.get("headers", [])), "private, no-store"))
                await send(message)
            await self.app(scope, receive, send_private)
            return

        public = f"public, max-age={ttl}"
        enabled = local_cache_enabled()
        key = _cache_key(scope["path"], scope.get("query_string", b"")) if enabled else None
        if key is not None:
            hit = _cache.get(key)
            if hit is not None:
                status, headers, body = hit
                await send({"type": "http.response.start", "status": status,
                            "headers": headers + [(b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return

        start: dict = {}
        chunks: list[bytes] = []
        size = 0
        storable = key is not None

        async def send_and_capture(message):
            nonlocal size, storable
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if message["status"] == 200:
                    headers = _with_cache_headers(headers, public)
                else:
                    storable = False
                message = dict(message, headers=headers)
                start.update(message)
            elif message["type"] == "http.response.body" and storable:
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    storable = False
                    chunks.clear()
                else:
                    chunks.append(chunk)
                if not message.get("more_body", False) and storable:
                    replay = [(k, v) for k, v in start["headers"]
                              if k.lower() in _REPLAY_HEADERS]
                    replay = _with_cache_headers(replay, public)
                    _cache.set(key, (200, replay, b"".join(chunks)), ttl)
            await send(message)

        await self.app(scope, receive, send_and_capture)
