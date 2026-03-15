"""
Tests: src/services/node_service.py + src/services/consumers/node_consumer.py
          + src/services/node_peer_client.py
Phase 17 — Federated AgentX Nodes
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.models.node import NodeMessageResponse, NodeResponse
from src.services import node_service

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)
_NODE_ID = uuid4()
_MSG_ID  = uuid4()


def _node_data(
    node_id: UUID | None = None,
    url: str = "https://peer.agentx.io",
    name: str | None = "PeerNode",
    status: str = "active",
    trust: float = 0.5,
) -> dict:
    return {
        "node_id":       node_id or _NODE_ID,
        "node_url":      url,
        "node_name":     name,
        "public_key":    None,
        "status":        status,
        "trust_level":   trust,
        "registered_at": NOW,
        "last_seen_at":  None,
    }


def _msg_data(
    msg_id: UUID | None = None,
    node_id: UUID | None = None,
    event_type: str = "CONTRACT_COMPLETED",
    payload: dict | None = None,
    direction: str = "inbound",
) -> dict:
    return {
        "message_id": msg_id or _MSG_ID,
        "node_id":    node_id,
        "event_type": event_type,
        "payload":    payload or {},
        "direction":  direction,
        "created_at": NOW,
    }


def _make_row(data: dict) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _fake_db(conn):
    """Context manager that returns *conn* on __aenter__."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__  = AsyncMock(return_value=False)
    return cm


# ─────────────────────────────────────────────────────────────────────────────
# _row_to_node
# ─────────────────────────────────────────────────────────────────────────────

class TestRowToNode:

    def test_basic_fields(self):
        data = _node_data()
        row  = _make_row(data)
        result = node_service._row_to_node(row)
        assert result.node_id  == data["node_id"]
        assert result.node_url == data["node_url"]
        assert result.status   == "active"
        assert result.trust_level == 0.5

    def test_optional_name_none(self):
        data = _node_data(name=None)
        row  = _make_row(data)
        assert node_service._row_to_node(row).node_name is None

    def test_optional_public_key(self):
        data = _node_data()
        row  = _make_row(data)
        assert node_service._row_to_node(row).public_key is None

    def test_trust_level_cast_to_float(self):
        data = _node_data(trust=1)   # int from DB
        row  = _make_row(data)
        result = node_service._row_to_node(row)
        assert isinstance(result.trust_level, float)

    def test_inactive_status(self):
        data = _node_data(status="inactive")
        row  = _make_row(data)
        assert node_service._row_to_node(row).status == "inactive"


# ─────────────────────────────────────────────────────────────────────────────
# _row_to_message
# ─────────────────────────────────────────────────────────────────────────────

class TestRowToMessage:

    def test_basic_fields(self):
        data = _msg_data()
        row  = _make_row(data)
        result = node_service._row_to_message(row)
        assert result.message_id == data["message_id"]
        assert result.event_type == "CONTRACT_COMPLETED"
        assert result.direction  == "inbound"

    def test_payload_dict_passthrough(self):
        data = _msg_data(payload={"x": 1})
        row  = _make_row(data)
        assert node_service._row_to_message(row).payload == {"x": 1}

    def test_payload_json_string_decoded(self):
        data = _msg_data()
        data["payload"] = '{"y": 2}'
        row  = _make_row(data)
        assert node_service._row_to_message(row).payload == {"y": 2}

    def test_payload_none_becomes_empty_dict(self):
        data = _msg_data()
        data["payload"] = None
        row  = _make_row(data)
        assert node_service._row_to_message(row).payload == {}

    def test_node_id_none(self):
        data = _msg_data(node_id=None)
        row  = _make_row(data)
        assert node_service._row_to_message(row).node_id is None


# ─────────────────────────────────────────────────────────────────────────────
# register_node
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterNode:

    @pytest.mark.asyncio
    async def test_returns_node_response(self):
        data = _node_data()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.register_node("https://peer.agentx.io", "PeerNode")
        assert isinstance(result, NodeResponse)
        assert result.node_url == "https://peer.agentx.io"

    @pytest.mark.asyncio
    async def test_passes_all_args_to_db(self):
        data = _node_data()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.register_node("https://p.io", "P", "pk123")
        args = conn.fetchrow.call_args[0]
        assert "https://p.io" in args
        assert "P" in args
        assert "pk123" in args

    @pytest.mark.asyncio
    async def test_none_name_accepted(self):
        data = _node_data(name=None)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.register_node("https://p.io")
        assert result.node_name is None

    @pytest.mark.asyncio
    async def test_upsert_query_contains_on_conflict(self):
        """Verify the SQL uses ON CONFLICT (node_url)."""
        data = _node_data()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.register_node("https://p.io")
        sql = conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql


# ─────────────────────────────────────────────────────────────────────────────
# list_nodes
# ─────────────────────────────────────────────────────────────────────────────

