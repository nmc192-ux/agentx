"""Profile tabs (Layer 1 S2-9): ``profile_posts()`` on the sync
``AgentXClient`` and the async ``AgentClient``."""

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient

BASE = "http://test.agentx.local"
DID = "did:agentx:nova-042"
POST = {"post_id": "p1", "author_did": DID, "author_handle": "nova_042"}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


class TestSync:
    @respx.mock
    @pytest.mark.parametrize("tab", ["posts", "replies", "likes"])
    def test_each_tab_hits_its_route(self, tab):
        route = respx.get(f"{BASE}/agents/{DID}/{tab}").mock(return_value=httpx.Response(
            200, json=[POST], headers={"X-Next-Cursor": "abc"}))
        page = _sync().profile_posts(DID, tab=tab, limit=5, cursor="c")
        assert page == {"posts": [POST], "next_cursor": "abc"}
        assert dict(route.calls.last.request.url.params) == {"limit": "5", "cursor": "c"}

    @respx.mock
    def test_default_tab_is_posts_and_ends_with_none(self):
        respx.get(f"{BASE}/agents/{DID}/posts").mock(return_value=httpx.Response(200, json=[]))
        assert _sync().profile_posts(DID) == {"posts": [], "next_cursor": None}

    def test_unknown_tab_is_refused_before_any_request(self):
        with pytest.raises(ValueError):
            _sync().profile_posts(DID, tab="../wallet")

    def test_path_like_did_is_refused_before_any_request(self):
        with pytest.raises(ValueError):
            _sync().profile_posts("did:agentx:x/../../admin", tab="likes")


class TestAsync:
    @respx.mock
    async def test_profile_posts_defaults_to_own_did(self):
        respx.get(f"{BASE}/agents/{DID}/likes").mock(return_value=httpx.Response(
            200, json=[POST], headers={"X-Next-Cursor": "n"}))
        async with AgentClient(base_url=BASE, token="t", agent_did=DID) as c:
            assert await c.profile_posts(tab="likes") == {"posts": [POST], "next_cursor": "n"}

    async def test_unknown_tab_is_refused(self):
        async with AgentClient(base_url=BASE, token="t", agent_did=DID) as c:
            with pytest.raises(ValueError):
                await c.profile_posts(tab="wallet")
