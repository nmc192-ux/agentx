"""
Tests: EG-4 — per-IP limit on anonymous list reads (Neon egress).

  - every list route that takes limit/cursor/page is covered, except the ones
    that need a login (route walk)
  - each covered route answers 429 (with Retry-After, CORS) once the caller's
    budget is spent, without running the route
  - one budget shared across routes; another address has its own
  - a valid access token is not in the per-IP budget but has its own per-agent
    one (SR-1); junk, expired and refresh tokens count as anonymous
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

LOGIN_ONLY = {
    "/agentbus/inbox", "/notifications", "/posts/moderation/queue", "/media/moderation/queue",
}


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


# ── SR-1 (Fable review, 14 Oct 2026): a valid token is a budget, not an exemption ──
# 40 of the 42 list routes have no per-agent rate limit of their own, so an
# exemption meant one sign-up bought unlimited reads out of Neon.

@pytest.fixture
def tight_agent(monkeypatch):
    monkeypatch.setenv("AUTH_LIST_LIMITS", "2/minute")
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "2/minute")
    monkeypatch.setenv("LOCAL_CACHE", "off")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)


def _spend_agent(did: str, n: int = 2):
    for limit in pll.configured_agent_limits():
        for _ in range(n):
            pll._limiter.hit(limit, "agent_list", f"did:{did}")


def _bearer(did: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(did)}"}


def _reached_route(r) -> bool:
    # A logged-in call that passes the limiter goes on to look the agent up in
    # the database, which these tests do not have; "not 429 from us" is the check.
    return r.status_code != 429 and "x-ratelimit-scope" not in r.headers


async def test_valid_token_has_its_own_budget_per_agent(tight_agent, counted_feed):
    ip = "198.51.100.30"
    a, b = _bearer("did:agentx:scraper"), _bearer("did:agentx:neighbour")
    passed = [_reached_route(await _get(f"/feed/global?limit={n}", headers=a, ip=ip)) for n in (3, 4, 5)]
    assert passed == [True, True, False]
    r = await _get("/feed/global?limit=6", headers=a, ip=ip)
    assert r.status_code == 429
    assert r.headers["x-ratelimit-scope"] == "per-agent" and int(r.headers["retry-after"]) >= 1
    assert r.json()["scope"] == "per-agent"
    # Another agent from the same address, and the anonymous budget of that
    # address, are untouched.
    assert _reached_route(await _get("/feed/global?limit=7", headers=b, ip=ip))
    assert (await _get("/feed/global?limit=8", ip=ip)).status_code == 200
    assert len(counted_feed) == 1


async def test_agent_budget_is_shared_across_list_routes(tight_agent, counted_feed):
    tok = _bearer("did:agentx:walker")
    _spend_agent("did:agentx:walker", 1)
    assert _reached_route(await _get("/feed/global", headers=tok))
    assert (await _get("/agents/discover", headers=tok)).status_code == 429
    assert (await _get("/posts/global", headers=tok)).status_code == 429


async def test_token_of_unknown_or_suspended_agent_is_still_budgeted(tight_agent, counted_feed):
    """The middleware does not look the agent up, so a token whose agent no
    longer exists (or is suspended) still lands in a bucket of its own."""
    tok = _bearer("did:agentx:ghost-no-such-agent")
    _spend_agent("did:agentx:ghost-no-such-agent")
    assert (await _get("/feed/global", headers=tok)).status_code == 429


@pytest.mark.parametrize("template", [t for t in _list_route_templates() if t not in LOGIN_ONLY])
async def test_429_on_each_list_route_once_agent_budget_spent(tight_agent, template):
    did = "did:agentx:route-walker"
    _spend_agent(did)
    r = await _get(_concrete(template), headers=_bearer(did), ip="198.51.100.31")
    assert r.status_code == 429, template
    assert r.headers["x-ratelimit-scope"] == "per-agent"


async def test_anonymous_budget_spent_does_not_touch_a_logged_in_caller(tight_agent, counted_feed):
    ip = "198.51.100.32"
    _spend(ip)
    assert (await _get("/feed/global", ip=ip)).status_code == 429
    assert _reached_route(await _get("/feed/global", headers=_bearer("did:agentx:member1"), ip=ip))


async def test_agent_budget_off_switch(counted_feed, monkeypatch):
    monkeypatch.setenv("AUTH_LIST_LIMITS", "off")
    monkeypatch.setenv("LOCAL_CACHE", "off")
    tok = _bearer("did:agentx:member1")
    for _ in range(10):
        assert _reached_route(await _get("/feed/global", headers=tok))


def test_agent_default_is_bounded_and_bad_setting_falls_back_to_it(monkeypatch):
    pll._parse_limits.cache_clear()
    monkeypatch.delenv("AUTH_LIST_LIMITS", raising=False)
    assert sorted(str(l) for l in pll.configured_agent_limits()) == ["120 per 1 minute", "3000 per 1 hour"]
    monkeypatch.setenv("AUTH_LIST_LIMITS", "all you like")
    assert sorted(str(l) for l in pll.configured_agent_limits()) == ["120 per 1 minute", "3000 per 1 hour"]
    pll._parse_limits.cache_clear()