class TestListNodes:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        rows = [_make_row(_node_data(url=f"https://peer{i}.io")) for i in range(3)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.list_nodes()
        assert len(result) == 3
        assert all(isinstance(r, NodeResponse) for r in result)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.list_nodes()
        assert result == []

    @pytest.mark.asyncio
    async def test_active_only_filter_in_query(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.list_nodes(active_only=True)
        sql = conn.fetch.call_args[0][0]
        assert "active" in sql.lower()

    @pytest.mark.asyncio
    async def test_no_filter_query_has_no_where(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.list_nodes(active_only=False)
        sql = conn.fetch.call_args[0][0]
        assert "WHERE" not in sql


# ─────────────────────────────────────────────────────────────────────────────
# get_node
# ─────────────────────────────────────────────────────────────────────────────

class TestGetNode:

    @pytest.mark.asyncio
    async def test_found(self):
        data = _node_data()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.get_node(data["node_id"])
        assert result.node_id == data["node_id"]

    @pytest.mark.asyncio
    async def test_not_found_raises_value_error(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            with pytest.raises(ValueError, match="not found"):
                await node_service.get_node(uuid4())

    @pytest.mark.asyncio
    async def test_passes_node_id_to_query(self):
        nid = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(_node_data(node_id=nid)))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.get_node(nid)
        assert nid in conn.fetchrow.call_args[0]


# ─────────────────────────────────────────────────────────────────────────────
# send_node_message
# ─────────────────────────────────────────────────────────────────────────────

class TestSendNodeMessage:

    @pytest.mark.asyncio
    async def test_returns_message_response(self):
        data = _msg_data()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.send_node_message(
                node_id=_NODE_ID,
                event_type="CONTRACT_COMPLETED",
                payload={"key": "val"},
                direction="outbound",
            )
        assert isinstance(result, NodeMessageResponse)

    @pytest.mark.asyncio
    async def test_inbound_direction(self):
        data = _msg_data(direction="inbound")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.send_node_message(
                node_id=None, event_type="TASK_COMPLETED", payload={}, direction="inbound"
            )
        assert result.direction == "inbound"

    @pytest.mark.asyncio
    async def test_null_node_id_accepted(self):
        data = _msg_data(node_id=None)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.send_node_message(
                node_id=None, event_type="X", payload={}, direction="inbound"
            )
        assert result.node_id is None

    @pytest.mark.asyncio
    async def test_payload_serialised_as_json(self):
        data = _msg_data(payload={"a": 1})
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            await node_service.send_node_message(
                node_id=None, event_type="X", payload={"a": 1}, direction="inbound"
            )
        # Verify json.dumps was called — the third positional arg should be a JSON string
        args = conn.fetchrow.call_args[0]
        json_arg = args[3]  # $3 in query = json.dumps(payload)
        assert json_arg == '{"a": 1}'


# ─────────────────────────────────────────────────────────────────────────────
# update_node_status
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateNodeStatus:

    @pytest.mark.asyncio
    async def test_valid_status_active(self):
        data = _node_data(status="active")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.update_node_status(_NODE_ID, "active")
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_valid_status_inactive(self):
        data = _node_data(status="inactive")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.update_node_status(_NODE_ID, "inactive")
        assert result.status == "inactive"

    @pytest.mark.asyncio
    async def test_valid_status_banned(self):
        data = _node_data(status="banned")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_make_row(data))
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            result = await node_service.update_node_status(_NODE_ID, "banned")
        assert result.status == "banned"

    @pytest.mark.asyncio
    async def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            await node_service.update_node_status(_NODE_ID, "unknown")

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("src.services.node_service.get_db", return_value=_fake_db(conn)):
            with pytest.raises(ValueError, match="not found"):
                await node_service.update_node_status(uuid4(), "active")


# ─────────────────────────────────────────────────────────────────────────────
# node_peer_client.post_event
# ─────────────────────────────────────────────────────────────────────────────

class TestNodePeerClient:

    @pytest.mark.asyncio
    async def test_returns_true_on_2xx(self):
        from src.services.node_peer_client import post_event
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.text = ""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            result = await post_event("https://peer.io", "CONTRACT_COMPLETED", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_4xx(self):
        from src.services.node_peer_client import post_event
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            result = await post_event("https://peer.io", "X", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(self):
        from src.services.node_peer_client import post_event
        import httpx
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            result = await post_event("https://peer.io", "X", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        from src.services.node_peer_client import post_event
        import httpx
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            result = await post_event("https://peer.io", "X", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_url(self):
        from src.services.node_peer_client import post_event
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            await post_event("https://peer.io/", "X", {})
        called_url = mock_client.post.call_args[0][0]
        assert called_url == "https://peer.io/nodes/events"

    @pytest.mark.asyncio
    async def test_source_node_url_included_in_body(self):
        from src.services.node_peer_client import post_event
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        with patch("src.services.node_peer_client.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            await post_event("https://peer.io", "X", {}, source_node_url="https://me.io")
        kwargs = mock_client.post.call_args[1]
        assert kwargs["json"]["source_node_url"] == "https://me.io"


# ─────────────────────────────────────────────────────────────────────────────
# node_consumer
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeConsumer:

    def _make_event(self, event_type_str: str, payload: dict | None = None):
        from src.events.types import AgentXEvent, EventType
        return AgentXEvent(
            event_type=EventType(event_type_str),
            payload=payload or {},
        )

    @pytest.mark.asyncio
    async def test_broadcasts_contract_completed(self):
        from src.services.consumers import node_consumer
        node = NodeResponse(
            node_id=_NODE_ID,
            node_url="https://peer.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        event = self._make_event("CONTRACT_COMPLETED", {"contract_id": "c1"})
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[node])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=True)) as pe:
                with patch.object(node_service, "send_node_message", AsyncMock(return_value=MagicMock())):
                    await node_consumer.handle(event)
        pe.assert_called_once()
        assert pe.call_args[1]["event_type"] == "CONTRACT_COMPLETED"

    @pytest.mark.asyncio
    async def test_broadcasts_task_completed(self):
        from src.services.consumers import node_consumer
        node = NodeResponse(
            node_id=_NODE_ID,
            node_url="https://peer.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        event = self._make_event("TASK_COMPLETED", {"agent_id": str(uuid4())})
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[node])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=True)) as pe:
                with patch.object(node_service, "send_node_message", AsyncMock(return_value=MagicMock())):
                    await node_consumer.handle(event)
        pe.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcasts_bounty_reward_distributed(self):
        from src.services.consumers import node_consumer
        node = NodeResponse(
            node_id=_NODE_ID,
            node_url="https://peer.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        event = self._make_event("BOUNTY_REWARD_DISTRIBUTED", {"recipient_id": str(uuid4())})
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[node])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=True)) as pe:
                with patch.object(node_service, "send_node_message", AsyncMock(return_value=MagicMock())):
                    await node_consumer.handle(event)
        pe.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_broadcast_event_skipped(self):
        from src.services.consumers import node_consumer
        event = self._make_event("TOKEN_TRANSFER")
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[])) as ln:
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock()) as pe:
                await node_consumer.handle(event)
        ln.assert_not_called()
        pe.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_peer_nodes_no_http_calls(self):
        from src.services.consumers import node_consumer
        event = self._make_event("CONTRACT_COMPLETED")
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock()) as pe:
                await node_consumer.handle(event)
        pe.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_post_does_not_log_message(self):
        from src.services.consumers import node_consumer
        node = NodeResponse(
            node_id=_NODE_ID,
            node_url="https://peer.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        event = self._make_event("CONTRACT_COMPLETED")
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[node])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=False)):
                with patch.object(node_service, "send_node_message", AsyncMock()) as sm:
                    await node_consumer.handle(event)
        sm.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_peers_all_called(self):
        from src.services.consumers import node_consumer
        peers = [
            NodeResponse(node_id=uuid4(), node_url=f"https://peer{i}.io",
                         status="active", trust_level=0.5, registered_at=NOW)
            for i in range(3)
        ]
        event = self._make_event("TASK_COMPLETED")
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=peers)):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=True)) as pe:
                with patch.object(node_service, "send_node_message", AsyncMock(return_value=MagicMock())):
                    await node_consumer.handle(event)
        assert pe.call_count == 3

    @pytest.mark.asyncio
    async def test_handle_swallows_exceptions(self):
        """handle() must not propagate exceptions — consumer loop safety."""
        from src.services.consumers import node_consumer
        event = self._make_event("CONTRACT_COMPLETED")
        with patch.object(node_service, "list_nodes", AsyncMock(side_effect=RuntimeError("db down"))):
            # Should not raise
            await node_consumer.handle(event)

    @pytest.mark.asyncio
    async def test_outbound_message_logged_on_success(self):
        from src.services.consumers import node_consumer
        node = NodeResponse(
            node_id=_NODE_ID,
            node_url="https://peer.io",
            status="active",
            trust_level=0.5,
            registered_at=NOW,
        )
        event = self._make_event("TASK_COMPLETED", {"agent_id": "abc"})
        with patch.object(node_service, "list_nodes", AsyncMock(return_value=[node])):
            with patch("src.services.consumers.node_consumer.post_event", AsyncMock(return_value=True)):
                with patch.object(node_service, "send_node_message", AsyncMock(return_value=MagicMock())) as sm:
                    await node_consumer.handle(event)
        sm.assert_called_once()
        _, kwargs = sm.call_args
        assert kwargs["direction"] == "outbound"
        assert kwargs["node_id"]   == _NODE_ID
