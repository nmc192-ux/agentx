"""
Tests: agentx_sdk/nodes.py — NodesClient
Phase 17 — Federated AgentX Nodes
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentx_sdk.nodes import NodesClient

NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(token: str | None = "tok") -> NodesClient:
    return NodesClient(base_url="https://api.agentx.io", token=token, timeout=5.0)


def _mock_response(data, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=data)
    resp.raise_for_status = MagicMock()
    if status >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "", request=MagicMock(), response=resp
        )
    return resp


def _node_dict(url: str = "https://peer.io") -> dict:
    return {
        "node_id": str(uuid4()),
        "node_url": url,
        "node_name": "Peer",
        "public_key": None,
        "status": "active",
        "trust_level": 0.5,
        "registered_at": NOW.isoformat(),
        "last_seen_at": None,
    }


def _msg_dict(event_type: str = "CONTRACT_COMPLETED") -> dict:
    return {
        "message_id": str(uuid4()),
        "node_id": None,
        "event_type": event_type,
        "payload": {},
        "direction": "inbound",
        "created_at": NOW.isoformat(),
    }


def _patched_client(resp):
    """Patch httpx.AsyncClient so that both get and post return *resp*."""
    mock_http = AsyncMock()
    mock_http.get  = AsyncMock(return_value=resp)
    mock_http.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_http)
    cm.__aexit__  = AsyncMock(return_value=False)
    return mock_http, patch("agentx_sdk.nodes.httpx.AsyncClient", return_value=cm)


# ─────────────────────────────────────────────────────────────────────────────
# NodesClient.register_node
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterNode:

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        client = _make_client()
        node   = _node_dict()
        resp   = _mock_response(node, 201)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            result = await client.register_node("https://peer.io")
        assert result["node_url"] == "https://peer.io"

    @pytest.mark.asyncio
    async def test_posts_to_correct_url(self):
        client = _make_client()
        node   = _node_dict()
        resp   = _mock_response(node, 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io")
        called_url = mock_http.post.call_args[0][0]
        assert called_url.endswith("/nodes/register")

    @pytest.mark.asyncio
    async def test_includes_node_name_in_body(self):
        client = _make_client()
        resp   = _mock_response(_node_dict(), 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io", node_name="MyNode")
        body = mock_http.post.call_args[1]["json"]
        assert body["node_name"] == "MyNode"

    @pytest.mark.asyncio
    async def test_includes_public_key_in_body(self):
        client = _make_client()
        resp   = _mock_response(_node_dict(), 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io", public_key="pem")
        body = mock_http.post.call_args[1]["json"]
        assert body["public_key"] == "pem"

    @pytest.mark.asyncio
    async def test_omits_name_when_none(self):
        client = _make_client()
        resp   = _mock_response(_node_dict(), 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io")
        body = mock_http.post.call_args[1]["json"]
        assert "node_name" not in body

    @pytest.mark.asyncio
    async def test_sends_auth_header_when_token_set(self):
        client = _make_client(token="my-jwt")
        resp   = _mock_response(_node_dict(), 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io")
        headers = mock_http.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-jwt"

    @pytest.mark.asyncio
    async def test_no_auth_header_without_token(self):
        client = _make_client(token=None)
        resp   = _mock_response(_node_dict(), 201)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.register_node("https://peer.io")
        headers = mock_http.post.call_args[1]["headers"]
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        import httpx
        client = _make_client()
        resp   = _mock_response({}, 400)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            with pytest.raises(httpx.HTTPStatusError):
                await client.register_node("https://peer.io")


# ─────────────────────────────────────────────────────────────────────────────
# NodesClient.list_nodes
# ─────────────────────────────────────────────────────────────────────────────

class TestListNodes:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        client = _make_client()
        nodes  = [_node_dict(f"https://peer{i}.io") for i in range(2)]
        resp   = _mock_response(nodes)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            result = await client.list_nodes()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_list(self):
        client = _make_client()
        resp   = _mock_response([])
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            result = await client.list_nodes()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_request_to_correct_url(self):
        client = _make_client()
        resp   = _mock_response([])
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.list_nodes()
        called_url = mock_http.get.call_args[0][0]
        assert called_url.endswith("/nodes")

    @pytest.mark.asyncio
    async def test_active_only_param_sent(self):
        client = _make_client()
        resp   = _mock_response([])
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.list_nodes(active_only=True)
        params = mock_http.get.call_args[1].get("params", {})
        assert params.get("active_only") == "true"

    @pytest.mark.asyncio
    async def test_no_params_when_active_only_false(self):
        client = _make_client()
        resp   = _mock_response([])
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.list_nodes(active_only=False)
        params = mock_http.get.call_args[1].get("params", {})
        assert not params  # empty dict

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        import httpx
        client = _make_client()
        resp   = _mock_response({}, 500)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            with pytest.raises(httpx.HTTPStatusError):
                await client.list_nodes()


# ─────────────────────────────────────────────────────────────────────────────
# NodesClient.send_event
# ─────────────────────────────────────────────────────────────────────────────

class TestSendEvent:

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        client = _make_client()
        msg    = _msg_dict("TASK_COMPLETED")
        resp   = _mock_response(msg, 202)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            result = await client.send_event("TASK_COMPLETED", {"x": 1})
        assert result["event_type"] == "TASK_COMPLETED"

    @pytest.mark.asyncio
    async def test_posts_to_nodes_events(self):
        client = _make_client()
        resp   = _mock_response(_msg_dict(), 202)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.send_event("X")
        called_url = mock_http.post.call_args[0][0]
        assert called_url.endswith("/nodes/events")

    @pytest.mark.asyncio
    async def test_body_contains_event_type(self):
        client = _make_client()
        resp   = _mock_response(_msg_dict(), 202)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.send_event("CONTRACT_COMPLETED", {"c": 1})
        body = mock_http.post.call_args[1]["json"]
        assert body["event_type"] == "CONTRACT_COMPLETED"
        assert body["payload"] == {"c": 1}

    @pytest.mark.asyncio
    async def test_none_payload_defaults_to_empty(self):
        client = _make_client()
        resp   = _mock_response(_msg_dict(), 202)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.send_event("X")
        body = mock_http.post.call_args[1]["json"]
        assert body["payload"] == {}

    @pytest.mark.asyncio
    async def test_source_node_url_included_when_set(self):
        client = _make_client()
        resp   = _mock_response(_msg_dict(), 202)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.send_event("X", source_node_url="https://me.io")
        body = mock_http.post.call_args[1]["json"]
        assert body["source_node_url"] == "https://me.io"

    @pytest.mark.asyncio
    async def test_source_node_url_omitted_when_none(self):
        client = _make_client()
        resp   = _mock_response(_msg_dict(), 202)
        mock_http, patch_ctx = _patched_client(resp)
        with patch_ctx:
            await client.send_event("X", source_node_url=None)
        body = mock_http.post.call_args[1]["json"]
        assert "source_node_url" not in body

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        import httpx
        client = _make_client()
        resp   = _mock_response({}, 422)
        _, patch_ctx = _patched_client(resp)
        with patch_ctx:
            with pytest.raises(httpx.HTTPStatusError):
                await client.send_event("BAD")


# ─────────────────────────────────────────────────────────────────────────────
# NodesClient internals
# ─────────────────────────────────────────────────────────────────────────────

class TestNodesClientInternals:

    def test_base_url_trailing_slash_stripped(self):
        client = NodesClient(base_url="https://api.io/")
        assert not client._base.endswith("/")

    def test_token_stored(self):
        client = NodesClient(base_url="https://api.io", token="abc")
        assert client._token == "abc"

    def test_timeout_stored(self):
        client = NodesClient(base_url="https://api.io", timeout=42.0)
        assert client._timeout == 42.0

    def test_headers_with_token(self):
        client = NodesClient(base_url="https://api.io", token="jwt")
        h = client._headers()
        assert h["Authorization"] == "Bearer jwt"
        assert h["Content-Type"] == "application/json"

    def test_headers_without_token(self):
        client = NodesClient(base_url="https://api.io", token=None)
        h = client._headers()
        assert "Authorization" not in h
        assert h["Content-Type"] == "application/json"
