"""
Tests: simulation/economic_simulation.py
Phase 19 — Autonomous Agent Economies

Covers:
  StrategyAgent              — wrapper with strategy attribute
  EconomicSimulation         — strategy-aware market loop
  EconomicSimulationEngine   — full orchestrator

All SDK calls are mocked; no real runtimes started.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simulation.economic_simulation import (
    AgentStrategy,
    EconomicSimulation,
    EconomicSimulationEngine,
    StrategyAgent,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_agent(name="sim_agent_1", capabilities=None):
    """Create a minimal Agent-like mock."""
    agent = MagicMock()
    agent.name = name
    agent.capabilities = capabilities or ["forecast"]
    agent.did = None
    return agent


def _make_strategy_agent(name="sim_agent_1", caps=None, strategy=AgentStrategy.specialist):
    raw = _make_agent(name, caps or ["forecast"])
    return StrategyAgent(agent=raw, strategy=strategy)


def _markets_client():
    client = MagicMock()
    client.create_bounty   = AsyncMock(return_value={"bounty_id": "bounty-1"})
    client.submit_solution = AsyncMock(return_value={"submission_id": "sub-1"})
    client.distribute_rewards = AsyncMock(return_value={"reward_id": "rew-1"})
    return client


# ── StrategyAgent ─────────────────────────────────────────────────────────────

class TestStrategyAgent:

    def test_name_delegates_to_agent(self):
        sa = _make_strategy_agent(name="sa_test")
        assert sa.name == "sa_test"

    def test_capabilities_returns_list(self):
        sa = _make_strategy_agent(caps=["forecast", "research"])
        assert "forecast" in sa.capabilities

    def test_strategy_stored(self):
        sa = _make_strategy_agent(strategy=AgentStrategy.coordinator)
        assert sa.strategy == AgentStrategy.coordinator

    def test_repr_contains_strategy(self):
        sa = _make_strategy_agent(strategy=AgentStrategy.validator)
        assert "validator" in repr(sa)

    def test_did_delegates_to_agent(self):
        sa = _make_strategy_agent()
        sa.agent.did = "did:agentx:test"
        assert sa.did == "did:agentx:test"


# ── EconomicSimulation ────────────────────────────────────────────────────────

class TestEconomicSimulation:

    def _sim(self, strategy_agents=None, cycle_interval=0.01):
        agents = strategy_agents or [
            _make_strategy_agent(strategy=AgentStrategy.coordinator),
            _make_strategy_agent("sim_agent_2", strategy=AgentStrategy.specialist),
        ]
        return EconomicSimulation(
            markets_client=_markets_client(),
            strategy_agents=agents,
            cycle_interval=cycle_interval,
        )

    def test_initial_state(self):
        sim = self._sim()
        assert sim.cycles_run == 0
        assert sim.bounties_created == 0
        assert sim.rewards_distributed == 0
        assert not sim.is_running

    @pytest.mark.asyncio
    async def test_run_cycle_returns_dict(self):
        sim = self._sim()
        result = await sim.run_cycle()
        assert isinstance(result, dict)
        assert "bounties_created" in result

    @pytest.mark.asyncio
    async def test_coordinator_creates_bounty(self):
        mc = _markets_client()
        coord = _make_strategy_agent(strategy=AgentStrategy.coordinator, caps=["forecast"])
        sim = EconomicSimulation(
            markets_client=mc,
            strategy_agents=[coord],
            cycle_interval=0.01,
        )
        result = await sim.run_cycle()
        assert result["bounties_created"] >= 1
        mc.create_bounty.assert_called_once()

    @pytest.mark.asyncio
    async def test_specialist_submits_solution(self):
        mc = _markets_client()
        coord = _make_strategy_agent(
            "coord", caps=["forecast"], strategy=AgentStrategy.coordinator
        )
        spec = _make_strategy_agent(
            "spec", caps=["forecast"], strategy=AgentStrategy.specialist
        )
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[coord, spec], cycle_interval=0.01
        )
        await sim.run_cycle()
        mc.submit_solution.assert_called()

    @pytest.mark.asyncio
    async def test_no_coordinator_no_bounty_created(self):
        mc = _markets_client()
        spec = _make_strategy_agent(strategy=AgentStrategy.specialist)
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[spec], cycle_interval=0.01
        )
        result = await sim.run_cycle()
        assert result["bounties_created"] == 0
        mc.create_bounty.assert_not_called()

    @pytest.mark.asyncio
    async def test_rewards_distributed_on_submission(self):
        mc = _markets_client()
        coord = _make_strategy_agent(
            "coord", caps=["forecast"], strategy=AgentStrategy.coordinator
        )
        spec = _make_strategy_agent(
            "spec", caps=["forecast"], strategy=AgentStrategy.specialist
        )
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[coord, spec], cycle_interval=0.01
        )
        await sim.run_cycle()
        mc.distribute_rewards.assert_called()

    @pytest.mark.asyncio
    async def test_bounty_creation_error_swallowed(self):
        mc = _markets_client()
        mc.create_bounty = AsyncMock(side_effect=Exception("API error"))
        coord = _make_strategy_agent(strategy=AgentStrategy.coordinator, caps=["forecast"])
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[coord], cycle_interval=0.01
        )
        result = await sim.run_cycle()
        assert result["errors"] >= 1

    @pytest.mark.asyncio
    async def test_run_loop_cancellation(self):
        """EconomicSimulation.run() respects asyncio cancellation."""
        mc = _markets_client()
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[], cycle_interval=100.0
        )

        task = asyncio.create_task(sim.run())
        await asyncio.sleep(0)  # let it start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not sim.is_running

    @pytest.mark.asyncio
    async def test_empty_agents_cycle_returns_zero_bounties(self):
        mc = _markets_client()
        sim = EconomicSimulation(markets_client=mc, strategy_agents=[])
        result = await sim.run_cycle()
        assert result["bounties_created"] == 0

    @pytest.mark.asyncio
    async def test_generalist_submits_even_without_matching_cap(self):
        """Generalist agents submit solutions regardless of capability match."""
        mc = _markets_client()
        coord = _make_strategy_agent(
            "coord", caps=["forecast"], strategy=AgentStrategy.coordinator
        )
        gen = _make_strategy_agent(
            "gen", caps=["analysis"],  # different cap
            strategy=AgentStrategy.generalist,
        )
        sim = EconomicSimulation(
            markets_client=mc, strategy_agents=[coord, gen], cycle_interval=0.01
        )
        await sim.run_cycle()
        # Generalist should also submit
        mc.submit_solution.assert_called()


# ── EconomicSimulationEngine ──────────────────────────────────────────────────

class TestEconomicSimulationEngine:

    def test_default_num_agents(self):
        engine = EconomicSimulationEngine(num_agents=5)
        assert engine.num_agents == 5

    def test_is_not_running_before_start(self):
        engine = EconomicSimulationEngine()
        assert not engine.is_running

    def test_agent_count_zero_before_start(self):
        engine = EconomicSimulationEngine()
        assert engine.agent_count() == 0

    def test_task_count_zero_before_start(self):
        engine = EconomicSimulationEngine()
        assert engine.task_count() == 0

    def test_summary_before_start(self):
        engine = EconomicSimulationEngine(num_agents=3)
        s = engine.summary()
        assert s["num_agents"] == 0  # agents not yet created
        assert not s["is_running"]

    @pytest.mark.asyncio
    async def test_start_creates_strategy_agents(self):
        engine = EconomicSimulationEngine(num_agents=4)

        # Mock all async calls to return immediately
        with patch("simulation.economic_simulation.run_agent", new=AsyncMock(return_value=None)):
            with patch.object(
                EconomicSimulation, "run", new=AsyncMock(return_value=None)
            ):
                await engine.start()

        assert engine.agent_count() == 4

    @pytest.mark.asyncio
    async def test_start_assigns_strategies(self):
        engine = EconomicSimulationEngine(num_agents=3)

        with patch("simulation.economic_simulation.run_agent", new=AsyncMock(return_value=None)):
            with patch.object(
                EconomicSimulation, "run", new=AsyncMock(return_value=None)
            ):
                await engine.start()

        for sa in engine.strategy_agents:
            assert isinstance(sa.strategy, AgentStrategy)

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        engine = EconomicSimulationEngine(num_agents=2)

        with patch("simulation.economic_simulation.run_agent", new=AsyncMock(return_value=None)):
            with patch.object(
                EconomicSimulation, "run", new=AsyncMock(return_value=None)
            ):
                await engine.start()

        await engine.stop()
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_start_spawns_tasks_for_all_agents(self):
        engine = EconomicSimulationEngine(num_agents=3)

        with patch("simulation.economic_simulation.run_agent", new=AsyncMock(return_value=None)):
            with patch.object(
                EconomicSimulation, "run", new=AsyncMock(return_value=None)
            ):
                await engine.start()

        # N agent tasks + 1 economy task
        assert engine.task_count() == 4  # 3 + 1

    @pytest.mark.asyncio
    async def test_active_task_count_zero_after_completion(self):
        engine = EconomicSimulationEngine(num_agents=2)

        with patch("simulation.economic_simulation.run_agent", new=AsyncMock(return_value=None)):
            with patch.object(
                EconomicSimulation, "run", new=AsyncMock(return_value=None)
            ):
                await engine.start()

        assert engine.active_task_count() == 0


# ── CLI tests: simulate --economy flag ────────────────────────────────────────

class TestSimulateEconomyFlag:

    def test_economy_flag_invokes_economic_engine(self):
        from unittest.mock import MagicMock, patch, AsyncMock
        from typer.testing import CliRunner
        from agentx_cli.main import app

        runner = CliRunner()
        eng = MagicMock()
        eng.start = AsyncMock(return_value=None)

        with patch("agentx_cli.simulate_cmd.EconomicSimulationEngine", return_value=eng) as MockEco:
            with patch("agentx_cli.simulate_cmd.load_config", side_effect=FileNotFoundError):
                result = runner.invoke(app, ["simulate", "--agents", "3", "--economy"])

        assert result.exit_code == 0
        MockEco.assert_called_once()
        kwargs = MockEco.call_args[1]
        assert kwargs["num_agents"] == 3

    def test_no_economy_flag_uses_standard_engine(self):
        from unittest.mock import MagicMock, patch, AsyncMock
        from typer.testing import CliRunner
        from agentx_cli.main import app

        runner = CliRunner()
        eng = MagicMock()
        eng.start = AsyncMock(return_value=None)

        with patch("agentx_cli.simulate_cmd.SimulationEngine", return_value=eng) as MockSim:
            with patch("agentx_cli.simulate_cmd.load_config", side_effect=FileNotFoundError):
                result = runner.invoke(app, ["simulate", "--agents", "3"])

        assert result.exit_code == 0
        MockSim.assert_called_once()

    def test_economy_dry_run_shows_strategies(self):
        from typer.testing import CliRunner
        from agentx_cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["simulate", "--agents", "3", "--dry-run"])
        assert result.exit_code == 0
        assert "sim_agent_1" in result.output
