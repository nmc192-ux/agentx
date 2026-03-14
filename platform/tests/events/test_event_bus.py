"""
Tests: src/events/ — Event Bus (Phase 7)

Covers:
  types.py        — AgentXEvent serialisation / deserialisation
  bus.py          — ensure_consumer_group (success, BUSYGROUP, Redis unavailable)
  publisher.py    — publish_event (success, Redis unavailable, XADD error)
                    publish_event_sync (success, failure)
  consumer.py     — ack_event (success, failure)
  handlers/       — reputation_handler, feed_handler, notification_handler
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.events.types import AgentXEvent, EventType


# ── AgentXEvent serialisation ─────────────────────────────────────────────────

class TestAgentXEvent:

    def test_to_stream_fields_contains_all_keys(self):
        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"task_id": "abc-123"},
            source_agent_did="did:agentx:atlas-001",
        )
        fields = event.to_stream_fields()
        assert fields["event_type"] == "TASK_COMPLETED"
        assert fields["source_agent_did"] == "did:agentx:atlas-001"
        assert json.loads(fields["payload"]) == {"task_id": "abc-123"}
        assert "event_id" in fields
        assert "timestamp" in fields

    def test_to_stream_fields_empty_agent_did_becomes_empty_string(self):
        event = AgentXEvent(event_type=EventType.POST_CREATED, payload={})
        fields = event.to_stream_fields()
        assert fields["source_agent_did"] == ""

    def test_from_stream_fields_round_trips(self):
        original = AgentXEvent(
            event_type=EventType.COLLECTIVE_JOINED,
            payload={"collective_id": str(uuid4())},
            source_agent_did="did:agentx:bruno-001",
        )
        fields = original.to_stream_fields()
        restored = AgentXEvent.from_stream_fields(fields)

        assert restored.event_type == original.event_type
        assert restored.payload == original.payload
        assert restored.source_agent_did == original.source_agent_did
        assert restored.event_id == original.event_id

    def test_from_stream_fields_handles_empty_agent_did(self):
        fields = {
            "event_type": "TASK_FAILED",
            "source_agent_did": "",
            "payload": "{}",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        event = AgentXEvent.from_stream_fields(fields)
        assert event.source_agent_did is None


# ── bus.ensure_consumer_group ─────────────────────────────────────────────────

class TestEnsureConsumerGroup:

    @pytest.mark.asyncio
    async def test_creates_group_successfully(self):
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(return_value=True)

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.bus import ensure_consumer_group
            result = await ensure_consumer_group()

        assert result is True
        mock_redis.xgroup_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_busygroup_error_treated_as_success(self):
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=Exception("BUSYGROUP Consumer Group name already exists")
        )

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.bus import ensure_consumer_group
            result = await ensure_consumer_group()

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_redis_unavailable(self):
        with patch("src.events.bus.get_bus_client", return_value=None):
            from src.events.bus import ensure_consumer_group
            result = await ensure_consumer_group()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_unexpected_error(self):
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=ConnectionError("Redis connection refused")
        )

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.bus import ensure_consumer_group
            result = await ensure_consumer_group()

        assert result is False


# ── publisher.publish_event ───────────────────────────────────────────────────

class TestPublishEvent:

    @pytest.mark.asyncio
    async def test_publishes_event_and_returns_stream_id(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1714059123456-0")

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.publisher import publish_event
            stream_id = await publish_event(
                EventType.TASK_COMPLETED,
                {"task_id": str(uuid4())},
                "did:agentx:atlas-001",
            )

        assert stream_id == "1714059123456-0"
        mock_redis.xadd.assert_awaited_once()

        # Verify the stream name and fields are correct
        call_args = mock_redis.xadd.await_args
        assert call_args.args[0] == "agentx.events"
        fields = call_args.args[1]
        assert fields["event_type"] == "TASK_COMPLETED"
        assert fields["source_agent_did"] == "did:agentx:atlas-001"

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_unavailable(self):
        with patch("src.events.bus.get_bus_client", return_value=None):
            from src.events.publisher import publish_event
            result = await publish_event(EventType.TASK_CREATED, {})

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_xadd_error(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.publisher import publish_event
            result = await publish_event(EventType.TASK_FAILED, {"task_id": "abc"})

        assert result is None

    @pytest.mark.asyncio
    async def test_accepts_string_event_type(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234-0")

        with patch("src.events.bus.get_bus_client", return_value=mock_redis):
            from src.events.publisher import publish_event
            result = await publish_event("TASK_COMPLETED", {"task_id": "x"})

        assert result == "1234-0"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_string_event_type(self):
        with patch("src.events.bus.get_bus_client", return_value=AsyncMock()):
            from src.events.publisher import publish_event
            result = await publish_event("NOT_A_REAL_EVENT", {})

        assert result is None


# ── publisher.publish_event_sync ──────────────────────────────────────────────

class TestPublishEventSync:

    def test_publishes_synchronously_and_returns_stream_id(self):
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="9999-0")

        with patch("src.events.publisher.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            from src.events.publisher import publish_event_sync
            result = publish_event_sync("TASK_COMPLETED", {"task_id": "abc"})

        assert result == "9999-0"
        mock_redis.xadd.assert_called_once()
        call_fields = mock_redis.xadd.call_args.args[1]
        assert call_fields["event_type"] == "TASK_COMPLETED"

    def test_returns_none_on_connection_error(self):
        with patch("src.events.publisher.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.side_effect = ConnectionError("Redis down")
            from src.events.publisher import publish_event_sync
            result = publish_event_sync("TASK_FAILED", {"task_id": "xyz"})

        assert result is None


# ── consumer.ack_event ────────────────────────────────────────────────────────

class TestAckEvent:

    @pytest.mark.asyncio
    async def test_acks_event_successfully(self):
        mock_redis = AsyncMock()
        mock_redis.xack = AsyncMock(return_value=1)

        with patch("src.events.consumer.get_bus_client", return_value=mock_redis):
            from src.events.consumer import ack_event
            result = await ack_event("1234-0")

        assert result is True
        mock_redis.xack.assert_awaited_once_with(
            "agentx.events", "agentx-services", "1234-0"
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_redis_unavailable(self):
        with patch("src.events.consumer.get_bus_client", return_value=None):
            from src.events.consumer import ack_event
            result = await ack_event("1234-0")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_xack_error(self):
        mock_redis = AsyncMock()
        mock_redis.xack = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.events.consumer.get_bus_client", return_value=mock_redis):
            from src.events.consumer import ack_event
            result = await ack_event("5678-0")

        assert result is False


# ── reputation_handler ────────────────────────────────────────────────────────

class TestReputationHandler:

    @pytest.mark.asyncio
    async def test_task_completed_calls_record_event(self):
        """Patch at the source module since reputation_handler uses a lazy import."""
        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"task_id": "t1"},
            source_agent_did="did:agentx:atlas-001",
        )
        mock_record_event = AsyncMock()
        with patch("src.services.reputation.record_event", new=mock_record_event):
            from src.events.handlers.reputation_handler import handle
            await handle(event)

        mock_record_event.assert_awaited_once()
        call_args = mock_record_event.await_args
        assert call_args.args[0] == "did:agentx:atlas-001"
        assert call_args.args[1] == "task_completed"

    @pytest.mark.asyncio
    async def test_task_failed_calls_record_event_with_task_failed(self):
        event = AgentXEvent(
            event_type=EventType.TASK_FAILED,
            payload={"task_id": "t2"},
            source_agent_did="did:agentx:atlas-001",
        )
        mock_record_event = AsyncMock()
        with patch("src.services.reputation.record_event", new=mock_record_event):
            from src.events.handlers.reputation_handler import handle
            await handle(event)

        mock_record_event.assert_awaited_once()
        assert mock_record_event.await_args.args[1] == "task_failed"

    @pytest.mark.asyncio
    async def test_skips_if_no_agent_did(self):
        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"task_id": "t3"},
            source_agent_did=None,
        )
        mock_record_event = AsyncMock()
        with patch("src.services.reputation.record_event", new=mock_record_event):
            from src.events.handlers.reputation_handler import handle
            await handle(event)

        mock_record_event.assert_not_awaited()


# ── feed_handler ──────────────────────────────────────────────────────────────

class TestFeedHandler:

    @pytest.mark.asyncio
    async def test_post_created_deletes_agent_and_global_feed_cache(self):
        event = AgentXEvent(
            event_type=EventType.POST_CREATED,
            payload={"post_id": str(uuid4())},
            source_agent_did="did:agentx:atlas-001",
        )
        mock_cache_delete = AsyncMock()
        with patch("src.cache.cache_delete", new=mock_cache_delete):
            from src.events.handlers.feed_handler import handle
            await handle(event)

        deleted_keys = [c.args[0] for c in mock_cache_delete.await_args_list]
        assert "feed:did:agentx:atlas-001" in deleted_keys
        assert "feed:global" in deleted_keys

    @pytest.mark.asyncio
    async def test_agent_registered_invalidates_global_feed(self):
        event = AgentXEvent(
            event_type=EventType.AGENT_REGISTERED,
            payload={"agent_did": "did:agentx:new-001"},
            source_agent_did="did:agentx:new-001",
        )
        mock_cache_delete = AsyncMock()
        with patch("src.cache.cache_delete", new=mock_cache_delete):
            from src.events.handlers.feed_handler import handle
            await handle(event)

        deleted_keys = [c.args[0] for c in mock_cache_delete.await_args_list]
        assert "feed:global" in deleted_keys

    @pytest.mark.asyncio
    async def test_post_created_without_agent_did_still_clears_global(self):
        event = AgentXEvent(
            event_type=EventType.POST_CREATED,
            payload={},
            source_agent_did=None,
        )
        mock_cache_delete = AsyncMock()
        with patch("src.cache.cache_delete", new=mock_cache_delete):
            from src.events.handlers.feed_handler import handle
            await handle(event)

        deleted_keys = [c.args[0] for c in mock_cache_delete.await_args_list]
        assert "feed:global" in deleted_keys


# ── notification_handler ──────────────────────────────────────────────────────

class TestNotificationHandler:

    @pytest.mark.asyncio
    async def test_collective_created_emits_websocket_event(self):
        col_id = str(uuid4())
        event = AgentXEvent(
            event_type=EventType.COLLECTIVE_CREATED,
            payload={"collective_id": col_id},
            source_agent_did="did:agentx:atlas-001",
        )
        mock_emit = AsyncMock(return_value={"event_id": str(uuid4())})
        with patch("src.services.events.emit_event", new=mock_emit):
            from src.events.handlers.notification_handler import handle
            await handle(event)

        mock_emit.assert_awaited_once()
        args = mock_emit.await_args.args
        assert args[0] == "COLLECTIVE_CREATED"

    @pytest.mark.asyncio
    async def test_collective_joined_emits_websocket_event(self):
        event = AgentXEvent(
            event_type=EventType.COLLECTIVE_JOINED,
            payload={"collective_id": str(uuid4())},
            source_agent_did="did:agentx:bruno-001",
        )
        mock_emit = AsyncMock(return_value={"event_id": str(uuid4())})
        with patch("src.services.events.emit_event", new=mock_emit):
            from src.events.handlers.notification_handler import handle
            await handle(event)

        mock_emit.assert_awaited_once()
        args = mock_emit.await_args.args
        assert args[0] == "COLLECTIVE_JOINED"

    @pytest.mark.asyncio
    async def test_trust_updated_emits_websocket_event(self):
        event = AgentXEvent(
            event_type=EventType.TRUST_UPDATED,
            payload={"score": 0.95},
            source_agent_did="did:agentx:atlas-001",
        )
        mock_emit = AsyncMock(return_value={"event_id": str(uuid4())})
        with patch("src.services.events.emit_event", new=mock_emit):
            from src.events.handlers.notification_handler import handle
            await handle(event)

        mock_emit.assert_awaited_once()
        assert mock_emit.await_args.args[0] == "TRUST_UPDATED"


# ── handlers/__init__.py — HANDLERS registry ──────────────────────────────────

class TestHandlersRegistry:

    def test_all_expected_event_types_have_handlers(self):
        from src.events.handlers import HANDLERS
        expected = {
            "TASK_COMPLETED", "TASK_FAILED",
            "POST_CREATED", "AGENT_REGISTERED",
            "COLLECTIVE_CREATED", "COLLECTIVE_JOINED", "TRUST_UPDATED",
        }
        assert expected == set(HANDLERS.keys())

    def test_all_handlers_are_callable(self):
        from src.events.handlers import HANDLERS
        for event_type, handler in HANDLERS.items():
            assert callable(handler), f"Handler for {event_type} is not callable"
