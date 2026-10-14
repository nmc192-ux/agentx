"""
Tests: EG-4 — per-IP limit on anonymous list reads (Neon egress).

  - every list route that takes limit/cursor/page is covered, except the ones
    that need a login (route walk)
  - each covered route answers 429 (with Retry-After, CORS) once the caller's
    budget is spent, without running the route
  - one budget shared across routes; another address has its own
  - a valid access token is not limited; junk, expired and refresh tokens are
  - answers served from the response cache are not counted
  - on Fly the Fly-Client-IP header keys the bucket; elsewhere it is ignored
  - POSTs, non-list paths and PUBLIC_LIST_LIMITS=off pass
"""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth.jwt import create_access_token, create_refresh_token
from src.main import app
from src.middleware import public_list_limit as pll
from src.services.feed_service import FeedPage

LOGIN_ONLY = {"/agentbus/inbox", "/notifications", "/posts/moderation/queue"}


def _list_route_templates():
    out = set()
    for r in app.routes:
        if "GET" in getattr(r, "methods", set()) and hasattr(r, "dependant"):
            names = {p.name for p in r.dependant.query_params}
            if names & {"limit", "cursor", "page"}:
                out.add(r.path)
    return sorted(out)


def _concrete(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "did:agentx:abc", template)


@pytest.fixture
def tight(monkeypatch):
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "2/minute")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)


@pytest.fixture
def counted_feed(monkeypatch):
    calls = []

    async def fake_global_feed(limit, caller_did, after):
        calls.append(caller_did)
        return FeedPage(posts=[], next_cursor=None)

    monkeypatch.setattr("src.routers.feed.get_global_feed", fake_global_feed)
    return calls


async def _get(url, headers=None, ip="203.0.113.7"):
    transport = ASGITransport(app=app, client=(ip, 1234), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get(url, headers=headers or {})


def _spend(ip: str, n: int = 2):
    for limit in pll.configured_limits():
        for _ in range(n):
            pll._limiter.hit(limit, "public_list", ip)


def test_route_walk_every_public_list_route_is_covered():
    templates = _list_route_templates()
    assert len(templates) > 30
    missing = [t for t in templates if t not in LOGIN_ONLY and not pll.is_list_path(_concrete(t))]
    assert missing == []


def test_login_only_lists_really_need_login():
    # If one of these becomes public it must be added to LIST_PATHS.
    templates = set(_list_route_templates())
    assert LOGIN_ONLY <= templates


def test_non_list_paths_not_matched():
    for path in ("/health", "/agents/did:agentx:abc", "/posts/123", "/skill.md",
                 "/agents/did:agentx:abc/followers/extra", "/onboard"):
        assert not pll.is_list_path(path), path


@pytest.mark.parametrize("template", [t for t in _list_route_templates() if t not in LOGIN_ONLY])
async def test_429_on_each_list_route_once_budget_spent(tight, template):
    ip = "198.51.100.10"
    _spend(ip)
    r = await _get(_concrete(template), ip=ip)
    assert r.status_code == 429, template
    assert int(r.headers["retry-after"]) >= 1
    assert r.headers["x-ratelimit-scope"] == "per-ip"
    assert r.json()["detail"] == "Rate limit exceeded"


async def test_under_budget_reaches_route_then_429(tight, counted_feed, monkeypatch):
    monkeypatch.setenv("LOCAL_CACHE", "off")
    r1 = await _get("/feed/global?limit=5")
    r2 = await _get("/feed/global?limit=6")
    r3 = await _get("/feed/global?limit=7")
    assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 429)
    assert len(counted_feed) == 2


async def test_budget_shared_across_routes_and_per_address(tight, counted_feed, monkeypatch):
    monkeypatch.setenv("LOCAL_CACHE", "off")
    _spend("203.0.113.7", 1)
    assert (await _get("/feed/global")).status_code == 200
    assert (await _get("/agents/discover")).status_code == 429
    assert (await _get("/feed/global", ip="203.0.113.8")).status_code == 200


