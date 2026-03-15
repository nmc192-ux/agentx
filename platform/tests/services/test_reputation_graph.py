"""
Tests: src/services/reputation_graph.py
Phase 20 — Agent Reputation Graph

Covers:
  record_interaction()
  update_trust_weight()
  get_agent_trust_network()
  get_top_collaborators()
  get_graph_weight_for_agent()
  calculate_graph_enhanced_score()
  handle_task_completed()
  handle_contract_completed()
  handle_verification_submitted()
  _clamp()                         (via public API)

All DB calls are fully mocked via patched get_db / transaction context managers.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest

from src.services.reputation_graph import (
    calculate_graph_enhanced_score,
    get_agent_trust_network,
    get_graph_weight_for_agent,
    get_top_collaborators,
    handle_contract_completed,
    handle_task_completed,
    handle_verification_submitted,
    record_interaction,
    update_trust_weight,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_row(
    agent_id=None,
    peer_agent_id=None,
    trust_weight=0.5,
    interaction_count=1,
):
    """Return a dict that mimics an asyncpg Record for agent_reputation_graph."""
    return {
        "graph_id":          uuid4(),
        "agent_id":          agent_id or uuid4(),
        "peer_agent_id":     peer_agent_id or uuid4(),
        "trust_weight":      trust_weight,
        "interaction_count": interaction_count,
        "last_interaction":  datetime.now(UTC),
        "created_at":        datetime.now(UTC),
    }


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


# ── record_interaction() ──────────────────────────────────────────────────────

class TestRecordInteraction:

    @pytest.mark.asyncio
    async def test_raises_if_same_agent(self):
        agent_id = uuid4()
        with pytest.raises(ValueError, match="must be different"):
            await record_interaction(agent_id, agent_id)

    @pytest.mark.asyncio
    async def test_returns_graph_edge(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await record_interaction(a, b, weight_delta=0.1)

        assert edge.agent_id == a
        assert edge.peer_agent_id == b

    @pytest.mark.asyncio
    async def test_calls_fetchrow_once(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await record_interaction(a, b, weight_delta=0.1)

        conn.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_weight_delta_passed_to_query(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.15)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await record_interaction(a, b, weight_delta=0.15)

        args = conn.fetchrow.await_args.args
        # $3 is the weight_delta
        assert args[3] == 0.15

    @pytest.mark.asyncio
    async def test_trust_weight_returned_from_row(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.72)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await record_interaction(a, b)

        assert edge.trust_weight == pytest.approx(0.72)

    @pytest.mark.asyncio
    async def test_interaction_count_returned(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, interaction_count=7)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await record_interaction(a, b)

        assert edge.interaction_count == 7

    @pytest.mark.asyncio
    async def test_default_weight_delta_is_positive(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await record_interaction(a, b)  # weight_delta defaults to 0.10

        args = conn.fetchrow.await_args.args
        assert args[3] > 0

    @pytest.mark.asyncio
    async def test_negative_delta_accepted(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.0)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await record_interaction(a, b, weight_delta=-0.05, interaction_type="rivalry")

        assert edge.trust_weight == pytest.approx(0.0)


# ── update_trust_weight() ─────────────────────────────────────────────────────

class TestUpdateTrustWeight:

    @pytest.mark.asyncio
    async def test_sets_explicit_weight(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.8)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await update_trust_weight(a, b, 0.8)

        assert edge.trust_weight == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_clamps_above_one(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=1.0)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await update_trust_weight(a, b, 1.5)  # should be clamped to 1.0

        args = conn.fetchrow.await_args.args
        assert args[3] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_clamps_below_zero(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.0)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await update_trust_weight(a, b, -0.5)  # clamped to 0.0

        args = conn.fetchrow.await_args.args
        assert args[3] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_returns_graph_edge(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.5)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            edge = await update_trust_weight(a, b, 0.5)

        assert edge.agent_id == a
        assert edge.peer_agent_id == b

    @pytest.mark.asyncio
    async def test_zero_weight_accepted(self):
        a, b = uuid4(), uuid4()
        row = _make_row(agent_id=a, peer_agent_id=b, trust_weight=0.0)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.reputation_graph.transaction", return_value=_tx_context(conn)):
            await update_trust_weight(a, b, 0.0)

        args = conn.fetchrow.await_args.args
        assert args[3] == pytest.approx(0.0)


# ── get_agent_trust_network() ─────────────────────────────────────────────────

class TestGetAgentTrustNetwork:

    @pytest.mark.asyncio
    async def test_returns_list_of_edges(self):
        agent_id = uuid4()
        rows = [_make_row(agent_id=agent_id) for _ in range(3)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_agent_trust_network(agent_id, limit=10)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_edges(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_agent_trust_network(agent_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_passed_to_query(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            await get_agent_trust_network(agent_id, limit=42)

        args = conn.fetch.await_args.args
        assert 42 in args

    @pytest.mark.asyncio
    async def test_agent_id_passed_to_query(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            await get_agent_trust_network(agent_id)

        args = conn.fetch.await_args.args
        assert agent_id in args

    @pytest.mark.asyncio
    async def test_default_limit_is_20(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            await get_agent_trust_network(agent_id)

        args = conn.fetch.await_args.args
        assert 20 in args

    @pytest.mark.asyncio
    async def test_edge_fields_populated(self):
        agent_id = uuid4()
        peer_id = uuid4()
        rows = [_make_row(agent_id=agent_id, peer_agent_id=peer_id, trust_weight=0.6)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_agent_trust_network(agent_id)

        assert result[0].peer_agent_id == peer_id
        assert result[0].trust_weight == pytest.approx(0.6)


# ── get_top_collaborators() ───────────────────────────────────────────────────

class TestGetTopCollaborators:

    @pytest.mark.asyncio
    async def test_returns_collaborator_summaries(self):
        agent_id = uuid4()
        rows = [
            {
                "peer_agent_id": uuid4(),
                "trust_weight": 0.9,
                "interaction_count": 10,
                "last_interaction": datetime.now(UTC),
            }
            for _ in range(3)
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_top_collaborators(agent_id, limit=5)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_top_collaborators(agent_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_default_limit_is_5(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            await get_top_collaborators(agent_id)

        args = conn.fetch.await_args.args
        assert 5 in args

    @pytest.mark.asyncio
    async def test_limit_passed_through(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            await get_top_collaborators(agent_id, limit=3)

        args = conn.fetch.await_args.args
        assert 3 in args

    @pytest.mark.asyncio
    async def test_collaborator_has_trust_weight(self):
        agent_id = uuid4()
        row = {
            "peer_agent_id": uuid4(),
            "trust_weight": 0.77,
            "interaction_count": 4,
            "last_interaction": datetime.now(UTC),
        }
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_top_collaborators(agent_id)

        assert result[0].trust_weight == pytest.approx(0.77)


# ── get_graph_weight_for_agent() ──────────────────────────────────────────────

class TestGetGraphWeightForAgent:

    @pytest.mark.asyncio
    async def test_returns_average_weight(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0.45)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_graph_weight_for_agent(agent_id)

        assert result == pytest.approx(0.45)

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_edges(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_graph_weight_for_agent(agent_id)

        assert result == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_returns_float(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0.33)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_graph_weight_for_agent(agent_id)

        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_coalesce_zero_when_db_returns_zero(self):
        agent_id = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0.0)

        with patch("src.services.reputation_graph.get_db", return_value=_db_context(conn)):
            result = await get_graph_weight_for_agent(agent_id)

        assert result == pytest.approx(0.0)


# ── calculate_graph_enhanced_score() ─────────────────────────────────────────

class TestCalculateGraphEnhancedScore:

    def test_adds_graph_bonus(self):
        result = calculate_graph_enhanced_score(0.5, 1.0, graph_boost_factor=0.1)
        assert result == pytest.approx(0.6)

    def test_zero_graph_weight_returns_base(self):
        result = calculate_graph_enhanced_score(0.5, 0.0)
        assert result == pytest.approx(0.5)

    def test_clamped_to_one(self):
        result = calculate_graph_enhanced_score(0.95, 1.0, graph_boost_factor=0.1)
        assert result == pytest.approx(1.0)

    def test_clamped_to_zero(self):
        result = calculate_graph_enhanced_score(0.0, 0.0)
        assert result == pytest.approx(0.0)

    def test_partial_boost(self):
        result = calculate_graph_enhanced_score(0.5, 0.5, graph_boost_factor=0.1)
        assert result == pytest.approx(0.55)

    def test_boost_factor_respected(self):
        result = calculate_graph_enhanced_score(0.5, 1.0, graph_boost_factor=0.2)
        assert result == pytest.approx(0.7)

    def test_returns_float(self):
        result = calculate_graph_enhanced_score(0.4, 0.5)
        assert isinstance(result, float)

    def test_full_trust_full_base_clamped(self):
        result = calculate_graph_enhanced_score(1.0, 1.0)
        assert result == pytest.approx(1.0)

    def test_base_score_dominates_at_zero_graph(self):
        result = calculate_graph_enhanced_score(0.75, 0.0)
        assert result == pytest.approx(0.75)


# ── handle_task_completed() ───────────────────────────────────────────────────

class TestHandleTaskCompleted:

    @pytest.mark.asyncio
    async def test_records_bidirectional_interaction(self):
        creator = uuid4()
        executor = uuid4()

        with patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            await handle_task_completed("task-1", creator, executor)

        assert mock_record.await_count == 2

    @pytest.mark.asyncio
    async def test_resolves_did_for_creator(self):
        creator_did = "did:agentx:creator"
        executor = uuid4()
        resolved = uuid4()

        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(return_value=resolved),
        ), patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            await handle_task_completed("task-1", creator_did, executor)

        assert mock_record.await_count == 2

    @pytest.mark.asyncio
    async def test_does_nothing_when_creator_not_found(self):
        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(return_value=None),
        ), patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            await handle_task_completed("task-1", "did:agentx:missing", uuid4())

        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_nothing_when_same_agent(self):
        same = uuid4()

        with patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            await handle_task_completed("task-1", same, same)

        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_soft_fail_on_exception(self, caplog):
        creator = uuid4()
        executor = uuid4()

        with patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(side_effect=Exception("DB down")),
        ), caplog.at_level(logging.WARNING, logger="src.services.reputation_graph"):
            # Should NOT raise
            await handle_task_completed("task-1", creator, executor)

    @pytest.mark.asyncio
    async def test_uses_task_completed_weight(self):
        creator = uuid4()
        executor = uuid4()
        captured_weights = []

        async def _mock_record(a, b, w, itype):
            captured_weights.append(w)

        with patch(
            "src.services.reputation_graph.record_interaction",
            new=_mock_record,
        ):
            await handle_task_completed("task-1", creator, executor)

        assert all(w == pytest.approx(0.10) for w in captured_weights)


# ── handle_contract_completed() ───────────────────────────────────────────────

class TestHandleContractCompleted:

    @pytest.mark.asyncio
    async def test_records_bidirectional_interaction(self):
        creator_did = "did:agentx:creator"
        contractor_did = "did:agentx:contractor"
        resolved = uuid4()

        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(return_value=resolved),
        ), patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            # Both DIDs resolve to different UUIDs — we need two different ones
            ids = [uuid4(), uuid4()]
            call_count = 0

            async def resolve(did):
                nonlocal call_count
                val = ids[call_count % 2]
                call_count += 1
                return val

            with patch("src.services.reputation_graph._resolve_did_to_uuid", new=resolve):
                await handle_contract_completed("contract-1", creator_did, contractor_did)

        # Both directions recorded
        assert mock_record.await_count == 2

    @pytest.mark.asyncio
    async def test_uses_contract_completed_weight(self):
        creator_did = "did:agentx:creator"
        contractor_did = "did:agentx:contractor"
        ids = [uuid4(), uuid4()]
        captured_weights: list[float] = []
        call_count = 0

        async def resolve(did):
            nonlocal call_count
            val = ids[call_count % 2]
            call_count += 1
            return val

        async def capture(a, b, w, itype):
            captured_weights.append(w)

        with patch("src.services.reputation_graph._resolve_did_to_uuid", new=resolve), \
             patch("src.services.reputation_graph.record_interaction", new=capture):
            await handle_contract_completed("contract-1", creator_did, contractor_did)

        assert all(w == pytest.approx(0.12) for w in captured_weights)

    @pytest.mark.asyncio
    async def test_soft_fail_on_exception(self):
        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(side_effect=Exception("timeout")),
        ):
            # Must not raise
            await handle_contract_completed("contract-1", "did:x", "did:y")

    @pytest.mark.asyncio
    async def test_does_nothing_when_did_not_found(self):
        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(return_value=None),
        ), patch(
            "src.services.reputation_graph.record_interaction",
            new=AsyncMock(),
        ) as mock_record:
            await handle_contract_completed("contract-1", "did:missing", "did:also-missing")

        mock_record.assert_not_awaited()


# ── handle_verification_submitted() ──────────────────────────────────────────

class TestHandleVerificationSubmitted:

    @pytest.mark.asyncio
    async def test_records_bidirectional_interaction(self):
        ids = [uuid4(), uuid4()]
        call_count = 0

        async def resolve(did):
            nonlocal call_count
            val = ids[call_count % 2]
            call_count += 1
            return val

        with patch("src.services.reputation_graph._resolve_did_to_uuid", new=resolve), \
             patch("src.services.reputation_graph.record_interaction", new=AsyncMock()) as mock_record:
            await handle_verification_submitted("ver-1", "did:verifier", "did:subject")

        assert mock_record.await_count == 2

    @pytest.mark.asyncio
    async def test_uses_verification_submitted_weight(self):
        ids = [uuid4(), uuid4()]
        call_count = 0
        captured: list[float] = []

        async def resolve(did):
            nonlocal call_count
            val = ids[call_count % 2]
            call_count += 1
            return val

        async def capture(a, b, w, itype):
            captured.append(w)

        with patch("src.services.reputation_graph._resolve_did_to_uuid", new=resolve), \
             patch("src.services.reputation_graph.record_interaction", new=capture):
            await handle_verification_submitted("ver-1", "did:verifier", "did:subject")

        assert all(w == pytest.approx(0.08) for w in captured)

    @pytest.mark.asyncio
    async def test_soft_fail_on_exception(self):
        with patch(
            "src.services.reputation_graph._resolve_did_to_uuid",
            new=AsyncMock(side_effect=RuntimeError("network error")),
        ):
            await handle_verification_submitted("ver-1", "did:a", "did:b")  # must not raise

    @pytest.mark.asyncio
    async def test_does_nothing_when_subject_not_found(self):
        verifier_id = uuid4()
        call_count = 0

        async def resolve(did):
            nonlocal call_count
            call_count += 1
            return verifier_id if call_count == 1 else None

        with patch("src.services.reputation_graph._resolve_did_to_uuid", new=resolve), \
             patch("src.services.reputation_graph.record_interaction", new=AsyncMock()) as mock_record:
            await handle_verification_submitted("ver-1", "did:verifier", "did:missing")

        mock_record.assert_not_awaited()
