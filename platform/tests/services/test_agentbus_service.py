"""
Tests: src/services/agentbus_service.py + workers/executor.execute_agentbus_message
Phase 11 -- Agent Bus  (updated for ACP-1.0 rename)

Covers:
  send_acp_message()          -- resolves DIDs, inserts message, publishes event + Redis
  get_acp_inbox()             -- queries messages by receiver_did with pagination
  stream_messages()           -- Redis pub/sub SSE generator
  execute_agentbus_message()  -- worker function, publishes AGENT_MESSAGE_RECEIVED
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Stub opentelemetry so workers/executor.py can be imported without the
# real SDK installed.  Must be done before any import of workers.executor.
# ---------------------------------------------------------------------------
def _make_otel_stubs() -> None:
    if "opentelemetry" not in sys.modules:
        sys.modules["opentelemetry"] = types.ModuleType("opentelemetry")

    if "opentelemetry.trace" not in sys.modules:
        _mod = types.ModuleType("opentelemetry.trace")

        class _SpanKind:
            INTERNAL = "INTERNAL"
            CONSUMER = "CONSUMER"
            PRODUCER = "PRODUCER"
            CLIENT   = "CLIENT"
            SERVER   = "SERVER"

        class _StatusCode:
            OK = "OK"
            ERROR = "ERROR"

        class _Span:
            def set_attribute(self, *a, **kw): pass
            def set_status(self, *a, **kw): pass
            def record_exception(self, *a, **kw): pass

        class _Tracer:
            @contextmanager
            def start_as_current_span(self, *args, **kwargs):
                yield _Span()

        _mod.SpanKind = _SpanKind
        _mod.StatusCode = _StatusCode
        _mod.get_tracer = lambda *a, **kw: _Tracer()
        sys.modules["opentelemetry.trace"] = _mod

    # Make opentelemetry.trace accessible as an attribute of the top-level module
    otel = sys.modules["opentelemetry"]
    otel.trace = sys.modules["opentelemetry.trace"]  # type: ignore[attr-defined]


_make_otel_stubs()

# Now safe to import the ACP models
from src.models.acp import ACPMessageCreate, ACPMessageResponse
from src.services import agentbus_service


# -- Helpers ------------------------------------------------------------------

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _agent_row(agent_id=None):
    return {"agent_id": agent_id or uuid4()}


def _message_row(
    message_id=None,
    sender_did="did:agentx:sender",
    receiver_did="did:agentx:receiver",
    channel="default",
    status="sent",
):
    """Build a DB-row dict that _row_to_acp() can process."""
    mid = message_id or uuid4()
    return {
        # Legacy columns
        "message_id":       mid,
        "sender_did":       sender_did,
        "receiver_did":     receiver_did,
        "content":          "Hello, agent!",
        "channel":          channel,
        "status":           status,
        "metadata":         None,
        "created_at":       _now(),
        # ACP-1.0 columns
        "acp_message_id":   mid,
        "agent_id":         sender_did,   # ACP agent_id == sender DID
        "acp_type":         "channel_message",
        "human_summary":    "Hello, agent!",
        "machine_payload":  None,
        "acp_timestamp":    None,
        "protocol_version": "ACP-1.0",
    }


def _acp_create(
    sender_did: str = "did:agentx:sender",
    receiver_did: str = "did:agentx:receiver",
    summary: str = "Hello, agent!",
    channel: str = "default",
    metadata=None,
) -> ACPMessageCreate:
    """Convenience factory for ACPMessageCreate with sensible defaults."""
    return ACPMessageCreate(
        agent_id=sender_did,
        type="channel_message",
        human_summary=summary,
        machine_payload={},
        receiver_did=receiver_did,
        channel=channel,
        metadata=metadata or {},
    )


# -- send_acp_message ---------------------------------------------------------

class TestSendMessage:

    @pytest.mark.asyncio
    async def test_sends_message_successfully(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(),
            )

        assert result.agent_id == "did:agentx:sender"
        assert result.receiver_did == "did:agentx:receiver"
        assert result.human_summary == "Hello, agent!"

    @pytest.mark.asyncio
    async def test_raises_if_receiver_not_found(self):
        sender_row = _agent_row()

        conn = AsyncMock()
        # sender lookup succeeds; receiver lookup returns None
        conn.fetchrow = AsyncMock(side_effect=[sender_row, None])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(receiver_did="did:agentx:ghost"),
            )

    @pytest.mark.asyncio
    async def test_publish_event_failure_does_not_raise(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch(
                "src.services.agentbus_service.publish_event",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(summary="hi"),
            )

        assert result.message_id is not None

    @pytest.mark.asyncio
    async def test_redis_publish_failure_does_not_raise(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=Exception("connection refused"))

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=mock_redis),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(summary="hi"),
            )

        assert result.message_id is not None

    @pytest.mark.asyncio
    async def test_sends_to_named_channel(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row(channel="announcements")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(summary="Announcement", channel="announcements"),
            )

        assert result.channel == "announcements"

    @pytest.mark.asyncio
    async def test_sends_with_metadata(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row()
        row["metadata"] = '{"priority": "high"}'

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(summary="Urgent", metadata={"priority": "high"}),
            )

        assert result.metadata == {"priority": "high"}

    @pytest.mark.asyncio
    async def test_unknown_sender_did_still_sends(self):
        """If sender DID isn't in agents table, sender_id=NULL but message persists."""
        receiver_row = _agent_row()
        row          = _message_row()

        conn = AsyncMock()
        # sender lookup returns None; receiver lookup succeeds
        conn.fetchrow = AsyncMock(side_effect=[None, receiver_row, row])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(
                "did:agentx:unknown-sender",
                _acp_create(
                    sender_did="did:agentx:unknown-sender",
                    summary="hi",
                ),
            )

        assert result.message_id is not None

    @pytest.mark.asyncio
    async def test_publishes_to_redis_channel_with_correct_key(self):
        sender_row   = _agent_row()
        receiver_row = _agent_row()
        row          = _message_row(receiver_did="did:agentx:bob")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[sender_row, receiver_row, row])

        mock_redis = AsyncMock()

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.agentbus_service.publish_event", new=AsyncMock()),
            patch("src.services.agentbus_service.get_cache", return_value=mock_redis),
        ):
            await agentbus_service.send_acp_message(
                "did:agentx:sender",
                _acp_create(receiver_did="did:agentx:bob", summary="ping"),
            )

        # Should publish to agentbus:did:agentx:bob
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "agentbus:did:agentx:bob"


