"""
Tests: EG-3 — in-process cache, no Redis (Neon egress).

  - TTLCache: expiry, lifetime capped at max_ttl, LRU bound, prefix delete
  - src.cache with Redis disabled uses the local store: round-trip is a copy,
    stale after the TTL, cache_delete works, LOCAL_CACHE=off switches it off
  - the response cache on the real app: a second anonymous call within the
    TTL does not reach the route (no DB), stale after the TTL, cursor header
    replayed, Cache-Control public; authenticated calls always reach the route
    and are marked private; errors are not stored; CORS headers on a hit
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src import cache, local_cache
from src.local_cache import TTLCache
from src.main import app
from src.middleware import response_cache
from src.services.feed_service import FeedPage


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ── TTLCache ─────────────────────────────────────────────────────────────────

def test_ttl_cache_expires_and_caps_lifetime():
    clock = Clock()
    c = TTLCache(max_entries=10, max_ttl=30, clock=clock)
    c.set("a", 1, ttl=10)
    c.set("b", 2, ttl=300)          # capped at 30
    clock.now += 9.9
    assert c.get("a") == 1
    clock.now += 0.2
    assert c.get("a") is None
    clock.now += 19
    assert c.get("b") == 2
    clock.now += 1
    assert c.get("b") is None


def test_ttl_cache_lru_bound_and_prefix_delete():
    c = TTLCache(max_entries=3, max_ttl=30)
    for k in ("x:1", "x:2", "y:1"):
        c.set(k, k)
    c.get("x:1")                    # most recently used now
    c.set("y:2", "y:2")             # evicts x:2
    assert c.get("x:2") is None and c.get("x:1") == "x:1"
    c.delete_prefix("y:")
    assert len(c) == 1 and c.get("x:1") == "x:1"


def test_ttl_cache_zero_ttl_not_stored():
    c = TTLCache()
    c.set("a", 1, ttl=0)
    assert c.get("a") is None


# ── src.cache falls back to the local store ──────────────────────────────────

@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.setattr(cache, "_redis_disabled", True)
    monkeypatch.setattr(cache, "_redis", None)


async def test_cache_round_trip_without_redis(no_redis):
    await cache.cache_set("trust:did:agentx:a", {"score": 0.5, "tags": ["x"]}, ttl=300)
    got = await cache.cache_get("trust:did:agentx:a")
    assert got == {"score": 0.5, "tags": ["x"]}
    got["tags"].append("mutated")   # callers get a copy, like Redis
    assert (await cache.cache_get("trust:did:agentx:a"))["tags"] == ["x"]
    await cache.cache_delete("trust:did:agentx:a")
    assert await cache.cache_get("trust:did:agentx:a") is None


async def test_cache_stale_after_ttl(no_redis, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(local_cache.store, "_clock", clock)
    await cache.cache_set("feed:global", [1, 2], ttl=60)    # capped at 30 s locally
    clock.now += 29
    assert await cache.cache_get("feed:global") == [1, 2]
    clock.now += 2
    assert await cache.cache_get("feed:global") is None


async def test_cache_unserialisable_value_is_not_an_error(no_redis):
    await cache.cache_set("k", {"obj": object()})
    assert await cache.cache_get("k") is None


async def test_local_cache_off_switch(no_redis, monkeypatch):
    monkeypatch.setenv("LOCAL_CACHE", "off")
    await cache.cache_set("k", 1)
    assert await cache.cache_get("k") is None


# ── Response cache on the real app ───────────────────────────────────────────

@pytest.fixture
def counted_feed(monkeypatch):
    calls = []

    async def fake_global_feed(limit, caller_did, after):
        calls.append((limit, caller_did, after))
        return FeedPage(posts=[], next_cursor=f"cur{len(calls)}")

    monkeypatch.setattr("src.routers.feed.get_global_feed", fake_global_feed)
    return calls


async def _get(url, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(url, headers=headers or {})


async def test_second_anonymous_call_does_not_reach_route(counted_feed):
    r1 = await _get("/feed/global?limit=10")
    r2 = await _get("/feed/global?limit=10")
    assert r1.status_code == r2.status_code == 200
    assert len(counted_feed) == 1
    assert r2.json() == r1.json() == []
    assert r2.headers["x-next-cursor"] == "cur1"
    for r in (r1, r2):
        assert r.headers["cache-control"] == "public, max-age=30"
        assert "Authorization" in r.headers["vary"]


async def test_query_order_shares_entry_and_different_query_does_not(counted_feed):
    await _get("/feed/global?limit=10&cursor=")
    await _get("/feed/global?cursor=&limit=10")
    assert len(counted_feed) == 1
    await _get("/feed/global?limit=11")
    assert len(counted_feed) == 2


async def test_limit_is_clamped_before_the_key(counted_feed):
    await _get("/feed/global?limit=500")
    await _get("/feed/global?limit=50")
    assert len(counted_feed) == 1


async def test_stale_after_ttl(counted_feed, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(response_cache._cache, "_clock", clock)
    await _get("/feed/global")
    clock.now += 29
    await _get("/feed/global")
    assert len(counted_feed) == 1
    clock.now += 2
    await _get("/feed/global")
    assert len(counted_feed) == 2


async def test_authenticated_calls_bypass_and_are_private(counted_feed):
    await _get("/feed/global")                                  # fills the cache
    r = await _get("/feed/global", {"Authorization": "Bearer not-a-real-token"})
    assert len(counted_feed) == 2
    assert r.headers["cache-control"] == "private, no-store"
    assert "Authorization" in r.headers["vary"]


async def test_authenticated_answer_never_served_to_anonymous(counted_feed):
    await _get("/feed/global", {"Authorization": "Bearer x"})
    await _get("/feed/global")
    assert len(counted_feed) == 2


async def test_errors_are_not_stored(counted_feed):
    r1 = await _get("/feed/global?cursor=garbage")
    r2 = await _get("/feed/global?cursor=garbage")
    assert r1.status_code == r2.status_code == 400
    assert "public" not in r1.headers.get("cache-control", "")


async def test_cors_headers_on_a_cached_answer(counted_feed):
    origin = {"Origin": "http://localhost:3000"}
    await _get("/feed/global", origin)
    r = await _get("/feed/global", origin)
    assert len(counted_feed) == 1
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "x-next-cursor" in r.headers["access-control-expose-headers"].lower()


async def test_uncached_path_untouched(counted_feed, monkeypatch):
    r = await _get("/health")
    assert "public" not in r.headers.get("cache-control", "")


async def test_off_switch(counted_feed, monkeypatch):
    monkeypatch.setenv("LOCAL_CACHE", "off")
    await _get("/feed/global")
    await _get("/feed/global")
    assert len(counted_feed) == 2


async def test_discover_cached(monkeypatch):
    calls = []

    async def fake_top(limit=10):
        calls.append(limit)
        return []

    monkeypatch.setattr("src.services.discovery_service.get_top_agents", fake_top)
    await _get("/agents/discover")
    r = await _get("/agents/discover")
    assert r.status_code == 200 and len(calls) == 1
    assert r.headers["cache-control"] == "public, max-age=60"


def test_invalidate_prefix():
    response_cache._cache.set("/spotlight/agent-of-the-week?", (200, [], b"{}"), 60)
    response_cache._cache.set("/agents?", (200, [], b"[]"), 60)
    response_cache.invalidate("/spotlight/")
    assert response_cache._cache.get("/spotlight/agent-of-the-week?") is None
    assert response_cache._cache.get("/agents?") is not None


def test_cached_paths_have_no_auth_dependency():
    """Every cached path must answer anonymous callers the same way for
    everyone, except /feed/global whose per-caller filter only applies with
    an Authorization header (which bypasses the cache)."""
    from fastapi.routing import APIRoute

    def deps(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from deps(d)

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in response_cache.CACHED_PATHS \
                and "GET" in route.methods:
            names = {getattr(c, "__name__", "") for c in deps(route.dependant)}
            assert not names & {"get_current_agent", "_check"}, (route.path, names)


# ── SR-1 (Fable review, 14 Oct 2026): byte budget on the response cache ──────
# 500 entries × 256 KB was 128 MB; one anonymous caller varying a junk query
# parameter could fill that inside its own per-IP budget on a 512 MB machine.

def _sized(max_bytes=100, clock=None, **kw):
    return local_cache.TTLCache(max_entries=50, max_ttl=60, clock=clock or Clock(),
                                max_bytes=max_bytes, size_of=len, **kw)


def test_ttl_cache_byte_budget_evicts_oldest_live_entry():
    c = _sized(max_bytes=100)
    c.set("a", b"x" * 40); c.set("b", b"y" * 40)
    assert c.bytes_used == 80
    c.get("a")                           # a is now the most recently used
    c.set("c", b"z" * 40)                # 120 > 100: b (least recently used) goes
    assert c.get("b") is None and c.get("a") is not None and c.get("c") is not None
    assert c.bytes_used == 80 and len(c) == 2


def test_ttl_cache_sweeps_expired_before_evicting_live_ones():
    clock = Clock()
    c = _sized(max_bytes=100, clock=clock)
    c.set("old", b"x" * 60, ttl=5)
    clock.now += 10                      # old is expired but still in memory
    c.set("new", b"y" * 60)              # 120 > 100: the expired one goes, not a live one
    assert c.get("new") is not None and len(c) == 1 and c.bytes_used == 60


def test_ttl_cache_value_over_budget_is_not_stored_and_overwrite_accounts():
    c = _sized(max_bytes=100)
    c.set("big", b"x" * 101)
    assert c.get("big") is None and c.bytes_used == 0
    c.set("k", b"x" * 30); c.set("k", b"x" * 50)
    assert c.bytes_used == 50
    c.delete("k"); assert c.bytes_used == 0
    c.set("k", b"x" * 50); c.clear(); assert c.bytes_used == 0 and len(c) == 0


def test_ttl_cache_without_budget_unchanged():
    c = local_cache.TTLCache(max_entries=2, clock=Clock())
    c.set("a", "v1"); c.set("b", "v2"); c.set("c", "v3")
    assert c.get("a") is None and c.bytes_used == 0 and len(c) == 2


async def test_junk_query_variants_cannot_exceed_the_byte_budget(monkeypatch):
    body = b'[{"content": "' + b"x" * 1200 + b'"}]'           # ~1.2 KB a page

    async def big_list(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    monkeypatch.setattr(response_cache._cache, "max_bytes", 4000)
    transport = ASGITransport(app=response_cache.ResponseCacheMiddleware(big_list))
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        for n in range(20):
            r = await c.get(f"/feed/global?limit=5&junk={n}")
            assert r.status_code == 200 and r.content == body
    assert 0 < response_cache._cache.bytes_used <= 4000
    assert len(response_cache._cache) <= 3
    assert response_cache.MAX_CACHE_BYTES <= 32 * 1024 * 1024
