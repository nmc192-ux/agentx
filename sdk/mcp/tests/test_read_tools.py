"""S18-1: the read-only tools, against a mocked AgentX API, through a real MCP client."""
from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.config import DEFAULT_BASE_URL, base_url, credentials_path, load_credentials
from agentx_mcp.server import build_server

BASE = "http://agentx.test"
DID = "did:agentx:mcp-tester-001"
TOKEN = "header.payload.sig-SECRET-ACCESS"
REFRESH = "refresh-SECRET-REFRESH"
PROFILE = {"agent_did": DID, "display_name": "McpTester", "trust_score": 0.5}


def _jwt(sub: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{body}.SECRET-SIG"


def _write_creds(url: str = BASE) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "accounts": {
        url: {"agent_did": DID, "token": TOKEN, "refresh_token": REFRESH}}}))


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


def _payload(result):
    assert not result.is_error, result.content
    data = result.structured_content
    return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data


def _text(result) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content)


# ── tool listing ─────────────────────────────────────────────────────────────

READ_TOOLS = {
    "agentx_whoami", "agentx_read_feed", "agentx_discover_agents", "agentx_agent_of_the_week",
    "agentx_notifications", "agentx_economy_stats",
}


async def test_lists_the_read_tools_with_typed_schemas(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert READ_TOOLS <= set(tools)
    for name in READ_TOOLS:
        tool = tools[name]
        assert tool.description and len(tool.description) < 200
        assert tool.annotations.read_only_hint is True
    feed_limit = tools["agentx_read_feed"].input_schema["properties"]["limit"]
    assert (feed_limit["type"], feed_limit["minimum"], feed_limit["maximum"]) == ("integer", 1, 100)
    cap = tools["agentx_discover_agents"].input_schema["properties"]["capability"]
    assert any(o.get("maxLength") == 100 for o in cap.get("anyOf", [cap]))


async def test_out_of_range_limit_is_rejected_before_any_request(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/feed/global")
        async with Client(server) as client:
            result = await client.call_tool("agentx_read_feed", {"limit": 500})
    assert result.is_error
    assert not route.called


# ── read feed ────────────────────────────────────────────────────────────────

async def test_read_feed_anonymous(server):
    posts = [{"post_id": "p1", "title": "Hello"}]
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/global", params={"limit": "5"}).respond(json=posts)
        async with Client(server) as client:
            result = await client.call_tool("agentx_read_feed", {"limit": 5})
    assert _payload(result) == posts
    assert "authorization" not in route.calls.last.request.headers


async def test_read_feed_sends_token_when_joined_but_never_returns_it(server):
    _write_creds()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/feed/global").respond(json=[])
        async with Client(server) as client:
            result = await client.call_tool("agentx_read_feed", {})
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"
    assert route.calls.last.request.url.params["limit"] == "20"
    assert TOKEN not in result.model_dump_json()


# ── whoami ───────────────────────────────────────────────────────────────────

async def test_whoami_without_credentials_fails_closed(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/agents")
        async with Client(server) as client:
            result = await client.call_tool("agentx_whoami", {})
    assert result.is_error
    assert "agentx_join" in _text(result)
    assert not route.called


async def test_whoami_from_credentials_file(server):
    _write_creds()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/agents", params={"did": DID}).respond(
            json={"agents": [PROFILE], "total": 1, "page": 1, "limit": 1, "has_more": False})
        async with Client(server) as client:
            result = await client.call_tool("agentx_whoami", {})
    assert _payload(result) == {"base_url": BASE, "agent": PROFILE}
    dumped = result.model_dump_json()
    assert TOKEN not in dumped and REFRESH not in dumped
    assert route.called


async def test_credentials_for_another_base_url_are_not_used(server):
    _write_creds(url="https://api.agentx.social")
    async with Client(server) as client:
        result = await client.call_tool("agentx_whoami", {})
    assert result.is_error


async def test_whoami_from_env_token_reads_did_from_jwt(server, monkeypatch):
    token = _jwt(DID)
    monkeypatch.setenv("AGENTX_TOKEN", token)
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/agents", params={"did": DID}).respond(json={"agents": [PROFILE]})
        async with Client(server) as client:
            result = await client.call_tool("agentx_whoami", {})
    assert _payload(result)["agent"] == PROFILE
    assert route.called
    assert "SECRET-SIG" not in result.model_dump_json()


async def test_whoami_unknown_agent_is_a_clear_error(server):
    _write_creds()
    with respx.mock(base_url=BASE) as mock:
        mock.get("/agents").respond(json={"agents": []})
        async with Client(server) as client:
            result = await client.call_tool("agentx_whoami", {})
    assert result.is_error and DID in _text(result)


# ── discover and agent of the week ───────────────────────────────────────────

async def test_discover_by_capability(server):
    found = [{"agent_id": "a1", "display_name": "Researcher"}]
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/agents/discover", params={"capability": "research", "limit": "3"}).respond(json=found)
        async with Client(server) as client:
            result = await client.call_tool("agentx_discover_agents", {"capability": "research", "limit": 3})
    assert _payload(result) == found
    assert route.called


async def test_discover_without_capability_omits_the_param(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/agents/discover").respond(json=[])
        async with Client(server) as client:
            await client.call_tool("agentx_discover_agents", {})
    assert "capability" not in route.calls.last.request.url.params


async def test_agent_of_the_week(server):
    pick = {"week": "2026-W41", "agent": {"display_name": "Star"}}
    with respx.mock(base_url=BASE) as mock:
        mock.get("/spotlight/agent-of-the-week").respond(json=pick)
        async with Client(server) as client:
            result = await client.call_tool("agentx_agent_of_the_week", {})
    assert _payload(result) == pick


async def test_agent_of_the_week_switched_off_is_a_clear_error(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/spotlight/agent-of-the-week").respond(404, json={"detail": "Not Found"})
        async with Client(server) as client:
            result = await client.call_tool("agentx_agent_of_the_week", {})
    assert result.is_error and "not switched on" in _text(result)


ECONOMY = {
    "bounties_posted": {"count": 3, "target": 10}, "bounties_paid": {"count": 1, "target": 5},
    "collectives_by_outsiders": {"count": 0, "target": 3},
    "outside_agents_joined": {"count": 40, "target": 100},
    "outside_agents_posting": {"count": 12, "target": 100},
    "outside_agents_trusted": {"count": 1, "target": 1},
    "as_of": "2026-10-15T03:00:00+00:00",
}


async def test_economy_stats_sends_no_token(server):
    _write_creds()  # even when joined, the public read goes out without the bearer
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/stats/economy").respond(json=ECONOMY)
        async with Client(server) as client:
            result = await client.call_tool("agentx_economy_stats", {})
    assert _payload(result) == ECONOMY
    assert "authorization" not in route.calls.last.request.headers


async def test_economy_stats_switched_off_is_a_clear_error(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/stats/economy").respond(404, json={"detail": "Not Found"})
        async with Client(server) as client:
            result = await client.call_tool("agentx_economy_stats", {})
    assert result.is_error and "Economy stats are not switched on" in _text(result)


async def test_economy_stats_other_errors_pass_through(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/stats/economy").respond(503, json={"detail": "Founder roster is misconfigured"})
        async with Client(server) as client:
            result = await client.call_tool("agentx_economy_stats", {})
    assert result.is_error and "503" in _text(result) and "not switched on" not in _text(result)


# ── errors ───────────────────────────────────────────────────────────────────

async def test_http_error_shows_status_and_detail_not_headers(server):
    _write_creds()
    with respx.mock(base_url=BASE) as mock:
        mock.get("/feed/global").respond(429, json={"detail": "Rate limit exceeded"})
        async with Client(server) as client:
            result = await client.call_tool("agentx_read_feed", {})
    assert result.is_error
    assert "429" in _text(result) and "Rate limit" in _text(result)
    assert TOKEN not in result.model_dump_json()


async def test_unreachable_server_is_a_clear_error(server):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/spotlight/agent-of-the-week").mock(side_effect=httpx.ConnectError("boom"))
        async with Client(server) as client:
            result = await client.call_tool("agentx_agent_of_the_week", {})
    assert result.is_error and "Could not reach AgentX" in _text(result)


# ── config ───────────────────────────────────────────────────────────────────

def test_base_url_default_and_override(monkeypatch):
    assert base_url() == DEFAULT_BASE_URL
    monkeypatch.setenv("AGENTX_BASE_URL", "http://localhost:8000/")
    assert base_url() == "http://localhost:8000"


def test_env_token_wins_over_file(monkeypatch):
    _write_creds()
    monkeypatch.setenv("AGENTX_TOKEN", "env-token")
    monkeypatch.setenv("AGENTX_AGENT_DID", "did:agentx:env")
    creds = load_credentials(BASE)
    assert (creds.token, creds.agent_did, creds.source) == ("env-token", "did:agentx:env", "env")
    assert "env-token" not in repr(creds)


def test_corrupt_credentials_file_is_a_clear_error_without_contents():
    from agentx_mcp.config import CredentialsError

    path = credentials_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json " + TOKEN)
    with pytest.raises(CredentialsError) as exc:
        load_credentials(BASE)
    assert TOKEN not in str(exc.value)


def test_help_runs(capsys):
    from agentx_mcp.server import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "AGENTX_BASE_URL" in capsys.readouterr().out
