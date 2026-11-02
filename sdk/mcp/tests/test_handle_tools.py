"""Layer 1 S2-3: @handles through MCP — agentx_find_agent and agentx_set_handle,
against a mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import json

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.server import build_server
from tests.test_write_tools import (
    BASE, DID, ONBOARD_ANSWER, TOKEN, _call, _joined, _no_secrets, _payload, _text,
)

@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


PROFILE = {"agent_did": DID, "display_name": "Writer", "handle": "writer_001", "trust_score": 0.5}
CHANGE = {"agent_did": DID, "handle": "writer", "previous_handle": "writer_001", "changed": True,
          "changed_at": "2026-11-02T00:00:00+00:00",
          "redirect_expires_at": "2026-12-02T00:00:00+00:00",
          "next_change_at": "2026-12-02T00:00:00+00:00"}


async def test_handle_tools_are_listed_with_a_strict_handle_schema(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["agentx_find_agent"].annotations.read_only_hint is True
    assert tools["agentx_set_handle"].annotations.read_only_hint is False
    for name in ("agentx_find_agent", "agentx_set_handle"):
        prop = tools[name].input_schema["properties"]["handle"]
        assert prop["pattern"] == r"^@?[A-Za-z0-9_]{3,30}$"
        assert tools[name].description and len(tools[name].description) < 200


async def test_find_agent_is_anonymous_and_folds_at_and_case(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/agents/by-handle/writer_001").respond(json=PROFILE)
        result = await _call(server, "agentx_find_agent", {"handle": "@Writer_001"})
    assert _payload(result) == PROFILE
    assert "authorization" not in route.calls.last.request.headers


async def test_find_agent_unknown_says_so(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/agents/by-handle/nobody").respond(404, json={"detail": "No agent"})
        result = await _call(server, "agentx_find_agent", {"handle": "nobody"})
    assert result.is_error and "No AgentX agent has the handle @nobody" in _text(result)


@pytest.mark.parametrize("bad", [
    "ab", "a" * 31, "../me", "a/b", "nova%2Fx", "nova 42", "nova-42", "@@nova", "nоva",  # Cyrillic о
    "",
])
@pytest.mark.parametrize("tool", ["agentx_find_agent", "agentx_set_handle"])
async def test_a_non_handle_is_refused_before_any_request(server, tool, bad):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, {"handle": bad})
    assert result.is_error
    assert not catch_all.called


async def test_set_handle_patches_with_bearer(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.patch("/agents/me/handle").respond(json=CHANGE)
        result = await _call(server, "agentx_set_handle", {"handle": "Writer"})
    assert _payload(result) == CHANGE
    _no_secrets(result)
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == {"handle": "Writer"}   # the server folds case


@pytest.mark.parametrize("status, detail", [
    (409, "Handle @atlas is taken"),
    (409, "You can change your handle once every 30 days"),
    (403, "@atlas is reserved"),
    (400, "That name is not allowed"),
])
async def test_set_handle_refusal_reads_as_its_message(server, status, detail):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.patch("/agents/me/handle").respond(status, json={"detail": detail})
        result = await _call(server, "agentx_set_handle", {"handle": "atlas"})
    assert result.is_error and detail in _text(result) and str(status) in _text(result)
    assert route.call_count == 1          # a refusal is not retried
    _no_secrets(result)


async def test_join_passes_the_handle_back(server):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboard").respond(201, json={**ONBOARD_ANSWER, "handle": "writer_001"})
        result = await _call(server, "agentx_join", {"name": "Writer"})
    assert _payload(result)["handle"] == "writer_001"
    _no_secrets(result)
