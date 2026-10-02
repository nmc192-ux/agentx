"""
Tests — POST /messages/send auth hardening
Auth fix: endpoint now requires get_current_agent and enforces
caller.did == body.sender_agent_did.

Sprint 9 (S9-6d) — direct messages are private:
  - GET /messages/{did} needs a login and returns the caller's own messages
    only (it took no login: anyone could read any agent's messages);
  - the MESSAGE_SENT event no longer carries the message text, and the two
    public readers of the events table (WS /events/stream,
    GET /dashboard/activity) leave that event type out.
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


ALICE = "did:agentx:alice-001"
BOB = "did:agentx:bob-001"


def _db(conn):
    ctx = MagicMock()
    ctx.return_value.__aenter__ = AsyncMock(return_value=conn)
    ctx.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestReadMessagesIsOwnOnly:

    @staticmethod
    async def _read(client, did, caller_did=None, headers=None):
        from src.auth.middleware import get_current_agent

        conn = AsyncMock()
        conn.fetchval.return_value = 1
        conn.fetch.return_value = [{
            "message_id": uuid4(), "sender_agent_did": did, "receiver_agent_did": BOB,
            "message": "the secret", "metadata": None,
            "created_at": __import__("datetime").datetime.utcnow(),
        }]
        cache_get = AsyncMock(return_value=None)
        if caller_did is not None:
            app.dependency_overrides[get_current_agent] = lambda: _make_caller(caller_did)
        try:
            with (
                patch("src.routers.messages.get_db", _db(conn)) as mock_db,
                patch("src.routers.messages.cache_get", new=cache_get),
                patch("src.routers.messages.cache_set", new=AsyncMock()),
            ):
                resp = await client.get(f"/messages/{did}", headers=headers)
        finally:
            app.dependency_overrides.pop(get_current_agent, None)
        return resp, mock_db, cache_get

    async def test_no_token_is_401_and_reads_nothing(self, client):
        resp, mock_db, cache_get = await self._read(client, ALICE)
        assert resp.status_code == 401
        assert "the secret" not in resp.text
        mock_db.assert_not_called()
        cache_get.assert_not_awaited()      # a cached inbox must not leak either

    async def test_bad_token_is_401_and_reads_nothing(self, client):
        resp, mock_db, cache_get = await self._read(
            client, ALICE, headers={"Authorization": "Bearer nope"},
        )
        assert resp.status_code == 401
        mock_db.assert_not_called()
        cache_get.assert_not_awaited()

    async def test_another_agents_inbox_is_403_and_reads_nothing(self, client):
        resp, mock_db, cache_get = await self._read(client, ALICE, caller_did=BOB)
        assert resp.status_code == 403
        assert "the secret" not in resp.text
        mock_db.assert_not_called()
        cache_get.assert_not_awaited()

    async def test_own_inbox_is_200(self, client):
        resp, _, _ = await self._read(client, ALICE, caller_did=ALICE)
        assert resp.status_code == 200
        assert resp.json()[0]["message"] == "the secret"


class TestMessageTextStaysOutOfPublicEvents:

    async def test_message_sent_event_has_no_message_text(self, client):
        from src.auth.middleware import get_current_agent

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {"agent_id": uuid4()},
            {"agent_id": uuid4()},
            {
                "message_id": uuid4(), "sender_agent_did": ALICE, "receiver_agent_did": BOB,
                "message": "the secret", "metadata": None,
                "created_at": __import__("datetime").datetime.utcnow(),
            },
        ]
        emit = AsyncMock()
        app.dependency_overrides[get_current_agent] = lambda: _make_caller(ALICE)
        try:
            with (
                patch("src.routers.messages.transaction", _db(conn)),
                patch("src.routers.messages.emit_event", new=emit),
                patch("src.routers.messages.record_event", new=AsyncMock()),
                patch("src.routers.messages.blocks_service.has_blocked",
                      new=AsyncMock(return_value=False)),
                patch("src.routers.messages.cache_delete", new=AsyncMock()),
            ):
                resp = await client.post("/messages/send", json={
                    "sender_agent_did": ALICE, "receiver_agent_did": BOB, "message": "the secret",
                })
        finally:
            app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        event_type, _, payload = emit.await_args.args
        assert event_type == "MESSAGE_SENT"
        assert "message" not in payload
        assert "the secret" not in str(payload)

    async def test_private_events_are_not_broadcast_to_the_public_stream(self):
        from src.services import events

        socket = AsyncMock()
        events._connections.add(socket)
        try:
            await events._broadcast({"event_type": "MESSAGE_SENT", "payload": {}})
            socket.send_json.assert_not_awaited()
            await events._broadcast({"event_type": "POST_CREATED", "payload": {}})
            socket.send_json.assert_awaited_once()
        finally:
            events._connections.discard(socket)

    async def test_dashboard_activity_leaves_private_events_out(self, client):
        conn = AsyncMock()
        conn.fetch.return_value = []
        with patch("src.routers.dashboard.get_db", _db(conn)):
            resp = await client.get("/dashboard/activity")

        assert resp.status_code == 200
        sql, excluded = conn.fetch.await_args.args
        assert "event_type <> ALL($1::text[])" in sql
        assert "MESSAGE_SENT" in excluded

    def test_event_stream_query_leaves_private_events_out(self):
        import inspect
        from src.routers import events as events_router

        source = inspect.getsource(events_router.stream_events)
        assert "event_type <> ALL($2::text[])" in source
        assert "list(PRIVATE_EVENT_TYPES)" in source
