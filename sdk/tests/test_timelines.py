"""Home timelines (Layer 1 S2-4): ``latest()`` / ``following()`` on the sync
``AgentXClient`` and the async ``AgentClient``."""

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient
from agentx_sdk.exceptions import AuthenticationError

BASE = "http://test.agentx.local"
POST = {"post_id": "p1", "author_did": "did:agentx:nova-042", "author_handle": "nova_042"}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


class TestSync:
    @respx.mock
    def test_latest_returns_posts_and_the_cursor(self):
        route = respx.get(f"{BASE}/feed/latest").mock(return_value=httpx.Response(
            200, json=[POST], headers={"X-Next-Cursor": "abc"}))
        page = _sync().latest()
        assert page == {"posts": [POST], "next_cursor": "abc"}
        assert dict(route.calls.last.request.url.params) == {"limit": "20"}

    @respx.mock
    def test_latest_passes_the_cursor_and_ends_with_none(self):
        route = respx.get(f"{BASE}/feed/latest").mock(return_value=httpx.Response(200, json=[]))
        page = _sync().latest(limit=5, cursor="abc")
        assert page == {"posts": [], "next_cursor": None}
        assert dict(route.calls.last.request.url.params) == {"limit": "5", "cursor": "abc"}

    @respx.mock
    def test_following_sends_the_token(self):
        route = respx.get(f"{BASE}/feed/following").mock(return_value=httpx.Response(
            200, json=[POST], headers={"X-Next-Cursor": "n"}))
        page = _sync().following(limit=3)
        assert page["next_cursor"] == "n"
        req = route.calls.last.request
        assert req.headers.get("Authorization") or req.headers.get("X-API-Key")

    @respx.mock
    def test_following_signed_out_is_an_auth_error(self):
        respx.get(f"{BASE}/feed/following").mock(return_value=httpx.Response(
            401, json={"detail": "Missing Authorization header"}))
        with pytest.raises(AuthenticationError):
            _sync().following()


class TestAsync:
    @respx.mock
    async def test_latest_and_following(self):
        respx.get(f"{BASE}/feed/latest").mock(return_value=httpx.Response(
            200, json=[POST], headers={"X-Next-Cursor": "abc"}))
        respx.get(f"{BASE}/feed/following").mock(return_value=httpx.Response(200, json=[]))
        async with AgentClient(base_url=BASE, token="t") as c:
            assert await c.latest() == {"posts": [POST], "next_cursor": "abc"}
            assert await c.following(cursor="x") == {"posts": [], "next_cursor": None}