# -- get_acp_inbox ------------------------------------------------------------

class TestGetInbox:

    @pytest.mark.asyncio
    async def test_returns_messages_for_receiver(self):
        rows = [_message_row(), _message_row(), _message_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            result = await agentbus_service.get_acp_inbox("did:agentx:receiver")

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_inbox(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            result = await agentbus_service.get_acp_inbox("did:agentx:nobody")

        assert result == []

    @pytest.mark.asyncio
    async def test_default_limit_is_50(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            await agentbus_service.get_acp_inbox("did:agentx:agent")

        # Verify fetch was called with limit=50 and offset=0
        call_args = conn.fetch.call_args
        assert 50 in call_args[0] or 50 in list(call_args[1].values())

    @pytest.mark.asyncio
    async def test_custom_limit_and_offset(self):
        rows = [_message_row(), _message_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            result = await agentbus_service.get_acp_inbox(
                "did:agentx:agent", limit=10, offset=20
            )

        assert len(result) == 2
        call_args = conn.fetch.call_args
        positional = call_args[0]
        assert 10 in positional and 20 in positional

    @pytest.mark.asyncio
    async def test_returns_correct_fields(self):
        row = _message_row(sender_did="did:agentx:alice", receiver_did="did:agentx:bob")
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            result = await agentbus_service.get_acp_inbox("did:agentx:bob")

        # ACPMessageResponse uses agent_id (DID of sender) and human_summary
        assert result[0].agent_id == "did:agentx:alice"
        assert result[0].receiver_did == "did:agentx:bob"
        assert result[0].human_summary == "Hello, agent!"

    @pytest.mark.asyncio
    async def test_decodes_json_metadata(self):
        row = _message_row()
        row["metadata"] = '{"key": "value"}'
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        with patch("src.services.agentbus_service.get_db", return_value=_tx_context(conn)):
            result = await agentbus_service.get_acp_inbox("did:agentx:receiver")

        assert result[0].metadata == {"key": "value"}


# -- stream_messages ----------------------------------------------------------

class TestStreamMessages:

    @pytest.mark.asyncio
    async def test_yields_keepalive_when_redis_unavailable(self):
        with patch("src.services.agentbus_service.get_cache", return_value=None):
            results = []
            async for chunk in agentbus_service.stream_messages("did:agentx:agent"):
                results.append(chunk)

        assert len(results) == 1
        assert "keepalive" in results[0]

    @pytest.mark.asyncio
    async def test_subscribes_to_correct_channel(self):
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe   = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose      = AsyncMock()

        async def _empty_listen():
            return
            yield  # make it a generator

        mock_pubsub.listen = _empty_listen

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("src.services.agentbus_service.get_cache", return_value=mock_redis):
            async for _ in agentbus_service.stream_messages("did:agentx:bob"):
                pass

        mock_pubsub.subscribe.assert_called_once_with("agentbus:did:agentx:bob")

    @pytest.mark.asyncio
    async def test_yields_sse_data_for_messages(self):
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe   = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose      = AsyncMock()

        async def _listen():
            yield {"type": "message", "data": '{"content": "hello"}'}
            yield {"type": "subscribe", "data": None}  # should be ignored

        mock_pubsub.listen = _listen

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("src.services.agentbus_service.get_cache", return_value=mock_redis):
            results = []
            async for chunk in agentbus_service.stream_messages("did:agentx:agent"):
                results.append(chunk)

        assert len(results) == 1
        assert results[0].startswith("data: ")
        assert '{"content": "hello"}' in results[0]

    @pytest.mark.asyncio
    async def test_ignores_non_message_type_events(self):
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe   = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose      = AsyncMock()

        async def _listen():
            yield {"type": "subscribe", "data": 1}
            yield {"type": "psubscribe", "data": None}
            yield {"type": "message", "data": "real_data"}

        mock_pubsub.listen = _listen

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("src.services.agentbus_service.get_cache", return_value=mock_redis):
            results = []
            async for chunk in agentbus_service.stream_messages("did:agentx:agent"):
                results.append(chunk)

        # Only the "message" type should yield
        assert len(results) == 1
        assert "real_data" in results[0]

    @pytest.mark.asyncio
    async def test_unsubscribes_on_completion(self):
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe   = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose      = AsyncMock()

        async def _empty():
            return
            yield

        mock_pubsub.listen = _empty

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("src.services.agentbus_service.get_cache", return_value=mock_redis):
            async for _ in agentbus_service.stream_messages("did:agentx:agent"):
                pass

        mock_pubsub.unsubscribe.assert_called_once()
        mock_pubsub.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_sse_format_is_correct(self):
        """Each yielded frame must end with double newline."""
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe   = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose      = AsyncMock()

        async def _listen():
            yield {"type": "message", "data": "payload1"}
            yield {"type": "message", "data": "payload2"}

        mock_pubsub.listen = _listen

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("src.services.agentbus_service.get_cache", return_value=mock_redis):
            results = []
            async for chunk in agentbus_service.stream_messages("did:agentx:agent"):
                results.append(chunk)

        assert len(results) == 2
        for frame in results:
            assert frame.endswith("\n\n")
            assert frame.startswith("data: ")


# -- execute_agentbus_message (worker function) --------------------------------

class TestExecuteAgentbusMessage:

    def test_returns_worker_ok_status(self):
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync") as mock_pub:
            result = execute_agentbus_message({
                "message_id":   str(uuid4()),
                "sender_did":   "did:agentx:sender",
                "receiver_did": "did:agentx:receiver",
                "content":      "Hello",
                "channel":      "default",
            })

        assert result["status"] == "worker_ok"
        assert result["processed"] is True

    def test_publishes_agent_message_received(self):
        from workers.executor import execute_agentbus_message

        msg_id = str(uuid4())
        with patch("workers.executor.publish_event_sync") as mock_pub:
            execute_agentbus_message({
                "message_id":   msg_id,
                "sender_did":   "did:agentx:sender",
                "receiver_did": "did:agentx:receiver",
                "content":      "Hello",
                "channel":      "default",
            })

        mock_pub.assert_called_once()
        event_type = mock_pub.call_args[0][0]
        assert event_type == "AGENT_MESSAGE_RECEIVED"

    def test_nlp_channel_produces_nlp_output(self):
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync"):
            result = execute_agentbus_message({
                "message_id": str(uuid4()),
                "channel": "nlp.classify",
                "content": "Classify this text",
            })

        assert "NLP" in result["output"]

    def test_data_channel_produces_data_output(self):
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync"):
            result = execute_agentbus_message({
                "message_id": str(uuid4()),
                "channel": "data.transform",
                "content": "Transform this data",
            })

        assert "Data" in result["output"]

    def test_generic_channel_produces_delivered_output(self):
        from workers.executor import execute_agentbus_message

        msg_id = str(uuid4())
        with patch("workers.executor.publish_event_sync"):
            result = execute_agentbus_message({
                "message_id":   msg_id,
                "receiver_did": "did:agentx:agent",
                "channel":      "default",
                "content":      "hi",
            })

        assert msg_id in result["output"]

    def test_handles_missing_fields_gracefully(self):
        """Empty dict should not raise — uses default values."""
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync"):
            result = execute_agentbus_message({})

        assert result["status"] == "worker_ok"

    def test_source_agent_did_set_to_receiver(self):
        """AGENT_MESSAGE_RECEIVED is published with source_agent_did=receiver_did."""
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync") as mock_pub:
            execute_agentbus_message({
                "message_id":   str(uuid4()),
                "receiver_did": "did:agentx:receiver",
                "channel":      "default",
            })

        kwargs = mock_pub.call_args[1]
        assert kwargs.get("source_agent_did") == "did:agentx:receiver"

    def test_payload_contains_all_required_fields(self):
        """AGENT_MESSAGE_RECEIVED payload includes message_id, sender, receiver, channel."""
        from workers.executor import execute_agentbus_message

        msg_id = str(uuid4())
        with patch("workers.executor.publish_event_sync") as mock_pub:
            execute_agentbus_message({
                "message_id":   msg_id,
                "sender_did":   "did:agentx:alice",
                "receiver_did": "did:agentx:bob",
                "channel":      "urgent",
            })

        payload = mock_pub.call_args[0][1]
        assert payload["message_id"] == msg_id
        assert payload["sender_did"] == "did:agentx:alice"
        assert payload["receiver_did"] == "did:agentx:bob"
        assert payload["channel"] == "urgent"
        assert "compute_time_ms" in payload

    def test_compute_time_is_non_negative(self):
        from workers.executor import execute_agentbus_message

        with patch("workers.executor.publish_event_sync") as mock_pub:
            execute_agentbus_message({"message_id": str(uuid4())})

        payload = mock_pub.call_args[0][1]
        assert payload["compute_time_ms"] >= 0


# -- agentbus channel key helper -----------------------------------------------

class TestAgentbusChannelKey:

    def test_channel_key_format(self):
        key = agentbus_service._agentbus_channel("did:agentx:alice")
        assert key == "agentbus:did:agentx:alice"

    def test_channel_key_unique_per_agent(self):
        key1 = agentbus_service._agentbus_channel("did:agentx:alice")
        key2 = agentbus_service._agentbus_channel("did:agentx:bob")
        assert key1 != key2

    def test_channel_key_has_prefix(self):
        key = agentbus_service._agentbus_channel("did:agentx:agent")
        assert key.startswith("agentbus:")

    def test_row_to_acp_handles_dict_metadata(self):
        """_row_to_acp should accept dict metadata (not just str)."""
        row = _message_row()
        row["metadata"] = {"nested": True}  # dict, not str
        msg = agentbus_service._row_to_acp(row)
        assert msg.metadata == {"nested": True}

    def test_row_to_acp_handles_none_metadata(self):
        """_row_to_acp converts None metadata to an empty dict."""
        row = _message_row()
        row["metadata"] = None
        msg = agentbus_service._row_to_acp(row)
        assert msg.metadata == {}
