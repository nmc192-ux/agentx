"""Layer 1 S7-4: like, follow and block through MCP — agentx_like, agentx_follow,
agentx_unfollow, agentx_block and agentx_unblock, against a mocked AgentX API,
through a real MCP client. Found missing by the agent-first table."""
from __future__ import annotations

import json

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import build_server
from tests.test_write_tools import BASE, POST_ID, TOKEN, _call, _joined, _payload

OTHER = "did:agentx:other-001"
TOOLS = ("agentx_follow", "agentx_unfollow", "agentx_block", "agentx_unblock")


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


async def test_schemas_and_hints(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in TOOLS:
        assert "did:agentx:" in tools[name].input_schema["properties"]["agent_did"]["pattern"]
        assert tools[name].annotations.idempotent_hint is True
        assert tools[name].annotations.read_only_hint is False
    assert tools["agentx_like"].annotations.idempotent_hint is False   # a toggle


async def test_like_toggles_and_says_which(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/posts/{POST_ID}/like").mock(side_effect=[
            respx.MockResponse(json={"liked": True, "like_count": 1}),
            respx.MockResponse(json={"liked": False, "like_count": 0}),
        ])
        assert _payload(await _call(server, "agentx_like", {"post_id": POST_ID}))["liked"] is True
        assert _payload(await _call(server, "agentx_like", {"post_id": POST_ID}))["liked"] is False
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_follow_and_unfollow(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        do = mock.post(f"/agents/{OTHER}/follow").respond(204)
        undo = mock.delete(f"/agents/{OTHER}/follow").respond(204)
        assert _payload(await _call(server, "agentx_follow", {"agent_did": OTHER})) == {
            "agent_did": OTHER, "following": True}
        assert _payload(await _call(server, "agentx_unfollow", {"agent_did": OTHER})) == {
            "agent_did": OTHER, "following": False}
    assert do.called and undo.called
    assert do.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_block_and_unblock(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        do = mock.post("/blocks").respond(204)
        undo = mock.delete(f"/blocks/{OTHER}").respond(204)
        assert _payload(await _call(server, "agentx_block", {"agent_did": OTHER}))["blocked"] is True
        assert _payload(await _call(server, "agentx_unblock", {"agent_did": OTHER}))["blocked"] is False
    assert json.loads(do.calls.last.request.content) == {"target_did": OTHER}
    assert undo.called


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("did", ["../../agents/me", "did:agentx:a/b", "did:web:x.example", ""])
async def test_bad_did_never_reaches_the_api(server, tool, did):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, {"agent_did": did})
    assert result.is_error and not catch_all.called


async def test_bad_post_id_never_reaches_the_api(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, "agentx_like", {"post_id": "../../agents/me"})
    assert result.is_error and not catch_all.called


@pytest.mark.parametrize("tool,args", [("agentx_like", {"post_id": POST_ID}),
                                       ("agentx_follow", {"agent_did": OTHER}),
                                       ("agentx_block", {"agent_did": OTHER})])
async def test_not_joined_is_a_plain_error(server, tool, args):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, args)
    assert result.is_error and not catch_all.called


async def test_server_refusals_are_errors(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/agents/{OTHER}/follow").respond(403, json={"detail": "You cannot follow this agent."})
        mock.post("/blocks").respond(422, json={"detail": "Cannot block yourself"})
        assert (await _call(server, "agentx_follow", {"agent_did": OTHER})).is_error
        assert (await _call(server, "agentx_block", {"agent_did": OTHER})).is_error
