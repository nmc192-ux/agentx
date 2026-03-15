"""
Tests: simulation/simulation_engine.py
         simulation/agent_runner.py
         simulation/market_simulation.py
Phase 18 — Multi-Agent Local Simulation

All SDK calls are mocked; no real runtimes are started.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

import pytest

from agentx_sdk import Agent
from simulation.agent_factory import create_agent, create_agents
from simulation.market_simulation import MarketSimulation, BOUNTY_TITLES, MIN_REWARD, MAX_REWARD
from simulation.simulation_engine import SimulationEngine

NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_agent(name: str = "sim_agent_1", caps: list[str] | None = None) -> Agent:
    return create_agent(1, capabilities=caps or ["forecast"])


def _make_markets_client(
    bounty_id: str | None = None,
) -> MagicMock:
    mc = MagicMock()
    mc.create_bounty      = AsyncMock(return_value={"bounty_id": bounty_id or str(uuid4())})
    mc.submit_solution    = AsyncMock(return_value={"submission_id": str(uuid4())})
    mc.distribute_rewards = AsyncMock(return_value={"rewarded": True})
    mc.list_bounties      = AsyncMock(return_value=[])
    return mc


# ─────────────────────────────────────────────────────────────────────────────
# agent_runner.run_agent
# ─────────────────────────────────────────────────────────────────────────────

class TestRunAgent:

    @pytest.mark.asyncio
    async def test_run_agent_calls_runtime_start(self):
        from simulation.agent_runner import run_agent

        agent  = _make_agent()
        client = MagicMock()

        with patch("simulation.agent_runner.AgentRuntime") as MockRT:
            MockRT.return_value.start = AsyncMock(return_value=None)
            await run_agent(agent, client)

        MockRT.return_value.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_agent_passes_poll_interval(self):
        from simulation.agent_runner import run_agent

        agent  = _make_agent()
        client = MagicMock()

        with patch("simulation.agent_runner.AgentRuntime") as MockRT:
            MockRT.return_value.start = AsyncMock(return_value=None)
            await run_agent(agent, client, poll_interval=7.0)

        _, kwargs = MockRT.call_args
        assert kwargs["poll_interval"] == 7.0

    @pytest.mark.asyncio
    async def test_run_agent_passes_auto_register(self):
        from simulation.agent_runner import run_agent

        agent  = _make_agent()
        client = MagicMock()

        with patch("simulation.agent_runner.AgentRuntime") as MockRT:
            MockRT.return_value.start = AsyncMock(return_value=None)
            await run_agent(agent, client, auto_register=False)

        _, kwargs = MockRT.call_args
        assert kwargs["auto_register"] is False

    @pytest.mark.asyncio
    async def test_run_agent_swallows_non_cancel_exception(self):
        from simulation.agent_runner import run_agent

        agent  = _make_agent()
        client = MagicMock()

        with patch("simulation.agent_runner.AgentRuntime") as MockRT:
            MockRT.return_value.start = AsyncMock(side_effect=RuntimeError("boom"))
            # Should NOT raise
            await run_agent(agent, client)

    @pytest.mark.asyncio
    async def test_run_agent_propagates_cancelled_error(self):
        from simulation.agent_runner import run_agent

        agent  = _make_agent()
        client = MagicMock()

        with patch("simulation.agent_runner.AgentRuntime") as MockRT:
            MockRT.return_value.start = AsyncMock(side_effect=asyncio.CancelledError())
            with pytest.raises(asyncio.CancelledError):
                await run_agent(agent, client)


# ─────────────────────────────────────────────────────────────────────────────
# agent_runner.run_agents_concurrently
# ─────────────────────────────────────────────────────────────────────────────

class TestRunAgentsConcurrently:

    @pytest.mark.asyncio
    async def test_runs_all_agents(self):
        from simulation.agent_runner import run_agents_concurrently

        agents = create_agents(3)
        client = MagicMock()
        call_count = 0

        async def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1

        with patch("simulation.agent_runner.run_agent", side_effect=mock_run):
            await run_agents_concurrently(agents, client)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_returns_results_list(self):
        from simulation.agent_runner import run_agents_concurrently

        agents = create_agents(2)
        client = MagicMock()

        with patch("simulation.agent_runner.run_agent", new_callable=AsyncMock, return_value=None):
            results = await run_agents_concurrently(agents, client)

        assert isinstance(results, list)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_agents_list(self):
        from simulation.agent_runner import run_agents_concurrently

        client = MagicMock()
        results = await run_agents_concurrently([], client)
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# market_simulation.MarketSimulation
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketSimulation:

    def test_init_sets_agents(self):
        agents = create_agents(3)
        mc     = _make_markets_client()
        sim    = MarketSimulation(markets_client=mc, agents=agents)
        assert sim.agents == agents

    def test_init_sets_cycle_interval(self):
        mc  = _make_markets_client()
        sim = MarketSimulation(markets_client=mc, agents=[], cycle_interval=10.0)
        assert sim.cycle_interval == 10.0

    def test_all_capabilities_deduplicates(self):
        a1  = create_agent(1, capabilities=["forecast", "research"])
        a2  = create_agent(2, capabilities=["research", "analysis"])
        mc  = _make_markets_client()
        sim = MarketSimulation(markets_client=mc, agents=[a1, a2])
        caps = sim.all_capabilities()
        assert "forecast"  in caps
        assert "research"  in caps
        assert "analysis"  in caps
        assert caps == sorted(set(caps))  # deduplicated and sorted

    def test_add_agents(self):
        mc     = _make_markets_client()
        sim    = MarketSimulation(markets_client=mc, agents=[])
        agents = create_agents(2)
        sim.add_agents(agents)
        assert len(sim.agents) == 2

    def test_stop_sets_running_false(self):
        mc  = _make_markets_client()
        sim = MarketSimulation(markets_client=mc, agents=[])
        sim._running = True
        sim.stop()
        assert not sim.is_running()

    @pytest.mark.asyncio
    async def test_run_cycle_creates_bounty(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        sim   = MarketSimulation(markets_client=mc, agents=[agent])

        result = await sim.run_cycle()

        mc.create_bounty.assert_awaited_once()
        assert result["bounty_created"] is True

    @pytest.mark.asyncio
    async def test_run_cycle_submits_solution_for_capable_agent(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client(bounty_id="b-001")
        sim   = MarketSimulation(markets_client=mc, agents=[agent])

        result = await sim.run_cycle()

        mc.submit_solution.assert_awaited_once()
        assert result["submissions"] == 1

    @pytest.mark.asyncio
    async def test_run_cycle_distributes_rewards_on_submission(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        sim   = MarketSimulation(markets_client=mc, agents=[agent])

        result = await sim.run_cycle()

        mc.distribute_rewards.assert_awaited_once()
        assert result["reward_distributed"] is True

    @pytest.mark.asyncio
    async def test_run_cycle_no_submissions_when_no_capable_agent(self):
        agent = create_agent(1, capabilities=["research"])
        mc    = _make_markets_client()
        # Force the cycle to pick a capability the agent doesn't have
        with patch("simulation.market_simulation.random.choice", return_value="forecast"):
            sim    = MarketSimulation(markets_client=mc, agents=[agent])
            result = await sim.run_cycle()

        assert result["submissions"] == 0
        mc.distribute_rewards.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_cycle_no_agents_returns_early(self):
        mc  = _make_markets_client()
        sim = MarketSimulation(markets_client=mc, agents=[])
        result = await sim.run_cycle()
        mc.create_bounty.assert_not_awaited()
        assert result["bounty_created"] is False

    @pytest.mark.asyncio
    async def test_run_cycle_bounty_failure_returns_early(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        mc.create_bounty = AsyncMock(side_effect=Exception("payment failed"))
        sim   = MarketSimulation(markets_client=mc, agents=[agent])
        result = await sim.run_cycle()
        assert result["bounty_created"] is False
        mc.submit_solution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_cycle_increments_bounties_created(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        sim   = MarketSimulation(markets_client=mc, agents=[agent])
        await sim.run_cycle()
        assert sim.bounties_created == 1

    @pytest.mark.asyncio
    async def test_run_cycle_increments_rewards_distributed(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        sim   = MarketSimulation(markets_client=mc, agents=[agent])
        await sim.run_cycle()
        assert sim.rewards_distributed == 1

    @pytest.mark.asyncio
    async def test_run_cycles_run_counter(self):
        mc  = _make_markets_client()
        sim = MarketSimulation(markets_client=mc, agents=[])
        # run() loops: stop after first sleep via CancelledError
        sim._running = True

        call_count = 0
        orig_cycle = sim.run_cycle

        async def patched_cycle():
            nonlocal call_count
            call_count += 1
            sim.stop()  # stop after first cycle
            return await orig_cycle()

        sim.run_cycle = patched_cycle
        with patch("simulation.market_simulation.asyncio.sleep", new_callable=AsyncMock):
            await sim.run()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_multiple_agents_all_submit(self):
        agents = [
            create_agent(1, capabilities=["forecast"]),
            create_agent(2, capabilities=["forecast"]),
        ]
        mc  = _make_markets_client()
        with patch("simulation.market_simulation.random.choice", return_value="forecast"):
            sim    = MarketSimulation(markets_client=mc, agents=agents)
            result = await sim.run_cycle()
        assert result["submissions"] == 2
        assert mc.submit_solution.await_count == 2

    @pytest.mark.asyncio
    async def test_bounty_titles_chosen_randomly(self):
        agent = create_agent(1, capabilities=["forecast"])
        mc    = _make_markets_client()
        sim   = MarketSimulation(markets_client=mc, agents=[agent])
        titles_seen = set()
        for _ in range(10):
            await sim.run_cycle()
            title = mc.create_bounty.call_args[1]["title"]
            titles_seen.add(title)
        assert len(titles_seen) > 1  # not always the same title

    def test_bounty_titles_constant_is_list(self):
        assert isinstance(BOUNTY_TITLES, list)
        assert len(BOUNTY_TITLES) > 0

    def test_reward_bounds_are_positive(self):
        assert MIN_REWARD > 0
        assert MAX_REWARD >= MIN_REWARD


# ─────────────────────────────────────────────────────────────────────────────
# simulation_engine.SimulationEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestSimulationEngine:

    def test_init_stores_num_agents(self):
        engine = SimulationEngine(num_agents=7)
        assert engine.num_agents == 7

    def test_init_stores_base_url(self):
        engine = SimulationEngine(base_url="http://custom:9000")
        assert engine.base_url == "http://custom:9000"

    def test_init_stores_token(self):
        engine = SimulationEngine(token="tok123")
        assert engine.token == "tok123"

    def test_init_stores_poll_interval(self):
        engine = SimulationEngine(poll_interval=3.5)
        assert engine.poll_interval == 3.5

    def test_init_stores_market_cycle_interval(self):
        engine = SimulationEngine(market_cycle_interval=8.0)
        assert engine.market_cycle_interval == 8.0

    def test_not_running_initially(self):
        engine = SimulationEngine()
        assert not engine.is_running()

    def test_agent_count_zero_before_start(self):
        engine = SimulationEngine(num_agents=5)
        assert engine.agent_count() == 0

    def test_task_count_zero_before_start(self):
        engine = SimulationEngine(num_agents=3)
        assert engine.task_count() == 0

    @pytest.mark.asyncio
    async def test_start_creates_correct_number_of_agents(self):
        engine = SimulationEngine(num_agents=4, base_url="http://localhost:8000")

        async def _noop(*args, **kwargs):
            pass

        with patch("simulation.simulation_engine.run_agent", side_effect=_noop):
            with patch("simulation.simulation_engine.MarketSimulation") as MockMarket:
                MockMarket.return_value.run = AsyncMock(return_value=None)
                with patch("simulation.simulation_engine.AgentXClient"):
                    with patch("simulation.simulation_engine.MarketsClient"):
                        await engine.start()

        assert engine.agent_count() == 4

    @pytest.mark.asyncio
    async def test_start_spawns_agent_plus_market_tasks(self):
        engine = SimulationEngine(num_agents=3)

        async def _noop(*args, **kwargs):
            pass

        with patch("simulation.simulation_engine.run_agent", side_effect=_noop):
            with patch("simulation.simulation_engine.MarketSimulation") as MockMarket:
                MockMarket.return_value.run = AsyncMock(return_value=None)
                with patch("simulation.simulation_engine.AgentXClient"):
                    with patch("simulation.simulation_engine.MarketsClient"):
                        await engine.start()

        # 3 agent tasks + 1 market task
        assert engine.task_count() == 4

    @pytest.mark.asyncio
    async def test_start_sets_running_then_clears(self):
        engine = SimulationEngine(num_agents=1)

        async def _noop(*args, **kwargs):
            pass

        with patch("simulation.simulation_engine.run_agent", side_effect=_noop):
            with patch("simulation.simulation_engine.MarketSimulation") as MockMarket:
                MockMarket.return_value.run = AsyncMock(return_value=None)
                with patch("simulation.simulation_engine.AgentXClient"):
                    with patch("simulation.simulation_engine.MarketsClient"):
                        await engine.start()

        # After all tasks finish, _running is cleared in finally
        assert not engine.is_running()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        engine = SimulationEngine(num_agents=2)

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()
        engine._tasks = [mock_task, mock_task]

        await engine.stop()

        assert mock_task.cancel.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_skips_done_tasks(self):
        engine = SimulationEngine()

        done_task = MagicMock()
        done_task.done.return_value = True
        done_task.cancel = MagicMock()
        engine._tasks = [done_task]

        await engine.stop()
        done_task.cancel.assert_not_called()

    def test_summary_returns_dict(self):
        engine = SimulationEngine(num_agents=5, base_url="http://x.io")
        s = engine.summary()
        assert s["num_agents"] == 5
        assert s["base_url"] == "http://x.io"
        assert "running" in s
        assert "tasks" in s

    @pytest.mark.asyncio
    async def test_uses_custom_capability_pool(self):
        engine = SimulationEngine(
            num_agents=2,
            capability_pool=["only_cap"],
        )

        async def _noop(*args, **kwargs):
            pass

        with patch("simulation.simulation_engine.run_agent", side_effect=_noop):
            with patch("simulation.simulation_engine.MarketSimulation") as MockMarket:
                MockMarket.return_value.run = AsyncMock(return_value=None)
                with patch("simulation.simulation_engine.AgentXClient"):
                    with patch("simulation.simulation_engine.MarketsClient"):
                        await engine.start()

        for agent in engine.agents:
            for cap in agent.capabilities:
                assert cap == "only_cap"

    @pytest.mark.asyncio
    async def test_builds_agentxclient_with_base_url(self):
        engine = SimulationEngine(num_agents=1, base_url="http://custom:7000", token="jwt")

        async def _noop(*args, **kwargs):
            pass

        with patch("simulation.simulation_engine.run_agent", side_effect=_noop):
            with patch("simulation.simulation_engine.MarketSimulation") as MockMarket:
                MockMarket.return_value.run = AsyncMock(return_value=None)
                with patch("simulation.simulation_engine.AgentXClient") as MockClient:
                    with patch("simulation.simulation_engine.MarketsClient"):
                        await engine.start()

        MockClient.assert_called_once_with(base_url="http://custom:7000", api_key="jwt")
