"""
Tests: src/services/consumers/ and src/events/service_runner.py
═══════════════════════════════════════════════════════════════
Phase 12.5: Event-Driven Service Architecture

Covers:
  contract_consumer      — CONTRACT_COMPLETED, CONTRACT_RESULT_SUBMITTED
  economy_consumer       — TASK_REWARD_RELEASED, TOKEN_TRANSFER, TREASURY_REWARD
  reputation_consumer    — TASK_COMPLETED, CONTRACT_VERIFIED, VERIFICATION_SUBMITTED
  verification_consumer  — CONTRACT_VERIFICATION_REQUESTED
  service_runner         — _ensure_service_consumer_group, run_service_consumers
                           dispatch, failure resilience
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.events.types import AgentXEvent, EventType


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event(event_type: EventType, payload: dict | None = None, source_did: str | None = None) -> AgentXEvent:
    return AgentXEvent(
        event_type=event_type,
        payload=payload or {},
        source_agent_did=source_did,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CONTRACT CONSUMER
# ═════════════════════════════════════════════════════════════════════════════

class TestContractConsumer:

    @pytest.mark.asyncio
    async def test_contract_completed_calls_record_metrics(self):
        event = _event(
            EventType.CONTRACT_COMPLETED,
            {"contract_id": str(uuid4())},
            "did:agentx:creator-001",
        )
        mock_metrics = AsyncMock()
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.contract_consumer import handle
            await handle(event)

        mock_metrics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_contract_completed_failure_does_not_raise(self):
        """Service failure must not crash the consumer loop."""
        event = _event(EventType.CONTRACT_COMPLETED, {"contract_id": str(uuid4())})
        mock_metrics = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.contract_consumer import handle
            await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_result_submitted_logs_without_service_call(self):
        """CONTRACT_RESULT_SUBMITTED only logs — no heavy service call needed."""
        event = _event(
            EventType.CONTRACT_RESULT_SUBMITTED,
            {"contract_id": str(uuid4()), "result_id": str(uuid4())},
            "did:agentx:executor-001",
        )
        # No patch needed — handler just logs; we verify it does not raise.
        from src.services.consumers.contract_consumer import handle
        await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_unexpected_event_type_logs_warning(self):
        event = _event(EventType.POST_CREATED, {})
        from src.services.consumers.contract_consumer import handle
        await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_consumer_receives_event_and_dispatches(self):
        """Smoke test: consumer is callable and dispatches without errors."""
        contract_id = str(uuid4())
        event = _event(EventType.CONTRACT_COMPLETED, {"contract_id": contract_id})

        mock_metrics = AsyncMock()
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.contract_consumer import handle
            await handle(event)

        mock_metrics.assert_awaited_once()


# ═════════════════════════════════════════════════════════════════════════════
# ECONOMY CONSUMER
# ═════════════════════════════════════════════════════════════════════════════

class TestEconomyConsumer:

    @pytest.mark.asyncio
    async def test_reward_released_calls_record_metrics(self):
        event = _event(
            EventType.TASK_REWARD_RELEASED,
            {"task_id": str(uuid4()), "amount": 500},
            "did:agentx:executor-001",
        )
        mock_metrics = AsyncMock()
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.economy_consumer import handle
            await handle(event)

        mock_metrics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reward_released_failure_does_not_raise(self):
        event = _event(EventType.TASK_REWARD_RELEASED, {"task_id": str(uuid4())})
        mock_metrics = AsyncMock(side_effect=ConnectionError("Redis down"))
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.economy_consumer import handle
            await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_token_transfer_logs_and_does_not_raise(self):
        event = _event(
            EventType.TOKEN_TRANSFER,
            {"from_agent_did": "did:agentx:a", "to_agent_did": "did:agentx:b", "amount": 100},
        )
        from src.services.consumers.economy_consumer import handle
        await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_treasury_reward_calls_record_metrics(self):
        event = _event(
            EventType.TREASURY_REWARD,
            {"source": "task_fee", "amount": 50},
        )
        mock_metrics = AsyncMock()
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.economy_consumer import handle
            await handle(event)

        mock_metrics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_treasury_reward_failure_does_not_raise(self):
        event = _event(EventType.TREASURY_REWARD, {})
        mock_metrics = AsyncMock(side_effect=RuntimeError("metrics unavailable"))
        with patch("src.services.economy_service.record_metrics", new=mock_metrics):
            from src.services.consumers.economy_consumer import handle
            await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_unexpected_event_type_does_not_raise(self):
        event = _event(EventType.POST_CREATED, {})
        from src.services.consumers.economy_consumer import handle
        await handle(event)  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# REPUTATION CONSUMER
# ═════════════════════════════════════════════════════════════════════════════

class TestReputationConsumer:
    """S9-9b: the consumer passes ids on; the reputation service decides."""

    @pytest.mark.asyncio
    async def test_task_completed_reports_the_task_id(self):
        task_id = str(uuid4())
        event = _event(EventType.TASK_COMPLETED, {"task_id": task_id}, "did:agentx:executor-001")
        mock_record = AsyncMock(return_value="recorded")
        with patch("src.services.reputation.record_task_completed", new=mock_record):
            from src.services.consumers.reputation_consumer import handle
            await handle(event)

        mock_record.assert_awaited_once_with(task_id, source="service_consumer")

    @pytest.mark.asyncio
    async def test_task_completed_skips_if_no_task_id(self):
        event = _event(EventType.TASK_COMPLETED, {}, "did:agentx:executor-001")
        mock_record = AsyncMock()
        with patch("src.services.reputation.record_task_completed", new=mock_record):
            from src.services.consumers.reputation_consumer import handle
            await handle(event)

        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_contract_verified_reports_the_verification_id(self):
        """The requester named in the payload earns nothing: only the winning
        voters do, and the service reads them from the database."""
        vid = str(uuid4())
        event = _event(
            EventType.CONTRACT_VERIFIED,
            {"verification_id": vid, "requester_did": "did:agentx:requester-001"},
        )
        mock_outcome = AsyncMock(return_value={})
        mock_event = AsyncMock()
        with (
            patch("src.services.reputation.record_verification_outcome", new=mock_outcome),
            patch("src.services.reputation.record_event", new=mock_event),
        ):
            from src.services.consumers.reputation_consumer import handle
            await handle(event)

        mock_outcome.assert_awaited_once_with(vid)
        mock_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_contract_verified_skips_if_no_verification_id(self):
        event = _event(EventType.CONTRACT_VERIFIED, {}, source_did=None)
        mock_outcome = AsyncMock()
        with patch("src.services.reputation.record_verification_outcome", new=mock_outcome):
            from src.services.consumers.reputation_consumer import handle
            await handle(event)

        mock_outcome.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_vote_cast_earns_nothing_by_itself(self):
        event = _event(
            EventType.VERIFICATION_SUBMITTED,
            {"verification_id": str(uuid4()), "verifier_did": "did:agentx:verifier-001"},
            source_did="did:agentx:verifier-001",
        )
        mock_event = AsyncMock()
        mock_outcome = AsyncMock()
        with (
            patch("src.services.reputation.record_event", new=mock_event),
            patch("src.services.reputation.record_verification_outcome", new=mock_outcome),
        ):
            from src.services.consumers.reputation_consumer import handle
            await handle(event)

        mock_event.assert_not_awaited()
        mock_outcome.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unexpected_event_type_does_not_raise(self):
        event = _event(EventType.POST_CREATED, {})
        from src.services.consumers.reputation_consumer import handle
        await handle(event)  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# VERIFICATION CONSUMER
# ═════════════════════════════════════════════════════════════════════════════

class TestVerificationConsumer:

    @pytest.mark.asyncio
    async def test_verification_requested_calls_assign_verifiers(self):
        vid = str(uuid4())
        event = _event(
            EventType.CONTRACT_VERIFICATION_REQUESTED,
            {
                "verification_id": vid,
                "requester_did": "did:agentx:requester-001",
            },
        )
        mock_assign = AsyncMock()
        with patch("src.services.verification_service.assign_verifiers", new=mock_assign):
            from src.services.consumers.verification_consumer import handle
            await handle(event)

        mock_assign.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_active_value_error_is_swallowed(self):
        """assign_verifiers raises ValueError when verification is already active."""
        vid = str(uuid4())
        event = _event(
            EventType.CONTRACT_VERIFICATION_REQUESTED,
            {"verification_id": vid, "requester_did": "did:agentx:req"},
        )
        mock_assign = AsyncMock(side_effect=ValueError("verification is already active"))
        with patch("src.services.verification_service.assign_verifiers", new=mock_assign):
            from src.services.consumers.verification_consumer import handle
            await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_missing_verification_id_skips_gracefully(self):
        event = _event(
            EventType.CONTRACT_VERIFICATION_REQUESTED,
            {},  # no verification_id
        )
        mock_assign = AsyncMock()
        with patch("src.services.verification_service.assign_verifiers", new=mock_assign):
            from src.services.consumers.verification_consumer import handle
            await handle(event)

        mock_assign.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_service_failure_does_not_raise(self):
        vid = str(uuid4())
        event = _event(
            EventType.CONTRACT_VERIFICATION_REQUESTED,
            {"verification_id": vid},
        )
        mock_assign = AsyncMock(side_effect=RuntimeError("DB exploded"))
        with patch("src.services.verification_service.assign_verifiers", new=mock_assign):
            from src.services.consumers.verification_consumer import handle
            await handle(event)  # must not raise

    @pytest.mark.asyncio
    async def test_unexpected_event_type_does_not_raise(self):
        event = _event(EventType.POST_CREATED, {})
        from src.services.consumers.verification_consumer import handle
        await handle(event)  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# SERVICE RUNNER
# ═════════════════════════════════════════════════════════════════════════════

class TestServiceRunner:

    @pytest.mark.asyncio
    async def test_ensure_service_consumer_group_success(self):
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(return_value=True)

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            from src.events.service_runner import _ensure_service_consumer_group
            result = await _ensure_service_consumer_group()

        assert result is True
        mock_redis.xgroup_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_group_busygroup_treated_as_success(self):
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=Exception("BUSYGROUP Consumer Group already exists")
        )

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            from src.events.service_runner import _ensure_service_consumer_group
            result = await _ensure_service_consumer_group()

        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_group_returns_false_when_redis_unavailable(self):
        with patch("src.events.service_runner.get_bus_client", return_value=None):
            from src.events.service_runner import _ensure_service_consumer_group
            result = await _ensure_service_consumer_group()

        assert result is False

    @pytest.mark.asyncio
    async def test_run_service_consumers_returns_when_redis_unavailable(self):
        """Runner exits gracefully when Redis is not available."""
        with patch("src.events.service_runner.get_bus_client", return_value=None):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=False)):
                from src.events.service_runner import run_service_consumers
                # Should return without looping
                await asyncio.wait_for(run_service_consumers(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_runner_dispatches_contract_event_to_correct_consumer(self):
        """A CONTRACT_COMPLETED event should reach contract_consumer.handle."""
        event = AgentXEvent(
            event_type=EventType.CONTRACT_COMPLETED,
            payload={"contract_id": str(uuid4())},
        )
        fields = event.to_stream_fields()

        # Simulate a single batch then CancelledError to break the loop
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(
            side_effect=[
                [["agentx.events", [["1000-0", fields]]]],
                asyncio.CancelledError(),
            ]
        )
        mock_redis.xack = AsyncMock()

        mock_contract_handle = AsyncMock()

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=True)):
                with patch(
                    "src.services.consumers.contract_consumer.handle",
                    new=mock_contract_handle,
                ):
                    from src.events.service_runner import run_service_consumers
                    with pytest.raises(asyncio.CancelledError):
                        await run_service_consumers()

        mock_contract_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_dispatches_economy_event_to_correct_consumer(self):
        """A TOKEN_TRANSFER event should reach economy_consumer.handle."""
        event = AgentXEvent(
            event_type=EventType.TOKEN_TRANSFER,
            payload={"amount": 100},
        )
        fields = event.to_stream_fields()

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(
            side_effect=[
                [["agentx.events", [["1001-0", fields]]]],
                asyncio.CancelledError(),
            ]
        )
        mock_redis.xack = AsyncMock()

        mock_economy_handle = AsyncMock()

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=True)):
                with patch(
                    "src.services.consumers.economy_consumer.handle",
                    new=mock_economy_handle,
                ):
                    from src.events.service_runner import run_service_consumers
                    with pytest.raises(asyncio.CancelledError):
                        await run_service_consumers()

        mock_economy_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_handler_failure_does_not_crash_loop(self):
        """A handler that raises should not stop the consumer loop."""
        event = AgentXEvent(
            event_type=EventType.CONTRACT_COMPLETED,
            payload={"contract_id": str(uuid4())},
        )
        fields = event.to_stream_fields()

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(
            side_effect=[
                [["agentx.events", [["1002-0", fields]]]],
                asyncio.CancelledError(),
            ]
        )
        mock_redis.xack = AsyncMock()

        # Handler raises — but the loop should continue and eventually cancel
        mock_failing_handle = AsyncMock(side_effect=RuntimeError("handler boom"))

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=True)):
                with patch(
                    "src.services.consumers.contract_consumer.handle",
                    new=mock_failing_handle,
                ):
                    from src.events.service_runner import run_service_consumers
                    with pytest.raises(asyncio.CancelledError):
                        await run_service_consumers()

        # Even though handler raised, ACK was still sent
        mock_redis.xack.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_acks_event_after_malformed_parse(self):
        """Malformed stream fields should be ACK'd and loop continues."""
        # Bad fields that cannot be parsed into AgentXEvent
        bad_fields = {"event_type": "NOT_REAL_EVENT", "payload": "{}"}

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(
            side_effect=[
                [["agentx.events", [["1003-0", bad_fields]]]],
                asyncio.CancelledError(),
            ]
        )
        mock_redis.xack = AsyncMock()

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=True)):
                from src.events.service_runner import run_service_consumers
                with pytest.raises(asyncio.CancelledError):
                    await run_service_consumers()

        # Malformed event should still be ACK'd
        mock_redis.xack.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_skips_unknown_event_types(self):
        """Events with no registered handler are ACK'd and skipped."""
        event = AgentXEvent(
            event_type=EventType.POST_CREATED,  # not in SERVICE_HANDLERS
            payload={},
        )
        fields = event.to_stream_fields()

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(
            side_effect=[
                [["agentx.events", [["1004-0", fields]]]],
                asyncio.CancelledError(),
            ]
        )
        mock_redis.xack = AsyncMock()

        with patch("src.events.service_runner.get_bus_client", return_value=mock_redis):
            with patch("src.events.service_runner._ensure_service_consumer_group",
                       new=AsyncMock(return_value=True)):
                from src.events.service_runner import run_service_consumers
                with pytest.raises(asyncio.CancelledError):
                    await run_service_consumers()

        # Skipped but still ACK'd
        mock_redis.xack.assert_awaited_once()

    def test_service_handler_table_contains_all_expected_event_types(self):
        """Verify the dispatch table covers all Phase 12.5+ event types."""
        from src.events.service_runner import _build_handlers

        handlers = _build_handlers()
        expected = {
            "CONTRACT_COMPLETED",
            "CONTRACT_RESULT_SUBMITTED",
            "TASK_REWARD_RELEASED",
            "TOKEN_TRANSFER",
            "TREASURY_REWARD",
            "TASK_COMPLETED",
            "CONTRACT_VERIFIED",
            "VERIFICATION_SUBMITTED",
            "CONTRACT_VERIFICATION_REQUESTED",
            # Phase 16: Agent Discovery
            "BOUNTY_REWARD_DISTRIBUTED",
        }
        assert expected == set(handlers.keys())

    def test_all_service_handlers_are_callable(self):
        from src.events.service_runner import _build_handlers

        for event_type, handler in _build_handlers().items():
            assert callable(handler), f"Handler for {event_type} is not callable"