async def test_cache_hits_are_not_counted(tight, counted_feed):
    for _ in range(6):
        assert (await _get("/feed/global?limit=5")).status_code == 200
    assert len(counted_feed) == 1


async def test_valid_token_not_limited(tight, counted_feed):
    ip = "198.51.100.20"
    _spend(ip)
    token = create_access_token("did:agentx:member1")
    r = await _get("/feed/global", headers={"Authorization": f"Bearer {token}"}, ip=ip)
    # Reaches the route (which then looks the agent up; no DB in this test).
    assert r.status_code != 429 and "x-ratelimit-scope" not in r.headers


@pytest.mark.parametrize("auth", [
    "Bearer junk",
    "Bearer " + "a." * 3,
    "Basic dXNlcjpwYXNz",
    "bearer-but-not",
])
async def test_junk_authorization_still_limited(tight, counted_feed, auth):
    ip = "198.51.100.21"
    _spend(ip)
    r = await _get("/feed/global", headers={"Authorization": auth}, ip=ip)
    assert r.status_code == 429


async def test_expired_and_refresh_tokens_still_limited(tight, counted_feed):
    ip = "198.51.100.22"
    _spend(ip)
    expired = create_access_token("did:agentx:member1", ttl_override=-10)
    refresh = create_refresh_token("did:agentx:member1")
    for tok in (expired, refresh):
        r = await _get("/feed/global", headers={"Authorization": f"Bearer {tok}"}, ip=ip)
        assert r.status_code == 429


async def test_429_carries_cors_headers(tight):
    from src.config import get_settings
    origin = get_settings().cors_origins[0]
    ip = "198.51.100.23"
    _spend(ip)
    r = await _get("/agents", headers={"Origin": origin}, ip=ip)
    assert r.status_code == 429
    assert r.headers.get("access-control-allow-origin") == origin


async def test_fly_client_ip_used_only_on_fly(tight, counted_feed, monkeypatch):
    monkeypatch.setenv("LOCAL_CACHE", "off")
    proxy = "172.16.0.2"
    _spend("192.0.2.50")
    # Not on Fly: a caller-supplied Fly-Client-IP is ignored (keyed on the peer).
    r = await _get("/feed/global", headers={"Fly-Client-IP": "192.0.2.50"}, ip=proxy)
    assert r.status_code == 200
    # On Fly: the proxy's header keys the bucket, so callers behind the one
    # proxy address get separate budgets.
    monkeypatch.setenv("FLY_APP_NAME", "agentx")
    r = await _get("/feed/global", headers={"Fly-Client-IP": "192.0.2.50"}, ip=proxy)
    assert r.status_code == 429
    r = await _get("/feed/global", headers={"Fly-Client-IP": "192.0.2.51"}, ip=proxy)
    assert r.status_code == 200


async def test_post_and_other_paths_pass(tight, monkeypatch):
    ip = "198.51.100.24"
    _spend(ip)
    assert (await _get("/health", ip=ip)).status_code != 429
    transport = ASGITransport(app=app, client=(ip, 1), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/posts", json={})
    assert r.status_code != 429 or r.headers.get("x-ratelimit-scope") != "per-ip"


async def test_off_switch(counted_feed, monkeypatch):
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")
    monkeypatch.setenv("LOCAL_CACHE", "off")
    for _ in range(40):
        assert (await _get("/feed/global")).status_code == 200


def test_bad_setting_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "lots please")
    assert [str(x) for x in pll.configured_limits()] == \
           [str(x) for x in pll._parse_limits(pll.DEFAULT_LIMITS)]


def test_default_is_tight():
    limits = {str(x) for x in pll._parse_limits(pll.DEFAULT_LIMITS)}
    assert limits == {"30 per 1 minute", "300 per 1 hour"}
