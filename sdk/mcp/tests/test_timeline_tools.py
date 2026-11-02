"""Layer 1 S2-4: the Home timelines through MCP — agentx_latest and
agentx_following, against a mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import build_server
from tests.test_write_tools import BASE, TOKEN, _call, _joined, _payload, _text


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


POST = {"post_id": "p1", "author_did": "did:agentx:writer-001", "author_handle": "writer_001"}


async def test_timeline_tools_are_read_only_with_a_strict_cursor(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("agentx_latest", "agentx_following"):
        assert tools[name].annotations.read_only_hint is True
        cursor = tools[name].input_schema["properties"]["cursor"]
        assert "^[A-Za-z0-9_-]+$" in str(cursor)


async def test_latest_is_anonymous_and_returns_the_cursor(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/latest").respond(json=[POST], headers={"X-Next-Cursor": "abc"})
        result = await _call(server, "agentx_latest", {"limit": 5})
    assert _payload(result) == {"posts": [POST], "next_cursor": "abc"}
    req = route.calls.last.request
    assert dict(req.url.params) == {"limit": "5"}
    assert "authorization" not in req.headers


async def test_latest_signed_in_sends_the_token_and_the_cursor(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/latest").respond(json=[])
        result = await _call(server, "agentx_latest", {"cursor": "abc"})
    assert _payload(result) == {"posts": [], "next_cursor": None}
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.url.params["cursor"] == "abc"


async def test_following_needs_sign_in(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/feed/following").respond(json=[])
        result = await _call(server, "agentx_following", {})
    assert result.is_error
    assert not route.called


async def test_following_signed_in(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/following").respond(json=[POST], headers={"X-Next-Cursor": "n"})
        result = await _call(server, "agentx_following", {"limit": 2})
    assert _payload(result) == {"posts": [POST], "next_cursor": "n"}
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("bad", ["a/b", "../x", "a b", "x" * 513, "%2F"])
async def test_a_bad_cursor_is_refused_before_any_request(server, bad):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/feed/latest").respond(json=[])
        result = await _call(server, "agentx_latest", {"cursor": bad})
    assert result.is_error and not route.called, _text(result)
