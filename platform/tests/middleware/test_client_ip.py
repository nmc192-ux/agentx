"""
RL-1 (T1, 14 Oct 2026): every per-IP rate limit keys on the real caller on Fly.

Before: Fly runs uvicorn without --proxy-headers, so slowapi's get_remote_address
returned Fly's proxy address for every caller and the sign-up budget (5/hour on
/onboard and POST /agents) was one global budget: five requests an hour from
anyone stopped sign-ups for everyone.

After: middleware/client_ip.py resolves the caller once for every per-IP limit:
  - Fly-Client-IP is believed only when FLY_APP_NAME is set (Fly sets it; Fly's
    proxy overwrites the header), otherwise the socket peer is used;
  - a header that is not one plain IP address falls back to the peer;
  - IPv6 is bucketed by /64 so a caller cannot rotate through its block.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from src.middleware import client_ip
from src.middleware.client_ip import (
    bucket,
    client_address,
    client_bucket,
    request_address,
    request_bucket,
    resolve_address,
)

PROXY = "172.19.4.2"          # what Fly's proxy looks like to the app
FLY_A = "198.51.100.10"
FLY_B = "198.51.100.11"


@pytest.fixture
def off_fly(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)


@pytest.fixture
def on_fly(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "agentx-platform")


def _request(peer: str | None = PROXY, headers: dict | None = None) -> Request:
    req = MagicMock(spec=Request)
    if peer is None:
        req.client = None
    else:
        req.client = MagicMock()
        req.client.host = peer
    req.headers = {k.lower(): v for k, v in (headers or {}).items()}
    return req


def _scope(peer: str | None = PROXY, headers: dict | None = None) -> dict:
    return {
        "type": "http",
        "client": (peer, 40000) if peer else None,
        "headers": [(k.lower().encode(), v.encode("latin-1")) for k, v in (headers or {}).items()],
    }


# ── resolve_address: when the header is believed ──────────────────────────────

class TestResolveAddress:
    def test_off_fly_header_is_ignored(self, off_fly):
        assert resolve_address(PROXY, FLY_A) == PROXY

    def test_on_fly_header_is_the_caller(self, on_fly):
        assert resolve_address(PROXY, FLY_A) == FLY_A

    def test_on_fly_missing_header_falls_back_to_peer(self, on_fly):
        assert resolve_address(PROXY, None) == PROXY
        assert resolve_address(PROXY, "") == PROXY
        assert resolve_address(PROXY, "   ") == PROXY

    @pytest.mark.parametrize("bad", [
        "198.51.100.10, 10.0.0.1",      # a list, not one address
        "198.51.100.10:443",            # with a port
        "evil",                         # not an address
        "did:agentx:someone",           # a key that would collide with DID buckets
        "ip:198.51.100.10",             # a key that would collide with IP buckets
        "2001:db8::1%eth0",             # scope id
        "9" * 65,                       # over the length cap
        "198.51.100.10\r\nX: y",        # header injection attempt
    ])
    def test_on_fly_junk_header_falls_back_to_peer(self, on_fly, bad):
        assert resolve_address(PROXY, bad) == PROXY

    def test_on_fly_header_is_normalised(self, on_fly):
        assert resolve_address(PROXY, " 198.51.100.10 ") == FLY_A
        assert resolve_address(PROXY, "2001:DB8:0:0:0:0:0:1") == "2001:db8::1"

    def test_no_peer_is_unknown(self, off_fly):
        assert resolve_address(None, FLY_A) == "unknown"

    def test_empty_app_name_is_off_fly(self, monkeypatch):
        monkeypatch.setenv("FLY_APP_NAME", "")
        assert resolve_address(PROXY, FLY_A) == PROXY


# ── bucket: IPv6 by /64 ───────────────────────────────────────────────────────

class TestBucket:
    def test_ipv4_unchanged(self):
        assert bucket("198.51.100.10") == "198.51.100.10"

    def test_ipv6_by_64(self):
        assert bucket("2001:db8:abcd:1234:1::1") == "2001:db8:abcd:1234::/64"
        assert bucket("2001:db8:abcd:1234:ffff:ffff:ffff:ffff") == "2001:db8:abcd:1234::/64"
        assert bucket("2001:db8:abcd:1235::1") == "2001:db8:abcd:1235::/64"

    def test_ipv4_mapped_counts_as_ipv4(self):
        assert bucket("::ffff:198.51.100.10") == "198.51.100.10"

    def test_non_address_passes_through(self):
        assert bucket("unknown") == "unknown"


# ── The ASGI and Request front ends agree ─────────────────────────────────────

class TestFrontEnds:
    def test_scope_and_request_off_fly(self, off_fly):
        h = {"Fly-Client-IP": FLY_A}
        assert client_address(_scope(headers=h)) == PROXY
        assert request_address(_request(headers=h)) == PROXY

    def test_scope_and_request_on_fly(self, on_fly):
        h = {"Fly-Client-IP": "2001:db8:abcd:1234:1::1"}
        assert client_address(_scope(headers=h)) == "2001:db8:abcd:1234:1::1"
        assert client_bucket(_scope(headers=h)) == "2001:db8:abcd:1234::/64"
        assert request_address(_request(headers=h)) == "2001:db8:abcd:1234:1::1"
        assert request_bucket(_request(headers=h)) == "2001:db8:abcd:1234::/64"

    def test_header_name_is_case_insensitive(self, on_fly):
        assert client_address(_scope(headers={"FLY-CLIENT-IP": FLY_A})) == FLY_A

    def test_no_client_in_scope(self, off_fly):
        assert client_address({"type": "http", "headers": []}) == "unknown"
        assert request_address(_request(peer=None)) == "unknown"


# ── The slowapi key functions use it ──────────────────────────────────────────

class TestKeyFunctions:
    def test_ip_limiter_keys_on_the_resolved_caller(self):
        from src.middleware.rate_limits import get_client_ip, limiter
        assert limiter._key_func is get_client_ip

    def test_get_client_ip(self, on_fly):
        from src.middleware.rate_limits import get_client_ip
        assert get_client_ip(_request(headers={"Fly-Client-IP": FLY_A})) == FLY_A
        assert get_client_ip(_request()) == PROXY

    def test_signup_key_anonymous_on_fly(self, on_fly):
        from src.middleware.rate_limits import get_signup_key
        assert get_signup_key(_request(headers={"Fly-Client-IP": FLY_A})) == f"ip:{FLY_A}"
        assert get_signup_key(_request(headers={"Fly-Client-IP": FLY_B})) == f"ip:{FLY_B}"

    def test_signup_key_anonymous_off_fly_ignores_header(self, off_fly):
        from src.middleware.rate_limits import get_signup_key
        assert get_signup_key(_request(headers={"Fly-Client-IP": FLY_A})) == f"ip:{PROXY}"

    def test_signup_key_junk_token_on_fly(self, on_fly):
        from src.middleware.rate_limits import get_signup_key
        req = _request(headers={"Fly-Client-IP": FLY_A, "Authorization": "Bearer nope"})
        assert get_signup_key(req) == f"ip:{FLY_A}"

    def test_agent_did_fallback_on_fly(self, on_fly):
        from src.middleware.rate_limits import get_agent_did
        assert get_agent_did(_request(headers={"Fly-Client-IP": FLY_A})) == f"ip:{FLY_A}"
        req = _request(headers={"Fly-Client-IP": FLY_A, "Authorization": "Bearer nope"})
        assert get_agent_did(req) == f"ip:{FLY_A}"

    def test_agent_did_fallback_off_fly(self, off_fly):
        from src.middleware.rate_limits import get_agent_did
        assert get_agent_did(_request(headers={"Fly-Client-IP": FLY_A})) == f"ip:{PROXY}"

    def test_slowapi_default_is_not_used_anywhere(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[2] / "src"
        hits = []
        for f in src.rglob("*.py"):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                stripped = line.strip()
                if "get_remote_address" in stripped and not stripped.startswith(("#", "-", '"', "RL-1", "saw", "budget")) \
                        and "``" not in stripped:
                    hits.append(f"{f.relative_to(src)}:{n}: {stripped}")
        assert hits == [], hits


# ── End to end on the real app: sign-up budgets are per caller on Fly ─────────

def _onboard_body(name: str) -> dict:
    return {"name": name, "capabilities": ["testing"], "bio": "rl-1"}


@pytest.fixture
def onboard_without_db(monkeypatch):
    """The real /onboard route, its service replaced so no DB is touched (→ 409)."""
    from src.routers import onboard as onboard_router
    from src.services.onboard_service import DisplayNameTakenError

    async def taken(**kwargs):
        raise DisplayNameTakenError("taken")

    monkeypatch.setattr(onboard_router.onboard_service, "onboard_agent", taken)


async def _onboard(peer: str, headers: dict | None = None, name: str = "rl1"):
    from src.main import app
    transport = ASGITransport(app=app, client=(peer, 40000), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        return await c.post("/onboard", json=_onboard_body(name), headers=headers or {})


SIGNUP_PER_HOUR = 5


@pytest.mark.asyncio
async def test_on_fly_two_callers_behind_the_proxy_have_separate_signup_budgets(
    on_fly, onboard_without_db,
):
    peer = "172.19.4.10"
    for _ in range(SIGNUP_PER_HOUR):
        r = await _onboard(peer, {"Fly-Client-IP": "198.51.100.20"})
        assert r.status_code == 409, r.text
    r = await _onboard(peer, {"Fly-Client-IP": "198.51.100.20"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    # Another caller, same proxy address, is not blocked.
    r = await _onboard(peer, {"Fly-Client-IP": "198.51.100.21"})
    assert r.status_code == 409
    # The peer itself (a request with no header: not via Fly's proxy) is its own bucket.
    r = await _onboard(peer)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_off_fly_a_spoofed_header_does_not_buy_a_fresh_budget(off_fly, onboard_without_db):
    peer = "172.19.4.11"
    for _ in range(SIGNUP_PER_HOUR):
        r = await _onboard(peer, {"Fly-Client-IP": f"198.51.100.{30 + _}"})
        assert r.status_code == 409, r.text
    r = await _onboard(peer, {"Fly-Client-IP": "198.51.100.99"})
    assert r.status_code == 429
    r = await _onboard(peer)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_on_fly_ipv6_rotation_inside_a_64_shares_one_budget(on_fly, onboard_without_db):
    peer = "172.19.4.12"
    for i in range(SIGNUP_PER_HOUR):
        r = await _onboard(peer, {"Fly-Client-IP": f"2001:db8:1234:5678::{i + 1}"})
        assert r.status_code == 409, r.text
    r = await _onboard(peer, {"Fly-Client-IP": "2001:db8:1234:5678:dead:beef::1"})
    assert r.status_code == 429
    # The next /64 is somebody else.
    r = await _onboard(peer, {"Fly-Client-IP": "2001:db8:1234:5679::1"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_on_fly_junk_header_shares_the_proxy_bucket_not_a_chosen_one(on_fly, onboard_without_db):
    """A header that is not one IP falls back to the peer: never a caller-chosen key."""
    from src.middleware.rate_limits import get_signup_key
    req = _request(peer="172.19.4.13", headers={"Fly-Client-IP": "did:agentx:founder-1"})
    assert get_signup_key(req) == "ip:172.19.4.13"


@pytest.mark.asyncio
async def test_access_log_shows_the_fly_caller(on_fly, caplog):
    import logging
    from src.main import app

    caplog.set_level(logging.INFO, logger="agentx.api")
    transport = ASGITransport(app=app, client=(PROXY, 40000), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        await c.get("/rl1-log-test", headers={"Fly-Client-IP": FLY_A, "X-Forwarded-For": FLY_B})
    lines = [r.getMessage() for r in caplog.records if "/rl1-log-test" in r.getMessage()]
    assert lines and f"client={FLY_A} " in lines[0], lines
    assert f"fwd={FLY_B}" in lines[0]
