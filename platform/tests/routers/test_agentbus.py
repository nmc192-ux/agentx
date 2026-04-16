"""
Tests: src/routers/agentbus.py
Phase 11 -- Agent Bus

Covers:
  POST /agentbus/send    -- send a direct message (requires auth)
  GET  /agentbus/inbox   -- list received messages (requires auth)
  GET  /agentbus/stream  -- SSE stream of incoming messages (requires auth)
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _now():
    return datetime.now(UTC)


# -- Model builders -----------------------------------------------------------

def _message(
    sender_did="did:agentx:sender",
    receiver_did="did:agentx:receiver",
    channel="default",
):
    from src.models.acp import ACPMessageResponse
    return ACPMessageResponse(
        protocol_version="ACP-1.0",
        message_id=uuid4(),
        timestamp=_now(),
        agent_id=sender_did,
        type="channel_message",
        human_summary="Hello, agent!",
        machine_payload={},
        metadata={},
        receiver_did=receiver_did,
        channel=channel,
    )


# -- Mock auth helper ---------------------------------------------------------

def _make_agent(did="did:agentx:caller-001"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did":       did,
        "display_name":    "Test Agent",
        "governance_role": "MEMBER",
        "tier":            "STANDARD",
        "status":          "ACTIVE",
        "trust_score":     0.8,
    }
    return AgentRecord(row=row, claims=mock_claims)


# -- POST /agentbus/send -------------------------------------------------------

class TestSendMessage:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        msg = _message()

        with patch(
            "src.routers.agentbus.agentbus_service.send_acp_message",
            new=AsyncMock(return_value=msg),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/agentbus/send",
                    json={
                        "agent_id": "did:agentx:sender",
                        "type": "channel_message",
                        "human_summary": "Hello, agent!",
                        "machine_payload": {},
                        "receiver_did": "did:agentx:receiver",
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == "did:agentx:sender"
        assert data["human_summary"] == "Hello, agent!"

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.post(
            "/agentbus/send",
            json={"receiver_did": "did:agentx:receiver", "content": "hi"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_receiver(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.send_acp_message",
            new=AsyncMock(side_effect=ValueError("Receiver agent not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/agentbus/send",
                    json={
                        "agent_id": "did:agentx:sender",
                        "type": "channel_message",
                        "human_summary": "hi",
                        "machine_payload": {},
                        "receiver_did": "did:agentx:ghost",
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_on_generic_error(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.send_acp_message",
            new=AsyncMock(side_effect=ValueError("invalid channel")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/agentbus/send",
                    json={
                        "agent_id": "did:agentx:sender",
                        "type": "channel_message",
                        "human_summary": "hi",
                        "machine_payload": {},
                        "receiver_did": "did:agentx:receiver",
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sends_with_custom_channel(self, client):
        from src.auth.middleware import get_current_agent
        msg = _message(channel="announcements")

        with patch(
            "src.routers.agentbus.agentbus_service.send_acp_message",
            new=AsyncMock(return_value=msg),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/agentbus/send",
                    json={
                        "agent_id": "did:agentx:sender",
                        "type": "channel_message",
                        "human_summary": "Announcement",
                        "machine_payload": {},
                        "receiver_did": "did:agentx:receiver",
                        "channel": "announcements",
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["channel"] == "announcements"

    @pytest.mark.asyncio
    async def test_sender_did_comes_from_auth_not_body(self, client):
        """The sender_did must be set from the authenticated agent, not request body."""
        from src.auth.middleware import get_current_agent
        msg = _message(sender_did="did:agentx:caller-001")

        with patch(
            "src.routers.agentbus.agentbus_service.send_acp_message",
            new=AsyncMock(return_value=msg),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent("did:agentx:caller-001")
            try:
                resp = await client.post(
                    "/agentbus/send",
                    json={
                        "agent_id": "did:agentx:caller-001",
                        "type": "channel_message",
                        "human_summary": "hi",
                        "machine_payload": {},
                        "receiver_did": "did:agentx:receiver",
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        # Verify the service was called with the authenticated agent's DID
        call_kwargs = mock_svc.call_args
        assert call_kwargs[1]["sender_did"] == "did:agentx:caller-001"


# -- GET /agentbus/inbox -------------------------------------------------------

class TestGetInbox:

    @pytest.mark.asyncio
    async def test_returns_200_with_messages(self, client):
        from src.auth.middleware import get_current_agent
        messages = [_message(), _message()]

        with patch(
            "src.routers.agentbus.agentbus_service.get_acp_inbox",
            new=AsyncMock(return_value=messages),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/inbox")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.get("/agentbus/inbox")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.get_acp_inbox",
            new=AsyncMock(return_value=[]),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/inbox")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_passes_limit_param(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.get_acp_inbox",
            new=AsyncMock(return_value=[]),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/inbox?limit=10")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        mock_svc.assert_awaited_once_with(
            agent_did="did:agentx:caller-001",
            limit=10,
            offset=0,
            acp_type=None,
            since=None,
        )

    @pytest.mark.asyncio
    async def test_passes_offset_param(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.get_acp_inbox",
            new=AsyncMock(return_value=[]),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/inbox?offset=25")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        mock_svc.assert_awaited_once_with(
            agent_did="did:agentx:caller-001",
            limit=50,
            offset=25,
            acp_type=None,
            since=None,
        )

    @pytest.mark.asyncio
    async def test_inbox_filtered_by_authenticated_did(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.agentbus.agentbus_service.get_acp_inbox",
            new=AsyncMock(return_value=[]),
        ) as mock_svc:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent("did:agentx:specific-agent")
            try:
                resp = await client.get("/agentbus/inbox")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        mock_svc.assert_awaited_once_with(
            agent_did="did:agentx:specific-agent",
            limit=50,
            offset=0,
            acp_type=None,
            since=None,
        )


# -- GET /agentbus/stream ------------------------------------------------------

class TestStreamMessages:

    @pytest.mark.asyncio
    async def test_returns_200_with_sse_content_type(self, client):
        from src.auth.middleware import get_current_agent

        async def _gen():
            yield "data: {}\n\n"

        with patch(
            "src.routers.agentbus.agentbus_service.stream_messages",
            return_value=_gen(),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/stream")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        resp = await client.get("/agentbus/stream")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_streams_sse_data_events(self, client):
        from src.auth.middleware import get_current_agent

        async def _gen():
            yield 'data: {"content": "hello"}\n\n'
            yield 'data: {"content": "world"}\n\n'

        with patch(
            "src.routers.agentbus.agentbus_service.stream_messages",
            return_value=_gen(),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/stream")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert "data:" in resp.text
        assert "hello" in resp.text

    @pytest.mark.asyncio
    async def test_stream_called_with_authenticated_did(self, client):
        from src.auth.middleware import get_current_agent

        async def _gen():
            yield "data: {}\n\n"

        with patch(
            "src.routers.agentbus.agentbus_service.stream_messages",
            return_value=_gen(),
        ) as mock_stream:
            app.dependency_overrides[get_current_agent] = lambda: _make_agent("did:agentx:streamer")
            try:
                await client.get("/agentbus/stream")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        mock_stream.assert_called_once_with("did:agentx:streamer")

    @pytest.mark.asyncio
    async def test_stream_no_cache_header(self, client):
        from src.auth.middleware import get_current_agent

        async def _gen():
            yield "data: {}\n\n"

        with patch(
            "src.routers.agentbus.agentbus_service.stream_messages",
            return_value=_gen(),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/stream")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.headers.get("cache-control") == "no-cache"

    @pytest.mark.asyncio
    async def test_stream_returns_keepalive_when_redis_unavailable(self, client):
        from src.auth.middleware import get_current_agent

        async def _keepalive_gen():
            yield ": keepalive\n\n"

        with patch(
            "src.routers.agentbus.agentbus_service.stream_messages",
            return_value=_keepalive_gen(),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.get("/agentbus/stream")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert "keepalive" in resp.text
