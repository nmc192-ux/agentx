"""
Tests — POST /messages/send auth hardening
Auth fix: endpoint now requires get_current_agent and enforces
caller.did == body.sender_agent_did.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from src.main import app


def _make_caller(did="did:agentx:alice-001"):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={
            "agent_did": did, "display_name": "Alice", "governance_role": "MEMBER",
            "tier": "STANDARD", "status": "ACTIVE", "trust_score": 0.5,
        },
        claims=claims,
    )


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


class TestSendMessageAuth:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        """No Bearer token → 401 before any DB access."""
        response = await client.post("/messages/send", json={
            "sender_agent_did":   "did:agentx:alice-001",
            "receiver_agent_did": "did:agentx:bob-001",
            "message":            "Hello Bob",
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_sender_mismatch_returns_403(self, client):
        """Authenticated as Alice but claiming to send as Charlie → 403."""
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: _make_caller("did:agentx:alice-001")
        try:
            response = await client.post("/messages/send", json={
                "sender_agent_did":   "did:agentx:charlie-001",  # not alice!
                "receiver_agent_did": "did:agentx:bob-001",
                "message":            "Impersonation attempt",
            })
        finally:
            app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_authenticated_matching_sender_allowed(self, client):
        """Correct auth + matching sender DID proceeds to DB layer."""
        from src.auth.middleware import get_current_agent
        sender_did   = "did:agentx:alice-001"
        receiver_did = "did:agentx:bob-001"

        with (
            patch("src.routers.messages.transaction") as mock_tx,
            patch("src.routers.messages.emit_event", new=AsyncMock()),
            patch("src.routers.messages.record_event", new=AsyncMock()),
            patch("src.routers.messages.blocks_service.has_blocked",
                  new=AsyncMock(return_value=False)),
            patch("src.routers.messages.cache_delete", new=AsyncMock()),
            patch("src.routers.messages.cache_set",    new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.side_effect = [
                {"agent_id": uuid4()},   # sender_row
                {"agent_id": uuid4()},   # receiver_row
                {                        # INSERT result
                    "message_id":        uuid4(),
                    "sender_agent_did":  sender_did,
                    "receiver_agent_did": receiver_did,
                    "message":           "Hello Bob",
                    "metadata":          None,
                    "created_at":        __import__("datetime").datetime.utcnow(),
                },
            ]
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: _make_caller(sender_did)
            response = await client.post("/messages/send", json={
                "sender_agent_did":   sender_did,
                "receiver_agent_did": receiver_did,
                "message":            "Hello Bob",
            })
        app.dependency_overrides = {}
        assert response.status_code == 201
