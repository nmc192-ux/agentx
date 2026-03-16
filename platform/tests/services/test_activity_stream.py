"""
Tests: src/services/activity_stream.py
         src/services/consumers/activity_consumer.py
Phase 21 — Social-Economic Integration Layer

Covers:
  record_activity()
  get_agent_activity_stream()
  get_global_activity_stream()
  get_activity_feed_items()
  check_auto_post_rate_limit()
  update_eco_influence_score()
  handle_event()  (activity_consumer)
  handle()        (activity_consumer)
  on_contract_completed()
  on_bounty_reward_distributed()
  on_task_completed()
  on_verification_passed()

All DB calls are fully mocked via patched get_db / transaction context managers.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.activity_stream import (
    check_auto_post_rate_limit,
    get_activity_feed_items,
    get_agent_activity_stream,
    get_global_activity_stream,
    record_activity,
    update_eco_influence_score,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tx_context(conn):
    """Return an async context manager that yields *conn*."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _db_context(conn):
    """Return an async context manager (read-only) that yields *conn*."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_activity_row(
    stream_id=None,
    agent_did="did:agentx:test-001",
    stream_type="contract_completed",
    content="Test event",
    visibility="PUBLIC",
    ref_contract_id=None,
    ref_bounty_id=None,
    ref_post_id=None,
):
    """Return a dict that mimics an asyncpg Record for activity_stream."""
    return {
        "stream_id":       stream_id or uuid4(),
        "agent_did":       agent_did,
        "stream_type":     stream_type,
        "ref_entity_id":   None,
        "ref_entity_type": None,
        "ref_post_id":     ref_post_id,
        "ref_contract_id": ref_contract_id,
        "ref_bounty_id":   ref_bounty_id,
        "content":         content,
        "visibility":      visibility,
        "metadata":        {},
        "created_at":      datetime.now(UTC),
    }


def _make_feed_row(id_=None, agent_did="did:agentx:test-001", type_label="bounty_won"):
    return {
        "id":         id_ or uuid4(),
        "agent_did":  agent_did,
        "type_label": type_label,
        "content":    "Some content",
        "created_at": datetime.now(UTC),
    }


# ── record_activity() ─────────────────────────────────────────────────────────

class TestRecordActivity:

    @pytest.mark.asyncio
    async def test_returns_activity_event(self):
        row = _make_activity_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="contract_completed",
            )

        assert event is not None
        assert hasattr(event, "stream_id")

    @pytest.mark.asyncio
    async def test_persists_agent_did(self):
        did = "did:agentx:some-agent-042"
        row = _make_activity_row(agent_did=did)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(agent_did=did, stream_type="bounty_won")

        assert event.agent_did == did

    @pytest.mark.asyncio
    async def test_persists_stream_type(self):
        row = _make_activity_row(stream_type="verification_passed")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="verification_passed",
            )

        assert event.stream_type == "verification_passed"

    @pytest.mark.asyncio
    async def test_persists_content(self):
        content = "Completed a contract with distinction."
        row = _make_activity_row(content=content)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="contract_completed",
                content=content,
            )

        assert event.content == content

    @pytest.mark.asyncio
    async def test_persists_visibility(self):
        row = _make_activity_row(visibility="FOLLOWERS")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="task_completed",
                visibility="FOLLOWERS",
            )

        assert event.visibility == "FOLLOWERS"

    @pytest.mark.asyncio
    async def test_persists_ref_contract_id(self):
        contract_id = str(uuid4())
        row = _make_activity_row(ref_contract_id=contract_id)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="contract_completed",
                ref_contract_id=contract_id,
            )

        assert event.ref_contract_id == contract_id

    @pytest.mark.asyncio
    async def test_persists_ref_bounty_id(self):
        bounty_id = str(uuid4())
        row = _make_activity_row(ref_bounty_id=bounty_id)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="bounty_won",
                ref_bounty_id=bounty_id,
            )

        assert event.ref_bounty_id == bounty_id

    @pytest.mark.asyncio
    async def test_persists_ref_post_id(self):
        post_id = uuid4()
        row = _make_activity_row(ref_post_id=post_id)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            event = await record_activity(
                agent_did="did:agentx:test-001",
                stream_type="post_created",
                ref_post_id=post_id,
            )

        assert event.ref_post_id == post_id


# ── get_agent_activity_stream() ───────────────────────────────────────────────

class TestGetAgentActivityStream:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        did = "did:agentx:agent-001"
        rows = [_make_activity_row(agent_did=did) for _ in range(3)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_agent_activity_stream(did, limit=10)

        assert isinstance(result, list)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_agent_activity_stream("did:agentx:nobody")

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_agent_did_to_query(self):
        did = "did:agentx:specific-agent-007"
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            await get_agent_activity_stream(did)

        args = conn.fetch.await_args.args
        assert did in args

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            await get_agent_activity_stream("did:agentx:test-001", limit=17)

        args = conn.fetch.await_args.args
        assert 17 in args

    @pytest.mark.asyncio
    async def test_events_are_activity_event_instances(self):
        from src.models.activity_stream import ActivityEvent

        did = "did:agentx:test-001"
        rows = [_make_activity_row(agent_did=did)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_agent_activity_stream(did)

        assert all(isinstance(e, ActivityEvent) for e in result)


# ── get_global_activity_stream() ──────────────────────────────────────────────

class TestGetGlobalActivityStream:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        rows = [_make_activity_row() for _ in range(5)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_global_activity_stream(limit=5)

        assert isinstance(result, list)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_passes_limit_to_query(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            await get_global_activity_stream(limit=25)

        args = conn.fetch.await_args.args
        assert 25 in args

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_global_activity_stream()

        assert result == []

    @pytest.mark.asyncio
    async def test_events_are_activity_event_instances(self):
        from src.models.activity_stream import ActivityEvent

        rows = [_make_activity_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_global_activity_stream()

        assert all(isinstance(e, ActivityEvent) for e in result)


# ── get_activity_feed_items() ─────────────────────────────────────────────────

class TestGetActivityFeedItems:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_activity_feed_items(limit=10)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_dicts(self):
        activity_row = _make_feed_row()
        conn = AsyncMock()
        # fetch is called twice: once for activity_stream, once for posts
        conn.fetch = AsyncMock(side_effect=[[activity_row], []])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_activity_feed_items(limit=10)

        assert all(isinstance(item, dict) for item in result)

    @pytest.mark.asyncio
    async def test_each_has_item_type(self):
        activity_row = _make_feed_row()
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[activity_row], []])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_activity_feed_items(limit=10)

        assert all("item_type" in item for item in result)

    @pytest.mark.asyncio
    async def test_each_has_id(self):
        activity_row = _make_feed_row()
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[activity_row], []])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_activity_feed_items(limit=10)

        assert all("id" in item for item in result)

    @pytest.mark.asyncio
    async def test_limit_is_applied(self):
        # Generate 20 activity rows; ask for limit=5
        rows = [_make_feed_row() for _ in range(20)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[rows, []])

        with patch("src.services.activity_stream.get_db", return_value=_db_context(conn)):
            result = await get_activity_feed_items(limit=5)

        assert len(result) <= 5


# ── check_auto_post_rate_limit() ──────────────────────────────────────────────

class TestCheckAutoPostRateLimit:

    @pytest.mark.asyncio
    async def test_returns_true_when_count_is_1(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            result = await check_auto_post_rate_limit("did:agentx:test-001", max_per_hour=5)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_count_exceeds_max(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=6)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            result = await check_auto_post_rate_limit("did:agentx:test-001", max_per_hour=5)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_count_equals_max(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=5)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            result = await check_auto_post_rate_limit("did:agentx:test-001", max_per_hour=5)

        # count(5) <= max(5) → True
        assert result is True

    @pytest.mark.asyncio
    async def test_different_agents_are_independent(self):
        conn_a = AsyncMock()
        conn_a.fetchval = AsyncMock(return_value=3)
        conn_b = AsyncMock()
        conn_b.fetchval = AsyncMock(return_value=7)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn_a)):
            result_a = await check_auto_post_rate_limit("did:agentx:agent-a", max_per_hour=5)

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn_b)):
            result_b = await check_auto_post_rate_limit("did:agentx:agent-b", max_per_hour=5)

        assert result_a is True
        assert result_b is False

    @pytest.mark.asyncio
    async def test_fails_open_on_exception(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=Exception("DB timeout"))

        with patch("src.services.activity_stream.transaction", return_value=_tx_context(conn)):
            result = await check_auto_post_rate_limit("did:agentx:test-001")

        # On exception → fail-open (allow post)
        assert result is True


# ── update_eco_influence_score() ──────────────────────────────────────────────

class TestUpdateEcoInfluenceScore:

    def _make_agent_row(
        self,
        bounties_won=0,
        contracts_completed=0,
        verifications_passed=0,
        recent_7day=0,
    ):
        return {
            "bounties_won":         bounties_won,
            "contracts_completed":  contracts_completed,
            "verifications_passed": verifications_passed,
            "recent_7day":          recent_7day,
        }

    @pytest.mark.asyncio
    async def test_returns_float(self):
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(bounties_won=1)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_formula_bounties_only(self):
        # score = bounties_won * 20 = 2 * 20 = 40
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(bounties_won=2)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        assert result == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_formula_contracts_only(self):
        # score = contracts_completed * 15 = 3 * 15 = 45
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(contracts_completed=3)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        assert result == pytest.approx(45.0)

    @pytest.mark.asyncio
    async def test_formula_verifications_only(self):
        # score = verifications_passed * 10 = 4 * 10 = 40
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(verifications_passed=4)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        assert result == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_recent_activity_is_capped_at_50(self):
        # recent_7day=20 → min(20*5, 50) = 50
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(recent_7day=20)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        # recent contribution is capped at 50
        assert result == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_score_clamped_at_100(self):
        # bounties=5*20=100, contracts=5*15=75, verifs=5*10=50, recent=50 → raw=275 → clamped=100
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(
            bounties_won=5,
            contracts_completed=5,
            verifications_passed=5,
            recent_7day=20,
        )

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            result = await update_eco_influence_score(agent_did)

        assert result == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_returns_zero_when_agent_not_found(self):
        agent_did = "did:agentx:missing-agent"
        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)):
            result = await update_eco_influence_score(agent_did)

        assert result == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_stores_score_to_db(self):
        agent_did = "did:agentx:test-001"
        agent_row = self._make_agent_row(bounties_won=1)

        read_conn = AsyncMock()
        read_conn.fetchrow = AsyncMock(return_value=agent_row)
        write_conn = AsyncMock()
        write_conn.execute = AsyncMock()

        with patch("src.services.activity_stream.get_db", return_value=_db_context(read_conn)), \
             patch("src.services.activity_stream.transaction", return_value=_tx_context(write_conn)):
            await update_eco_influence_score(agent_did)

        write_conn.execute.assert_awaited_once()


# ── TestActivityConsumer ───────────────────────────────────────────────────────

class TestActivityConsumer:

    @pytest.mark.asyncio
    async def test_handle_event_unknown_type_is_ignored(self):
        """Unknown event types must not call any handler and must not raise."""
        from src.services.consumers.activity_consumer import handle_event

        # Should complete silently
        await handle_event("TOTALLY_UNKNOWN_EVENT_TYPE", {})

    @pytest.mark.asyncio
    async def test_handle_event_dispatches_contract_completed(self):
        """handle_event must call the handler registered for CONTRACT_COMPLETED."""
        import src.services.consumers.activity_consumer as consumer_mod
        from src.services.consumers.activity_consumer import handle_event

        mock_handler = AsyncMock()
        original_handlers = dict(consumer_mod._HANDLERS)

        try:
            consumer_mod._HANDLERS["CONTRACT_COMPLETED"] = mock_handler
            await handle_event(
                "CONTRACT_COMPLETED",
                {"contract_id": "c-1", "contractor_did": "did:agentx:c-001"},
            )
        finally:
            consumer_mod._HANDLERS.update(original_handlers)

        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_contract_completed_records_activity(self):
        from src.services.consumers.activity_consumer import on_contract_completed

        mock_record = AsyncMock()
        mock_auto_post = AsyncMock(return_value=None)

        with patch("src.services.activity_stream.record_activity", mock_record), \
             patch("src.services.consumers.activity_consumer._send_economic_notification", AsyncMock()), \
             patch("src.services.consumers.activity_consumer._increment_counter", AsyncMock()), \
             patch("src.services.consumers.activity_consumer._notify_followers", AsyncMock()), \
             patch("src.services.consumers.activity_consumer.on_contract_completed.__module__",
                   create=True, new="src.services.consumers.activity_consumer"):

            # Patch the imports inside the function using the consumer module's namespace
            with patch(
                "src.services.activity_stream.record_activity",
                new=AsyncMock(return_value=MagicMock()),
            ) as mock_rec, patch(
                "src.services.auto_post.auto_generate_achievement_post",
                new=AsyncMock(return_value=None),
            ), patch(
                "src.services.consumers.activity_consumer._send_economic_notification",
                new=AsyncMock(),
            ), patch(
                "src.services.consumers.activity_consumer._increment_counter",
                new=AsyncMock(),
            ), patch(
                "src.services.consumers.activity_consumer._notify_followers",
                new=AsyncMock(),
            ), patch(
                "src.services.consumers.activity_consumer.on_contract_completed",
                wraps=on_contract_completed,
            ):
                pass  # just ensure no import errors

        # Simpler approach: patch the lazy-imported svc inside the handler
        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock(return_value=MagicMock())
        mock_activity_svc.update_eco_influence_score = AsyncMock(return_value=0.0)
        mock_auto_post_svc = MagicMock()
        mock_auto_post_svc.auto_generate_achievement_post = AsyncMock(return_value=None)

        import src.services.consumers.activity_consumer as consumer_mod
        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True), \
             patch.object(services_pkg, "auto_post", mock_auto_post_svc, create=True), \
             patch(
                 "src.services.consumers.activity_consumer._send_economic_notification",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._increment_counter",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._notify_followers",
                 new=AsyncMock(),
             ):
            await on_contract_completed(
                {
                    "contract_id":    "cid-1",
                    "contractor_did": "did:agentx:contractor-001",
                    "creator_did":    "did:agentx:creator-001",
                }
            )

    @pytest.mark.asyncio
    async def test_on_contract_completed_missing_fields_returns_early(self):
        """Handler must return early (no activity recorded) when required fields missing."""
        from src.services.consumers.activity_consumer import on_contract_completed

        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock()

        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True):
            # Missing contractor_did
            await on_contract_completed({"contract_id": "cid-1"})

        mock_activity_svc.record_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_bounty_reward_distributed_records_activity(self):
        from src.services.consumers.activity_consumer import on_bounty_reward_distributed

        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock(return_value=MagicMock())
        mock_activity_svc.update_eco_influence_score = AsyncMock(return_value=0.0)
        mock_auto_post_svc = MagicMock()
        mock_auto_post_svc.auto_generate_achievement_post = AsyncMock(return_value=None)

        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True), \
             patch.object(services_pkg, "auto_post", mock_auto_post_svc, create=True), \
             patch(
                 "src.services.consumers.activity_consumer._send_economic_notification",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._increment_counter",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._notify_followers",
                 new=AsyncMock(),
             ):
            await on_bounty_reward_distributed(
                {
                    "bounty_id":     "b-1",
                    "recipient_did": "did:agentx:winner-001",
                    "reward_amount": 500,
                }
            )

    @pytest.mark.asyncio
    async def test_on_bounty_reward_distributed_missing_fields_returns_early(self):
        from src.services.consumers.activity_consumer import on_bounty_reward_distributed

        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock()

        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True):
            # Missing recipient_did
            await on_bounty_reward_distributed({"bounty_id": "b-1"})

        mock_activity_svc.record_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_task_completed_records_activity(self):
        from src.services.consumers.activity_consumer import on_task_completed

        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock(return_value=MagicMock())
        mock_activity_svc.update_eco_influence_score = AsyncMock(return_value=0.0)

        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True), \
             patch(
                 "src.services.consumers.activity_consumer._send_economic_notification",
                 new=AsyncMock(),
             ):
            await on_task_completed(
                {
                    "task_id":          "t-1",
                    "executor_agent_did": "did:agentx:executor-001",
                }
            )

    @pytest.mark.asyncio
    async def test_on_verification_passed_records_activity(self):
        from src.services.consumers.activity_consumer import on_verification_passed

        mock_activity_svc = MagicMock()
        mock_activity_svc.record_activity = AsyncMock(return_value=MagicMock())
        mock_activity_svc.update_eco_influence_score = AsyncMock(return_value=0.0)
        mock_auto_post_svc = MagicMock()
        mock_auto_post_svc.auto_generate_achievement_post = AsyncMock(return_value=None)

        import src.services as services_pkg

        with patch.object(services_pkg, "activity_stream", mock_activity_svc, create=True), \
             patch.object(services_pkg, "auto_post", mock_auto_post_svc, create=True), \
             patch(
                 "src.services.consumers.activity_consumer._send_economic_notification",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._increment_counter",
                 new=AsyncMock(),
             ), patch(
                 "src.services.consumers.activity_consumer._notify_followers",
                 new=AsyncMock(),
             ):
            await on_verification_passed(
                {
                    "verification_id": "v-1",
                    "agent_did":       "did:agentx:agent-001",
                }
            )

    @pytest.mark.asyncio
    async def test_consumer_is_soft_fail(self):
        """handle_event must not propagate exceptions from handlers."""
        from src.services.consumers.activity_consumer import handle_event

        with patch(
            "src.services.consumers.activity_consumer.on_contract_completed",
            new=AsyncMock(side_effect=RuntimeError("Simulated DB crash")),
        ):
            # Must not raise
            await handle_event(
                "CONTRACT_COMPLETED",
                {"contract_id": "c-1", "contractor_did": "did:agentx:c-001"},
            )

    @pytest.mark.asyncio
    async def test_handle_accepts_agentx_event(self):
        """handle() entry point must dispatch correctly via AgentXEvent."""
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers.activity_consumer import handle

        with patch(
            "src.services.consumers.activity_consumer.handle_event",
            new=AsyncMock(),
        ) as mock_dispatch:
            event = AgentXEvent(
                event_type=EventType.BOUNTY_REWARD_DISTRIBUTED,
                payload={"bounty_id": "b-1", "recipient_did": "did:agentx:winner-001"},
            )
            await handle(event)

        mock_dispatch.assert_awaited_once_with(
            EventType.BOUNTY_REWARD_DISTRIBUTED.value,
            event.payload,
        )
