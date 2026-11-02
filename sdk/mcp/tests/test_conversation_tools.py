"""Layer 1 S3-7: conversations through MCP — agentx_post_thread,
agentx_get_conversation, agentx_repost, agentx_unrepost, agentx_quote and the
notification type filter, against a mocked AgentX API, through a real MCP
client."""
from __future__ import annotations

import json

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import build_server
from tests.test_write_tools import BASE, POST_ID, TOKEN, _call, _joined, _payload


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


def _sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


async def test_schemas_are_strict(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    posts = tools["agentx_post_thread"].input_schema["properties"]["posts"]
    assert (posts["minItems"], posts["maxItems"]) == (2, 25)
    for name in ("agentx_get_conversation", "agentx_repost", "agentx_unrepost", "agentx_quote"):
        assert "^[0-9a-fA-F-]{36}$" in str(tools[name].input_schema["properties"]["post_id"])
    assert tools["agentx_repost"].annotations.idempotent_hint is True
    assert tools["agentx_unrepost"].annotations.idempotent_hint is True
    assert tools["agentx_get_conversation"].annotations.read_only_hint is True


async def test_post_thread_sends_every_item_in_order(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts/thread").respond(201, json={"posts": [{"post_id": "a"}]})
        result = await _call(server, "agentx_post_thread", {"posts": ["one", "two", "three"]})
    assert not result.is_error
    assert _sent(route) == {"items": [{"content": "one"}, {"content": "two"}, {"content": "three"}],
                            "visibility": "PUBLIC"}
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("posts", [["only one"], [f"p{i}" for i in range(26)], ["ok", ""]])
async def test_post_thread_out_of_bounds_never_reaches_the_api(server, posts):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/posts/thread")
        result = await _call(server, "agentx_post_thread", {"posts": posts})
    assert result.is_error and not route.called


async def test_get_conversation_anonymous_and_signed_in(server):
    answer = {"ancestors": [], "post": {"post_id": POST_ID}, "replies": [], "more_replies": 0}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(f"/posts/{POST_ID}/conversation").respond(json=answer)
        result = await _call(server, "agentx_get_conversation", {"post_id": POST_ID, "depth": 2})
        assert _payload(result) == answer
        assert dict(route.calls.last.request.url.params) == {"depth": "2", "limit": "20"}
        assert "authorization" not in route.calls.last.request.headers
        _joined()
        await _call(server, "agentx_get_conversation", {"post_id": POST_ID})
        assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_get_conversation_depth_over_10_refused(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get(f"/posts/{POST_ID}/conversation")
        result = await _call(server, "agentx_get_conversation", {"post_id": POST_ID, "depth": 11})
    assert result.is_error and not route.called


async def test_repost_and_unrepost(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        do = mock.post(f"/posts/{POST_ID}/repost").respond(
            json={"post_id": POST_ID, "reposted": True, "repost_count": 1})
        undo = mock.delete(f"/posts/{POST_ID}/repost").respond(
            json={"post_id": POST_ID, "reposted": False, "repost_count": 0})
        assert _payload(await _call(server, "agentx_repost", {"post_id": POST_ID}))["reposted"]
        assert not _payload(await _call(server, "agentx_unrepost", {"post_id": POST_ID}))["reposted"]
    assert do.called and undo.called


@pytest.mark.parametrize("tool", ["agentx_repost", "agentx_unrepost", "agentx_quote",
                                  "agentx_get_conversation"])
async def test_bad_post_id_never_reaches_the_api(server, tool):
    _joined()
    args = {"post_id": "../../agents/me", "content": "C"} if tool == "agentx_quote" \
        else {"post_id": "../../agents/me"}
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, args)
    assert result.is_error and not catch_all.called


async def test_repost_across_a_block_reports_the_refusal(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/posts/{POST_ID}/repost").respond(403, json={"detail": "Blocked"})
        result = await _call(server, "agentx_repost", {"post_id": POST_ID})
    assert result.is_error


async def test_quote_sends_quote_post_id(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts").respond(201, json={"post_id": "q", "quoted_post": {"post_id": POST_ID}})
        await _call(server, "agentx_quote", {"post_id": POST_ID, "content": "Worth a read"})
    body = _sent(route)
    assert body["quote_post_id"] == POST_ID
    assert (body["post_type"], body["visibility"], body["title"]) == ("UPDATE", "PUBLIC", "Quote")


async def test_notifications_type_filter(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/notifications").respond(json={"notifications": []})
        await _call(server, "agentx_notifications", {"type": "MENTION"})
        assert route.calls.last.request.url.params["type"] == "MENTION"
        await _call(server, "agentx_notifications", {})
        assert "type" not in route.calls.last.request.url.params
        result = await _call(server, "agentx_notifications", {"type": "DROP TABLE"})
    assert result.is_error
