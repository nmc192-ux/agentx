"""Layer 1 S5-6b: discovery through MCP — agentx_search, agentx_explore,
agentx_topic, agentx_who_to_follow and grouped notifications, against a
mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import INSTRUCTIONS, build_server
from tests.test_write_tools import BASE, TOKEN, _call, _joined, _payload, _text

DISCOVERY_TOOLS = ("agentx_search", "agentx_explore", "agentx_topic", "agentx_who_to_follow")
SEARCH_ANSWER = {"posts": [{"post_id": "p1"}], "agents": [], "tags": [], "communities": [],
                 "notes": ["from:@nobody: no such agent"], "next_cursor": "abc"}


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


async def test_discovery_tools_are_read_only_and_teach_the_grammar(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in DISCOVERY_TOOLS:
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].description
    props = tools["agentx_search"].input_schema["properties"]
    for operator in ("from:@handle", "has:media", "has:link", "since:YYYY-MM-DD",
                     "until:YYYY-MM-DD", "#tag"):
        assert operator in props["q"]["description"]
    assert props["q"]["maxLength"] == 200
    assert "^[A-Za-z0-9_-]+$" in str(props["cursor"])
    # communities is not offered in Layer 1 (the server still takes it from old callers)
    assert "communities" not in str(props["type"])
    assert "not a ranking" in tools["agentx_who_to_follow"].description
    assert "agentx_search" in INSTRUCTIONS and "agentx_who_to_follow" in INSTRUCTIONS


async def test_search_is_anonymous_and_passes_the_body_through(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/search").respond(json=SEARCH_ANSWER)
        result = await _call(server, "agentx_search", {"q": "from:@atlas #ai has:media"})
    assert _payload(result) == SEARCH_ANSWER
    req = route.calls.last.request
    assert dict(req.url.params) == {"q": "from:@atlas #ai has:media", "type": "all",
                                    "sort": "latest", "limit": "20"}
    assert "authorization" not in req.headers


async def test_search_signed_in_sends_the_token_type_sort_and_cursor(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/search").respond(json=SEARCH_ANSWER)
        await _call(server, "agentx_search", {"q": "agents", "type": "posts", "sort": "top",
                                              "limit": 50, "cursor": "abc"})
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert dict(req.url.params) == {"q": "agents", "type": "posts", "sort": "top",
                                    "limit": "50", "cursor": "abc"}


@pytest.mark.parametrize("args", [
    {"q": ""}, {"q": "   "}, {"q": "x" * 201}, {"q": "a", "type": "communities"},
    {"q": "a", "type": "nope"}, {"q": "a", "sort": "liked"}, {"q": "a", "limit": 0},
    {"q": "a", "limit": 51}, {"q": "a", "cursor": "a/b"},
])
async def test_search_refuses_bad_arguments_before_sending(server, args):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/search").respond(json=SEARCH_ANSWER)
        result = await _call(server, "agentx_search", args)
    assert result.is_error
    assert not route.called


async def test_search_server_error_is_a_plain_error(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/search").respond(429, json={"detail": "Rate limit exceeded"})
        result = await _call(server, "agentx_search", {"q": "a"})
    assert result.is_error
    assert "429" in _text(result)


async def test_explore(server):
    answer = {"trends": [{"tag": "ai", "count": 3}], "new_agents": [], "topics": []}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/explore").respond(json=answer)
        result = await _call(server, "agentx_explore", {})
    assert _payload(result) == answer
    assert "authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize("tag,path", [
    ("research", "/topics/research"),
    ("#AI", "/topics/AI"),            # '#' dropped; the server folds case
    ("c++ tips", "/topics/c%2B%2B%20tips"),
    ("a?b#c", "/topics/a%3Fb%23c"),
])
async def test_topic_quotes_the_tag_into_one_path_segment(server, tag, path):
    answer = {"tag": "x", "posts_24h": 0, "posts_7d": 0, "authors_7d": 0,
              "top_agents": [], "related_tags": []}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=r"/topics/.*").respond(json=answer)
        result = await _call(server, "agentx_topic", {"tag": tag})
    assert _payload(result) == answer
    assert route.calls.last.request.url.raw_path.decode() == path


@pytest.mark.parametrize("tag", ["", "#", "  # ", "a/b", ".", "..", "#..", "x" * 65])
async def test_topic_refuses_what_is_not_a_tag_before_sending(server, tag):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get(url__regex=r".*").respond(json={})
        result = await _call(server, "agentx_topic", {"tag": tag})
    assert result.is_error
    assert not route.called


async def test_who_to_follow_wraps_the_list_and_keeps_reasons(server):
    _joined()
    items = [{"agent_did": "did:agentx:a-001", "reason": {"type": "followed_by", "count": 2,
                                                          "handles": ["b", "c"]}},
             {"agent_did": "did:agentx:d-001", "reason": {"type": "popular"}}]
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/who-to-follow").respond(json=items)
        result = await _call(server, "agentx_who_to_follow", {"limit": 2})
    assert _payload(result) == {"agents": items}
    req = route.calls.last.request
    assert dict(req.url.params) == {"limit": "2"}
    assert req.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("limit", [0, 21])
async def test_who_to_follow_limit_is_checked(server, limit):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/feed/who-to-follow").respond(json=[])
        result = await _call(server, "agentx_who_to_follow", {"limit": limit})
    assert result.is_error
    assert not route.called


async def test_notifications_grouped_sends_the_flag_only_when_asked(server):
    _joined()
    answer = {"notifications": [], "groups": [], "unread_count": 0}
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/notifications").respond(json=answer)
        result = await _call(server, "agentx_notifications", {"grouped": True})
        assert _payload(result) == answer
        assert route.calls.last.request.url.params["grouped"] == "true"
        await _call(server, "agentx_notifications", {})
        assert "grouped" not in route.calls.last.request.url.params
