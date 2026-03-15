"""
Tests: simulation/trust_network_simulation.py
Phase 20 — Agent Reputation Graph

Covers:
  TrustEdge                    — apply_delta, clamping, repr
  TrustNetworkSimulation       — run_cycle, run, analytics
  TrustNetworkEngine           — build, run, summary, analytics delegation

Pure-Python, no mocking required.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from simulation.trust_network_simulation import (
    Alliance,
    Rivalry,
    TrustEdge,
    TrustNetworkEngine,
    TrustNetworkSimulation,
    TrustedTeam,
)


# ── TrustEdge ─────────────────────────────────────────────────────────────────

class TestTrustEdge:

    def test_initial_trust_weight_zero(self):
        e = TrustEdge("a", "b")
        assert e.trust_weight == 0.0

    def test_apply_delta_increases_weight(self):
        e = TrustEdge("a", "b")
        e.apply_delta(0.1)
        assert e.trust_weight == pytest.approx(0.1)

    def test_apply_delta_increments_count(self):
        e = TrustEdge("a", "b")
        e.apply_delta(0.1)
        e.apply_delta(0.1)
        assert e.interaction_count == 2

    def test_clamp_above_one(self):
        e = TrustEdge("a", "b", trust_weight=0.95)
        e.apply_delta(0.2)
        assert e.trust_weight == pytest.approx(1.0)

    def test_clamp_below_zero(self):
        e = TrustEdge("a", "b", trust_weight=0.0)
        e.apply_delta(-0.5)
        assert e.trust_weight == pytest.approx(0.0)

    def test_interaction_type_stored(self):
        e = TrustEdge("a", "b")
        e.apply_delta(0.05, "contract_completed")
        assert e.interaction_type == "contract_completed"

    def test_repr_contains_source_and_target(self):
        e = TrustEdge("agent_1", "agent_2")
        r = repr(e)
        assert "agent_1" in r
        assert "agent_2" in r

    def test_repr_contains_weight(self):
        e = TrustEdge("a", "b", trust_weight=0.75)
        assert "0.750" in repr(e)

    def test_negative_delta_decreases_weight(self):
        e = TrustEdge("a", "b", trust_weight=0.5)
        e.apply_delta(-0.1)
        assert e.trust_weight == pytest.approx(0.4)


# ── TrustNetworkSimulation ────────────────────────────────────────────────────

class TestTrustNetworkSimulation:

    def _sim(self, n=4, alliances=None, rivalries=None, teams=None):
        agents = [f"agent_{i}" for i in range(n)]
        return TrustNetworkSimulation(
            agent_ids=agents,
            alliances=alliances or [],
            rivalries=rivalries or [],
            trusted_teams=teams or [],
            cycle_interval=0.0,
        )

    @pytest.mark.asyncio
    async def test_initial_cycles_zero(self):
        sim = self._sim()
        assert sim.cycles_run == 0

    @pytest.mark.asyncio
    async def test_initial_interactions_zero(self):
        sim = self._sim()
        assert sim.total_interactions == 0

    @pytest.mark.asyncio
    async def test_run_cycle_increments_cycles(self):
        sim = self._sim()
        await sim.run_cycle()
        assert sim.cycles_run == 1

    @pytest.mark.asyncio
    async def test_run_cycle_returns_dict(self):
        sim = self._sim()
        result = await sim.run_cycle()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_run_cycle_result_has_cycle_key(self):
        sim = self._sim()
        result = await sim.run_cycle()
        assert "cycle" in result

    @pytest.mark.asyncio
    async def test_run_cycle_result_has_interactions_key(self):
        sim = self._sim()
        result = await sim.run_cycle()
        assert "interactions" in result

    @pytest.mark.asyncio
    async def test_run_cycle_result_has_edge_count(self):
        sim = self._sim()
        result = await sim.run_cycle()
        assert "edge_count" in result

    @pytest.mark.asyncio
    async def test_alliance_creates_edges(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1")],
            cycle_interval=0.0,
        )
        await sim.run_cycle()
        assert sim.get_edge("a0", "a1") is not None
        assert sim.get_edge("a1", "a0") is not None

    @pytest.mark.asyncio
    async def test_rivalry_creates_edges(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            rivalries=[("a0", "a1")],
            cycle_interval=0.0,
        )
        await sim.run_cycle()
        e = sim.get_edge("a0", "a1")
        assert e is not None
        assert e.interaction_type == "rivalry"

    @pytest.mark.asyncio
    async def test_trusted_team_creates_edges_for_all_pairs(self):
        agents = ["t0", "t1", "t2"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            trusted_teams=[agents],
            cycle_interval=0.0,
        )
        await sim.run_cycle()
        assert sim.get_edge("t0", "t1") is not None
        assert sim.get_edge("t1", "t0") is not None
        assert sim.get_edge("t0", "t2") is not None

    @pytest.mark.asyncio
    async def test_alliance_increases_trust_weight(self):
        agents = ["a", "b", "c", "d"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a", "b")],
            cycle_interval=0.0,
        )
        await sim.run_cycle()
        await sim.run_cycle()
        e = sim.get_edge("a", "b")
        assert e.trust_weight > 0.0

    @pytest.mark.asyncio
    async def test_get_edge_returns_none_when_no_interaction(self):
        sim = self._sim()
        # Before any cycles, edges may not exist
        assert sim.get_edge("agent_0", "agent_99") is None

    @pytest.mark.asyncio
    async def test_run_cycles_multiple(self):
        sim = self._sim(alliances=[("agent_0", "agent_1")])
        await sim.run(cycles=5)
        assert sim.cycles_run == 5

    @pytest.mark.asyncio
    async def test_is_running_false_after_run(self):
        sim = self._sim()
        await sim.run(cycles=2)
        assert not sim.is_running

    @pytest.mark.asyncio
    async def test_all_edges_returns_list(self):
        sim = self._sim(alliances=[("agent_0", "agent_1")])
        await sim.run_cycle()
        edges = sim.all_edges()
        assert isinstance(edges, list)

    @pytest.mark.asyncio
    async def test_total_interactions_increases(self):
        sim = self._sim(alliances=[("agent_0", "agent_1")])
        before = sim.total_interactions
        await sim.run_cycle()
        assert sim.total_interactions > before

    @pytest.mark.asyncio
    async def test_summary_keys_present(self):
        sim = self._sim()
        await sim.run(cycles=2)
        s = sim.summary()
        for key in ("cycles_run", "total_interactions", "edge_count",
                    "agent_count", "avg_trust", "max_trust", "min_trust"):
            assert key in s

    @pytest.mark.asyncio
    async def test_summary_edge_count_matches(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1")],
            cycle_interval=0.0,
        )
        await sim.run_cycle()
        s = sim.summary()
        assert s["edge_count"] == len(sim.all_edges())


# ── TrustNetworkSimulation analytics ─────────────────────────────────────────

class TestTrustNetworkSimulationAnalytics:

    @pytest.mark.asyncio
    async def test_detect_alliances_returns_list(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1")],
            cycle_interval=0.0,
        )
        # Run many cycles to build up trust > 0.3 threshold
        await sim.run(cycles=5)
        result = sim.detect_alliances(threshold=0.0)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_detect_alliances_includes_high_trust_pair(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1")],
            cycle_interval=0.0,
        )
        await sim.run(cycles=10)
        alliances = sim.detect_alliances(threshold=0.1)
        pairs = [(a.agent_a, a.agent_b) for a in alliances]
        assert ("a0", "a1") in pairs or ("a1", "a0") in pairs

    @pytest.mark.asyncio
    async def test_detect_rivalries_returns_list(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            rivalries=[("a0", "a1")],
            cycle_interval=0.0,
        )
        await sim.run(cycles=2)
        rivalries = sim.detect_rivalries()
        assert isinstance(rivalries, list)

    @pytest.mark.asyncio
    async def test_detect_trusted_teams_returns_list(self):
        agents = ["t0", "t1", "t2", "t3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            trusted_teams=[["t0", "t1", "t2"]],
            cycle_interval=0.0,
        )
        await sim.run(cycles=5)
        teams = sim.detect_trusted_teams(min_trust=0.0)
        assert isinstance(teams, list)

    @pytest.mark.asyncio
    async def test_top_trusted_pairs_returns_at_most_n(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1"), ("a1", "a2"), ("a2", "a3")],
            cycle_interval=0.0,
        )
        await sim.run(cycles=5)
        top = sim.top_trusted_pairs(n=2)
        assert len(top) <= 2

    @pytest.mark.asyncio
    async def test_top_trusted_pairs_sorted_desc(self):
        agents = ["a0", "a1", "a2", "a3"]
        sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=[("a0", "a1"), ("a2", "a3")],
            cycle_interval=0.0,
        )
        await sim.run(cycles=3)
        top = sim.top_trusted_pairs(n=10)
        weights = [e.trust_weight for e in top]
        assert weights == sorted(weights, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_sim_detect_alliances_empty(self):
        sim = TrustNetworkSimulation(agent_ids=[])
        result = sim.detect_alliances()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_sim_detect_rivalries_empty(self):
        sim = TrustNetworkSimulation(agent_ids=[])
        result = sim.detect_rivalries()
        assert result == []


# ── TrustNetworkEngine ────────────────────────────────────────────────────────

class TestTrustNetworkEngine:

    def test_default_num_agents(self):
        engine = TrustNetworkEngine(num_agents=8)
        assert engine.num_agents == 8

    def test_is_not_running_before_start(self):
        engine = TrustNetworkEngine()
        assert not engine.is_running

    def test_simulation_none_before_run(self):
        engine = TrustNetworkEngine()
        assert engine.simulation is None

    def test_summary_before_run(self):
        engine = TrustNetworkEngine(num_agents=5)
        s = engine.summary()
        assert s["cycles_run"] == 0
        assert s["edge_count"] == 0
        assert not s["is_running"]

    @pytest.mark.asyncio
    async def test_run_creates_simulation(self):
        engine = TrustNetworkEngine(num_agents=4, seed=42)
        await engine.run(cycles=1)
        assert engine.simulation is not None

    @pytest.mark.asyncio
    async def test_run_completes_cycles(self):
        engine = TrustNetworkEngine(num_agents=4, seed=42)
        await engine.run(cycles=3)
        assert engine.simulation.cycles_run == 3

    @pytest.mark.asyncio
    async def test_is_running_false_after_run(self):
        engine = TrustNetworkEngine(num_agents=3, seed=1)
        await engine.run(cycles=2)
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_summary_after_run_has_cycles(self):
        engine = TrustNetworkEngine(num_agents=4, seed=7)
        await engine.run(cycles=2)
        s = engine.summary()
        assert s["cycles_run"] == 2

    @pytest.mark.asyncio
    async def test_summary_has_agent_count(self):
        engine = TrustNetworkEngine(num_agents=6, seed=7)
        await engine.run(cycles=1)
        s = engine.summary()
        assert s["agent_count"] == 6

    @pytest.mark.asyncio
    async def test_detected_alliances_returns_list(self):
        engine = TrustNetworkEngine(num_agents=6, seed=42)
        await engine.run(cycles=5)
        alliances = engine.detected_alliances(threshold=0.0)
        assert isinstance(alliances, list)

    @pytest.mark.asyncio
    async def test_detected_rivalries_returns_list(self):
        engine = TrustNetworkEngine(num_agents=6, seed=42)
        await engine.run(cycles=5)
        rivalries = engine.detected_rivalries()
        assert isinstance(rivalries, list)

    @pytest.mark.asyncio
    async def test_detected_teams_returns_list(self):
        engine = TrustNetworkEngine(num_agents=9, team_size=3, seed=42)
        await engine.run(cycles=5)
        teams = engine.detected_teams(min_trust=0.0)
        assert isinstance(teams, list)

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        engine = TrustNetworkEngine(num_agents=3)
        await engine.stop()  # must not raise
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_background_task_can_be_stopped(self):
        engine = TrustNetworkEngine(num_agents=4, cycle_interval=100.0, seed=1)
        await engine.start_background(cycles=50)
        await asyncio.sleep(0)  # let task start
        await engine.stop()
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_single_agent_no_alliances(self):
        engine = TrustNetworkEngine(num_agents=1, seed=99)
        await engine.run(cycles=2)
        # With 1 agent there are no possible interactions
        assert engine.simulation.total_interactions == 0

    @pytest.mark.asyncio
    async def test_zero_agents_runs_without_error(self):
        engine = TrustNetworkEngine(num_agents=0, seed=0)
        await engine.run(cycles=2)
        s = engine.summary()
        assert s["agent_count"] == 0

    @pytest.mark.asyncio
    async def test_engine_uses_seed_for_reproducibility(self):
        engine_a = TrustNetworkEngine(num_agents=6, seed=123)
        engine_b = TrustNetworkEngine(num_agents=6, seed=123)
        await engine_a.run(cycles=3)
        await engine_b.run(cycles=3)
        # Both engines have the same structure
        assert engine_a.summary()["edge_count"] == engine_b.summary()["edge_count"]

    @pytest.mark.asyncio
    async def test_detected_alliances_none_before_run(self):
        engine = TrustNetworkEngine()
        alliances = engine.detected_alliances()
        assert alliances == []

    @pytest.mark.asyncio
    async def test_detected_rivalries_none_before_run(self):
        engine = TrustNetworkEngine()
        rivalries = engine.detected_rivalries()
        assert rivalries == []

    @pytest.mark.asyncio
    async def test_detected_teams_none_before_run(self):
        engine = TrustNetworkEngine()
        teams = engine.detected_teams()
        assert teams == []
