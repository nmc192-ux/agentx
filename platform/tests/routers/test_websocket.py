"""
Tests — WebSocket Endpoint (Sprint 5)
══════════════════════════════════════
Verifies:
  WS /ws?token=...   — authenticated stream, subscribe/unsubscribe, ping, error
  GET /ws/stats      — connection statistics

Uses pytest-anyio / anyio because httpx.AsyncClient doesn't support WebSocket;
we test the WebSocket manager directly + the stats endpoint via HTTP.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.auth.jwt import create_access_token
from src.websocket.manager import ConnectionManager, MessageType


# ── Fixtures ──────────────────────────────────────────────────────────────────

AGENT_DID = "did:agentx:nova-001"
TOKEN     = create_access_token(AGENT_DID, role="MEMBER", tier="STANDARD")


# ── ConnectionManager unit tests ──────────────────────────────────────────────

class TestConnectionManager:
    """Unit tests for ConnectionManager — no real WebSocket needed."""

    def _make_ws(self) -> MagicMock:
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        ws.accept    = AsyncMock()
        ws.close     = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_registers_agent(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)

        assert AGENT_DID in mgr._agent_connections
        assert ws in mgr._agent_connections[AGENT_DID]
        assert ws in mgr._ws_to_agent

    @pytest.mark.asyncio
    async def test_connect_sends_connected_message(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)

        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == MessageType.CONNECTED
        assert call_args["agent_did"] == AGENT_DID

    @pytest.mark.asyncio
    async def test_disconnect_removes_agent(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)
        await mgr.disconnect(ws, AGENT_DID)

        assert AGENT_DID not in mgr._agent_connections
        assert ws not in mgr._ws_to_agent

    @pytest.mark.asyncio
    async def test_disconnect_without_agent_did_uses_reverse_map(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)
        await mgr.disconnect(ws)  # no agent_did supplied

        assert AGENT_DID not in mgr._agent_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_agent_sends_message(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)
        ws.send_json.reset_mock()   # clear CONNECTED message

        count = await mgr.broadcast_to_agent(AGENT_DID, {"type": "NEW_POST"})

        assert count == 1
        ws.send_json.assert_called_once_with({"type": "NEW_POST"})

    @pytest.mark.asyncio
    async def test_broadcast_to_agent_returns_zero_for_offline_agent(self):
        mgr = ConnectionManager()
        count = await mgr.broadcast_to_agent("did:agentx:ghost-999", {"type": "NEW_POST"})
        assert count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_collective_reaches_subscribed_agents(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()
        cid = uuid4()

        await mgr.connect(ws, AGENT_DID, collective_ids=[cid])
        ws.send_json.reset_mock()

        count = await mgr.broadcast_to_collective(cid, {"type": "PROPOSAL_CREATED"})
        assert count == 1

    @pytest.mark.asyncio
    async def test_broadcast_to_collective_zero_for_no_subs(self):
        mgr   = ConnectionManager()
        count = await mgr.broadcast_to_collective(uuid4(), {"type": "PROPOSAL_CREATED"})
        assert count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_channel_reaches_subscribed_agents(self):
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID, channels=["feed"])
        ws.send_json.reset_mock()

        count = await mgr.broadcast_to_channel("feed", {"type": "NEW_POST"})
        assert count == 1

    @pytest.mark.asyncio
    async def test_broadcast_global_reaches_all_agents(self):
        mgr  = ConnectionManager()
        ws1  = self._make_ws()
        ws2  = self._make_ws()
        did2 = "did:agentx:atlas-001"

        await mgr.connect(ws1, AGENT_DID)
        await mgr.connect(ws2, did2)
        ws1.send_json.reset_mock()
        ws2.send_json.reset_mock()

        count = await mgr.broadcast_global({"type": "TRUST_UPDATE"})
        assert count == 2

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe_collective(self):
        mgr = ConnectionManager()
        cid = uuid4()

        mgr.subscribe_collective(AGENT_DID, cid)
        assert AGENT_DID in mgr._collective_subs[cid]

        mgr.unsubscribe_collective(AGENT_DID, cid)
        assert AGENT_DID not in mgr._collective_subs.get(cid, set())

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe_channel(self):
        mgr = ConnectionManager()

        mgr.subscribe_channel(AGENT_DID, "governance")
        assert AGENT_DID in mgr._channel_subs["governance"]

        mgr.unsubscribe_channel(AGENT_DID, "governance")
        assert AGENT_DID not in mgr._channel_subs.get("governance", set())

    def test_stats_returns_correct_shape(self):
        mgr = ConnectionManager()
        s   = mgr.stats()
        assert "agents_online"       in s
        assert "total_connections"   in s
        assert "collective_channels" in s
        assert "named_channels"      in s

    @pytest.mark.asyncio
    async def test_max_one_connection_per_did_evicts_old(self):
        """A new connection for the same DID closes the previous one (max-1 policy)."""
        mgr = ConnectionManager()
        ws1 = self._make_ws()
        ws2 = self._make_ws()

        await mgr.connect(ws1, AGENT_DID)
        await mgr.connect(ws2, AGENT_DID)

        # ws1 should have been evicted; only ws2 remains
        assert len(mgr._agent_connections[AGENT_DID]) == 1
        assert ws2 in mgr._agent_connections[AGENT_DID]
        assert ws1 not in mgr._agent_connections.get(AGENT_DID, [])
        # ws1.close was called with supersede code
        ws1.close.assert_called_once_with(code=4008, reason="Superseded by new connection")

    @pytest.mark.asyncio
    async def test_expired_token_stored_on_connect(self):
        """token_exp is persisted in _conn_token_exp when provided."""
        import time
        mgr = ConnectionManager()
        ws  = self._make_ws()
        exp = time.time() + 900  # 15 min from now

        await mgr.connect(ws, AGENT_DID, token_exp=exp)

        assert mgr._conn_token_exp[ws] == exp

    @pytest.mark.asyncio
    async def test_token_exp_cleared_on_disconnect(self):
        """_conn_token_exp entry is removed when the socket disconnects."""
        import time
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID, token_exp=time.time() + 900)
        await mgr.disconnect(ws, AGENT_DID)

        assert ws not in mgr._conn_token_exp

    @pytest.mark.asyncio
    async def test_failed_send_disconnects_socket(self):
        """If send_json raises, the socket is removed."""
        mgr = ConnectionManager()
        ws  = self._make_ws()

        await mgr.connect(ws, AGENT_DID)
        ws.send_json.side_effect = RuntimeError("connection closed")

        count = await mgr.broadcast_to_agent(AGENT_DID, {"type": "NEW_POST"})
        assert count == 0
        assert AGENT_DID not in mgr._agent_connections


# ── HTTP stats endpoint ────────────────────────────────────────────────────────

class TestWsStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_returns_200(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ws/stats")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_shape(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ws/stats")
        data = resp.json()
        assert "agents_online"     in data
        assert "total_connections" in data


# ── JWT auth helper ────────────────────────────────────────────────────────────

class TestWsAuthHelper:
    @pytest.mark.asyncio
    async def test_valid_token_returns_agent_did_and_exp(self):
        from src.routers.ws import _authenticate_ws
        did, exp = await _authenticate_ws(TOKEN)
        assert did == AGENT_DID
        assert exp is not None and exp > 0

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none_tuple(self):
        from src.routers.ws import _authenticate_ws
        did, exp = await _authenticate_ws("not.a.valid.token")
        assert did is None
        assert exp is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none_tuple(self):
        from src.routers.ws import _authenticate_ws
        did, exp = await _authenticate_ws("")
        assert did is None
        assert exp is None
