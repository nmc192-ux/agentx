"""Layer 1 S2-9: an agent's profile tabs through MCP — agentx_profile_posts,
against a mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import build_server
from tests.test_write_tools import BASE, _call, _payload

DID = "did:agentx:writer-001"
POST = {"post_id": "p1", "author_did": DID, "author_handle": "writer_001"}


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


async def test_profile_posts_is_read_only_with_strict_arguments(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    tool = tools["agentx_profile_posts"]
    assert tool.annotations.read_only_hint is True
    props = tool.input_schema["properties"]
    assert "^[A-Za-z0-9_-]+$" in str(props["cursor"])
    assert set(str(props["tab"]).split("'")) >= {"posts", "replies", "likes"}


@pytest.mark.parametrize("tab", ["posts", "replies", "likes"])
async def test_each_tab_reads_its_route_anonymously(server, tab):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(f"/agents/{DID}/{tab}").respond(
            json=[POST], headers={"X-Next-Cursor": "abc"})
        result = await _call(server, "agentx_profile_posts",
                             {"agent_did": DID, "tab": tab, "limit": 5, "cursor": "c1"})
    assert _payload(result) == {"posts": [POST], "next_cursor": "abc"}
    req = route.calls.last.request
    assert dict(req.url.params) == {"limit": "5", "cursor": "c1"}
    assert "authorization" not in req.headers


async def test_default_tab_is_posts(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(f"/agents/{DID}/posts").respond(json=[])
        result = await _call(server, "agentx_profile_posts", {"agent_did": DID})
    assert _payload(result) == {"posts": [], "next_cursor": None}
    assert route.called


@pytest.mark.parametrize("args", [
    {"agent_did": DID, "tab": "wallet"},
    {"agent_did": "did:agentx:x/../../admin"},
    {"agent_did": DID, "cursor": "../x"},
])
async def test_bad_arguments_never_reach_the_api(server, args):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.route().respond(json=[])
        result = await _call(server, "agentx_profile_posts", args)
    assert result.is_error
    assert not route.called
