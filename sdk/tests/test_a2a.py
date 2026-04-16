"""
agentx_sdk — A2ANamespace unit tests (no live server required).

Uses respx to mock httpx requests.

Coverage:
  discover_remote()  — GET {url}/.well-known/agent.json via httpx directly
  send_message()     — POST {url}/a2a with JSON-RPC 2.0 envelope
  get_my_card()      — GET /agents/{did}/.well-known/agent.json via platform client
  A2ANamespace wired — client.a2a accessible after __init__
  get_my_card() error — RuntimeError when no identity set
  send_message() caller_did — included when identity is set
  send_message() context_id — forwarded into message envelope
  send_message() metadata   — merged with caller_did
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch, MagicMock

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, A2ANamespace

# ── Constants ─────────────────────────────────────────────────────────────────

BASE      = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
REMOTE    = "https://remote-agent.example.com"

TASK_ID   = str(uuid.uuid4())


def _client_no_identity() -> AgentXClient:
    return AgentXClient(api_key="test-token", base_url=BASE)


def _client_with_identity() -> AgentXClient:
    client = AgentXClient(api_key="test-token", base_url=BASE)
    client.identity = AgentIdentity(
        agent_did=AGENT_DID,
        api_key="test-token",
        display_name="TestBot",
    )
    return client


def _agent_card() -> dict:
    return {
        "name":        "Remote Agent",
        "description": "A remote A2A agent",
        "version":     "1.0",
        "url":         REMOTE,
        "skills":      [{"id": "translate", "name": "Translate text"}],
    }


def _rpc_success(task_id: str = TASK_ID) -> dict:
    return {
        "jsonrpc": "2.0",
        "id":      "request-123",
        "result": {
            "id":     task_id,
            "status": {"state": "submitted"},
        },
    }


# ── A2ANamespace wiring ───────────────────────────────────────────────────────

class TestA2ANamespaceWiring:

    def test_client_has_a2a_attribute(self):
        client = _client_no_identity()
        assert hasattr(client, "a2a")
        assert isinstance(client.a2a, A2ANamespace)

    def test_a2a_namespace_exported(self):
        from agentx_sdk import A2ANamespace as Exported
        assert Exported is A2ANamespace

    def test_a2a_namespace_holds_client_ref(self):
        client = _client_no_identity()
        assert client.a2a._client is client


# ── discover_remote ───────────────────────────────────────────────────────────

class TestDiscoverRemote:

    @respx.mock
    def test_happy_path_returns_agent_card(self):
        card = _agent_card()
        respx.get(f"{REMOTE}/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card)
        )
        client = _client_no_identity()
        result = client.a2a.discover_remote(REMOTE)
        assert result["name"] == "Remote Agent"
        assert result["skills"][0]["id"] == "translate"

    @respx.mock
    def test_strips_trailing_slash(self):
        card = _agent_card()
        respx.get(f"{REMOTE}/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card)
        )
        client = _client_no_identity()
        result = client.a2a.discover_remote(REMOTE + "/")
        assert result["name"] == "Remote Agent"

    @respx.mock
    def test_http_error_propagates(self):
        respx.get(f"{REMOTE}/.well-known/agent.json").mock(
            return_value=httpx.Response(404)
        )
        client = _client_no_identity()
        with pytest.raises(httpx.HTTPStatusError):
            client.a2a.discover_remote(REMOTE)


# ── send_message ──────────────────────────────────────────────────────────────

class TestSendMessage:

    @respx.mock
    def test_happy_path_returns_rpc_response(self):
        rpc_resp = _rpc_success()
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=rpc_resp)
        )
        client = _client_no_identity()
        result = client.a2a.send_message(REMOTE, "Hello agent!")
        assert result["result"]["status"]["state"] == "submitted"
        assert result["jsonrpc"] == "2.0"

    @respx.mock
    def test_posts_to_a2a_endpoint(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "test message")
        assert respx.calls.call_count == 1
        url = str(respx.calls.last.request.url)
        assert url.endswith("/a2a")

    @respx.mock
    def test_jsonrpc_envelope_is_correct(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "envelope test")
        body = json.loads(respx.calls.last.request.content)
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "message/send"
        assert "id" in body
        assert "params" in body
        msg = body["params"]["message"]
        assert msg["role"] == "user"
        assert msg["parts"][0]["kind"] == "text"
        assert msg["parts"][0]["text"] == "envelope test"

    @respx.mock
    def test_caller_did_included_when_identity_set(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_with_identity()
        client.a2a.send_message(REMOTE, "hi with identity")
        body = json.loads(respx.calls.last.request.content)
        assert body["params"]["metadata"]["caller_did"] == AGENT_DID

    @respx.mock
    def test_caller_did_absent_when_no_identity(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "anonymous")
        body = json.loads(respx.calls.last.request.content)
        assert "caller_did" not in body["params"]["metadata"]

    @respx.mock
    def test_context_id_forwarded(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "session msg", context_id="ctx-xyz")
        body = json.loads(respx.calls.last.request.content)
        assert body["params"]["message"]["contextId"] == "ctx-xyz"

    @respx.mock
    def test_context_id_omitted_when_none(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "no context")
        body = json.loads(respx.calls.last.request.content)
        assert "contextId" not in body["params"]["message"]

    @respx.mock
    def test_extra_metadata_merged(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE, "meta msg", metadata={"priority": "high"})
        body = json.loads(respx.calls.last.request.content)
        assert body["params"]["metadata"]["priority"] == "high"

    @respx.mock
    def test_trailing_slash_stripped_from_url(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(200, json=_rpc_success())
        )
        client = _client_no_identity()
        client.a2a.send_message(REMOTE + "/", "trailing slash test")
        url = str(respx.calls.last.request.url)
        assert url.endswith("/a2a")
        assert "//" not in url.split("://", 1)[1]

    @respx.mock
    def test_http_error_propagates(self):
        respx.post(f"{REMOTE}/a2a").mock(
            return_value=httpx.Response(500)
        )
        client = _client_no_identity()
        with pytest.raises(httpx.HTTPStatusError):
            client.a2a.send_message(REMOTE, "will fail")


# ── get_my_card ───────────────────────────────────────────────────────────────

class TestGetMyCard:

    def test_raises_runtime_error_when_no_identity(self):
        client = _client_no_identity()
        with pytest.raises(RuntimeError, match="registered identity"):
            client.a2a.get_my_card()

    @respx.mock
    def test_fetches_card_from_platform(self):
        card = _agent_card()
        respx.get(f"{BASE}/agents/{AGENT_DID}/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card)
        )
        client = _client_with_identity()
        result = client.a2a.get_my_card()
        assert result["name"] == "Remote Agent"

    @respx.mock
    def test_uses_agent_did_from_identity(self):
        card = _agent_card()
        route = respx.get(f"{BASE}/agents/{AGENT_DID}/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card)
        )
        client = _client_with_identity()
        client.a2a.get_my_card()
        assert route.called
