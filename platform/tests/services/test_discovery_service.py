"""
Tests: discovery_service (Phase 16)
════════════════════════════════════════════════════════════════════════════════
Covers:
  calculate_agent_score    — pure ranking formula
  register_capability      — upserts to agent_capabilities_registry
  get_agent_capabilities   — lists capabilities for an agent
  list_agents_by_capability — capability-filtered ranked list
  search_agents_semantic   — ILIKE-based semantic search
  get_top_agents           — global ranking query
  get_agent_metrics        — fetch stored metrics
  update_agent_metrics     — recompute and upsert metrics
  discovery_consumer       — event handler dispatches update_agent_metrics

All DB and event calls are mocked; no live DB/Redis required.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import discovery_service


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mk_row(**kwargs):
    """Create a dict-backed asyncpg-row mock."""
    data = {
        "agent_id":             uuid4(),
        "agent_did":            "did:agentx:test",
        "name":                 "Test Agent",
        "trust_score":          0.7,
        "capabilities":         "collect_data,analyse_data",
        "contracts_completed":  10,
        "contracts_failed":     1,
        "verification_success": 0.8,
        "bounties_won":         2,
        "last_active":          None,
        **kwargs,
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _mk_cap_row(agent_id=None, capability="collect_data", confidence=0.9):
    data = {
        "registry_id": uuid4(),
        "agent_id":    agent_id or uuid4(),
        "capability":  capability,
        "confidence":  confidence,
        "created_at":  "2026-01-01T00:00:00Z",
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


def _mk_metrics_row(agent_id=None):
    data = {
        "agent_id":             agent_id or uuid4(),
        "contracts_completed":  5,
        "contracts_failed":     0,
        "verification_success": 0.9,
        "bounties_won":         1,
        "last_active":          "2026-01-01T00:00:00Z",
    }
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=data.__getitem__)
    row.get = MagicMock(side_effect=data.get)
    return row


@asynccontextmanager
async def _fake_tx(conn):
    yield conn


@asynccontextmanager
async def _fake_db(conn):
    yield conn


# ═════════════════════════════════════════════════════════════════════════════
# calculate_agent_score — pure function
# ═════════════════════════════════════════════════════════════════════════════

class TestCalculateAgentScore:

    def test_all_zeros_returns_zero(self):
        score = discovery_service.calculate_agent_score(0.0, 0, 0.0, 0)
        assert score == pytest.approx(0.0)

    def test_full_trust_only(self):
        score = discovery_service.calculate_agent_score(1.0, 0, 0.0, 0)
        assert score == pytest.approx(0.4)

    def test_full_completion_only(self):
        # 100 completed → normalized to 1.0 → weight 0.2
        score = discovery_service.calculate_agent_score(0.0, 100, 0.0, 0)
        assert score == pytest.approx(0.2)

    def test_full_verification_only(self):
        score = discovery_service.calculate_agent_score(0.0, 0, 1.0, 0)
        assert score == pytest.approx(0.2)

    def test_full_bounties_only(self):
        # 10 bounties → normalized to 1.0 → weight 0.2
        score = discovery_service.calculate_agent_score(0.0, 0, 0.0, 10)
        assert score == pytest.approx(0.2)

    def test_perfect_agent_scores_one(self):
        score = discovery_service.calculate_agent_score(1.0, 100, 1.0, 10)
        assert score == pytest.approx(1.0)

    def test_contracts_capped_at_100(self):
        # 200 completed same as 100
        s100 = discovery_service.calculate_agent_score(0.0, 100, 0.0, 0)
        s200 = discovery_service.calculate_agent_score(0.0, 200, 0.0, 0)
        assert s100 == pytest.approx(s200)

    def test_bounties_capped_at_10(self):
        s10 = discovery_service.calculate_agent_score(0.0, 0, 0.0, 10)
        s20 = discovery_service.calculate_agent_score(0.0, 0, 0.0, 20)
        assert s10 == pytest.approx(s20)

    def test_typical_agent(self):
        # trust=0.7, 10 completed, ver=0.8, 2 bounties
        score = discovery_service.calculate_agent_score(0.7, 10, 0.8, 2)
        expected = 0.7 * 0.4 + 0.1 * 0.2 + 0.8 * 0.2 + 0.2 * 0.2
        assert score == pytest.approx(expected)

    def test_score_in_range(self):
        for trust in [0.0, 0.5, 1.0]:
            for contracts in [0, 50, 100]:
                score = discovery_service.calculate_agent_score(trust, contracts, 0.5, 5)
                assert 0.0 <= score <= 1.0


# ═════════════════════════════════════════════════════════════════════════════
# register_capability
# ═════════════════════════════════════════════════════════════════════════════

class TestRegisterCapability:

    @pytest.mark.asyncio
    async def test_register_returns_capability(self):
        aid = uuid4()
        cap_row = _mk_cap_row(agent_id=aid)
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)   # agent exists
        conn.fetchrow = AsyncMock(return_value=cap_row)

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            result = await discovery_service.register_capability(aid, "collect_data", 0.9)

        assert result.capability == "collect_data"
        assert result.confidence == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_register_raises_when_agent_not_found(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # agent missing

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            with pytest.raises(ValueError, match="Agent not found"):
                await discovery_service.register_capability(uuid4(), "x", 1.0)

    @pytest.mark.asyncio
    async def test_register_uses_default_confidence(self):
        aid = uuid4()
        cap_row = _mk_cap_row(agent_id=aid, confidence=1.0)
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetchrow = AsyncMock(return_value=cap_row)

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            result = await discovery_service.register_capability(aid, "analyse_data")

        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_register_calls_upsert(self):
        aid = uuid4()
        cap_row = _mk_cap_row(agent_id=aid)
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetchrow = AsyncMock(return_value=cap_row)

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            await discovery_service.register_capability(aid, "skill_x", 0.5)

        # fetchrow should have been called with INSERT ... ON CONFLICT
        assert conn.fetchrow.called
        sql = conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql


# ═════════════════════════════════════════════════════════════════════════════
# get_agent_capabilities
# ═════════════════════════════════════════════════════════════════════════════

class TestGetAgentCapabilities:

    @pytest.mark.asyncio
    async def test_returns_list(self):
        aid = uuid4()
        rows = [_mk_cap_row(agent_id=aid), _mk_cap_row(agent_id=aid, capability="x")]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_agent_capabilities(aid)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_agent_capabilities(uuid4())

        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# list_agents_by_capability
# ═════════════════════════════════════════════════════════════════════════════

class TestListAgentsByCapability:

    @pytest.mark.asyncio
    async def test_returns_agents(self):
        rows = [_mk_row(), _mk_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.list_agents_by_capability("collect_data")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_passes_capability_to_query(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            await discovery_service.list_agents_by_capability("analyse_data", limit=5)

        args = conn.fetch.call_args[0]
        assert "analyse_data" in args
        assert 5 in args

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.list_agents_by_capability("unknown_cap")

        assert result == []

    @pytest.mark.asyncio
    async def test_computes_scores(self):
        row = _mk_row(trust_score=0.8, contracts_completed=20,
                      verification_success=0.9, bounties_won=3)
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.list_agents_by_capability("collect_data")

        assert result[0].score > 0.0
        assert result[0].trust_score == pytest.approx(0.8)


# ═════════════════════════════════════════════════════════════════════════════
# search_agents_semantic
# ═════════════════════════════════════════════════════════════════════════════

class TestSearchAgentsSemantic:

    @pytest.mark.asyncio
    async def test_returns_agents(self):
        rows = [_mk_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.search_agents_semantic("data")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_passes_ilike_pattern(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            await discovery_service.search_agents_semantic("collect", limit=3)

        args = conn.fetch.call_args[0]
        # Pattern should be %collect%
        assert "%collect%" in args

    @pytest.mark.asyncio
    async def test_passes_limit(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            await discovery_service.search_agents_semantic("data", limit=7)

        args = conn.fetch.call_args[0]
        assert 7 in args

    @pytest.mark.asyncio
    async def test_query_is_lowercased(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            await discovery_service.search_agents_semantic("ANALYSE Data")

        args = conn.fetch.call_args[0]
        assert "%analyse data%" in args

    @pytest.mark.asyncio
    async def test_empty_returns_empty(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.search_agents_semantic("nonexistent")

        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# get_top_agents
# ═════════════════════════════════════════════════════════════════════════════

class TestGetTopAgents:

    @pytest.mark.asyncio
    async def test_returns_agents(self):
        rows = [_mk_row(), _mk_row(), _mk_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_top_agents(limit=3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_passes_limit(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            await discovery_service.get_top_agents(limit=5)

        args = conn.fetch.call_args[0]
        assert 5 in args

    @pytest.mark.asyncio
    async def test_scores_are_computed(self):
        rows = [
            _mk_row(trust_score=0.9, contracts_completed=50,
                    verification_success=0.95, bounties_won=5),
            _mk_row(trust_score=0.3, contracts_completed=2,
                    verification_success=0.1, bounties_won=0),
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_top_agents()

        assert result[0].score > result[1].score

    @pytest.mark.asyncio
    async def test_empty_returns_empty(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_top_agents()

        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# get_agent_metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestGetAgentMetrics:

    @pytest.mark.asyncio
    async def test_returns_metrics(self):
        aid = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)   # agent exists
        conn.fetchrow = AsyncMock(return_value=_mk_metrics_row(agent_id=aid))

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_agent_metrics(aid)

        assert result.agent_id == aid
        assert result.contracts_completed == 5
        assert result.bounties_won == 1

    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_metrics_row(self):
        aid = uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)   # agent exists
        conn.fetchrow = AsyncMock(return_value=None)  # no metrics row

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            result = await discovery_service.get_agent_metrics(aid)

        assert result.agent_id == aid
        assert result.contracts_completed == 0

    @pytest.mark.asyncio
    async def test_raises_when_agent_not_found(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # agent missing

        with patch("src.services.discovery_service.get_db", lambda: _fake_db(conn)):
            with pytest.raises(ValueError, match="Agent not found"):
                await discovery_service.get_agent_metrics(uuid4())


# ═════════════════════════════════════════════════════════════════════════════
# update_agent_metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdateAgentMetrics:

    def _ver_row(self, approved=5, total=6):
        data = {"approved": approved, "total": total}
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        row.get = MagicMock(side_effect=data.get)
        return row

    @pytest.mark.asyncio
    async def test_update_returns_metrics(self):
        aid = uuid4()
        metrics_row = _mk_metrics_row(agent_id=aid)
        conn = AsyncMock()
        conn.fetchval.side_effect = [10, 1, 3]  # completed, failed, bounties
        conn.fetchrow.side_effect = [self._ver_row(5, 6), metrics_row]

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            result = await discovery_service.update_agent_metrics(aid)

        assert result.agent_id == aid

    @pytest.mark.asyncio
    async def test_update_computes_ver_success_rate(self):
        aid = uuid4()
        metrics_row = _mk_metrics_row(agent_id=aid)
        conn = AsyncMock()
        conn.fetchval.side_effect = [10, 0, 2]
        conn.fetchrow.side_effect = [self._ver_row(approved=8, total=10), metrics_row]

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            await discovery_service.update_agent_metrics(aid)

        # The upsert should have been called with ver_success ≈ 0.8
        upsert_call = conn.fetchrow.call_args_list[-1]
        args = upsert_call[0]
        # 5th positional param is ver_success (after agent_id, completed, failed, ver, bounties)
        assert args[4] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_update_soft_fails_on_exception(self):
        aid = uuid4()
        conn = AsyncMock()
        conn.fetchval.side_effect = RuntimeError("DB error")

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            # Should not raise — soft fail
            result = await discovery_service.update_agent_metrics(aid)

        assert result.agent_id == aid
        assert result.contracts_completed == 0

    @pytest.mark.asyncio
    async def test_update_handles_zero_verifications(self):
        aid = uuid4()
        metrics_row = _mk_metrics_row(agent_id=aid)
        ver_row = self._ver_row(approved=0, total=0)
        conn = AsyncMock()
        conn.fetchval.side_effect = [0, 0, 0]
        conn.fetchrow.side_effect = [ver_row, metrics_row]

        with patch("src.services.discovery_service.transaction", lambda: _fake_tx(conn)):
            result = await discovery_service.update_agent_metrics(aid)

        # ver_success should be 0.0 when total=0
        upsert_call = conn.fetchrow.call_args_list[-1]
        args = upsert_call[0]
        assert args[4] == pytest.approx(0.0)


# ═════════════════════════════════════════════════════════════════════════════
# discovery_consumer
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscoveryConsumer:

    @pytest.mark.asyncio
    async def test_handle_task_completed(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        aid = uuid4()
        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"agent_id": str(aid)},
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_called_once_with(aid)

    @pytest.mark.asyncio
    async def test_handle_contract_completed(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        aid = uuid4()
        event = AgentXEvent(
            event_type=EventType.CONTRACT_COMPLETED,
            payload={"assigned_agent_id": str(aid)},
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_called_once_with(aid)

    @pytest.mark.asyncio
    async def test_handle_bounty_reward(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        aid = uuid4()
        event = AgentXEvent(
            event_type=EventType.BOUNTY_REWARD_DISTRIBUTED,
            payload={"recipient_id": str(aid)},
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_called_once_with(aid)

    @pytest.mark.asyncio
    async def test_handle_contract_verified(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        aid = uuid4()
        event = AgentXEvent(
            event_type=EventType.CONTRACT_VERIFIED,
            payload={"agent_id": str(aid)},
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_called_once_with(aid)

    @pytest.mark.asyncio
    async def test_handle_missing_agent_id_is_skipped(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={},   # no agent_id
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_unhandled_event_type_is_ignored(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        event = AgentXEvent(
            event_type=EventType.TOKEN_TRANSFER,
            payload={"agent_id": str(uuid4())},
        )

        update_mock = AsyncMock()
        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = update_mock
            await discovery_consumer.handle(event)

        update_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_swallows_exception(self):
        from src.events.types import AgentXEvent, EventType
        from src.services.consumers import discovery_consumer

        event = AgentXEvent(
            event_type=EventType.TASK_COMPLETED,
            payload={"agent_id": str(uuid4())},
        )

        with patch("src.services.consumers.discovery_consumer.discovery_service") as svc:
            svc.update_agent_metrics = AsyncMock(side_effect=RuntimeError("DB down"))
            # Should NOT raise
            await discovery_consumer.handle(event)


# ═════════════════════════════════════════════════════════════════════════════
# _row_to_discovery edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestRowToDiscovery:

    def test_empty_capabilities_string(self):
        row = _mk_row(capabilities="")
        result = discovery_service._row_to_discovery(row)
        assert result.capabilities == []

    def test_single_capability(self):
        row = _mk_row(capabilities="collect_data")
        result = discovery_service._row_to_discovery(row)
        assert result.capabilities == ["collect_data"]

    def test_multiple_capabilities(self):
        row = _mk_row(capabilities="a,b,c")
        result = discovery_service._row_to_discovery(row)
        assert set(result.capabilities) == {"a", "b", "c"}

    def test_none_capabilities(self):
        row = _mk_row(capabilities=None)
        result = discovery_service._row_to_discovery(row)
        assert result.capabilities == []

    def test_score_computed_from_fields(self):
        row = _mk_row(
            trust_score=1.0, contracts_completed=100,
            verification_success=1.0, bounties_won=10,
        )
        result = discovery_service._row_to_discovery(row)
        assert result.score == pytest.approx(1.0)

    def test_name_falls_back_to_did(self):
        row = _mk_row(name=None)
        result = discovery_service._row_to_discovery(row)
        assert result.name == row.get("agent_did")
