"""
AgentX Simulation — Economic Simulation Engine
═══════════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Extends the Phase 18 simulation with economic strategies.  Each agent is
assigned one of four economic strategies (specialist, generalist,
coordinator, validator).  Coordinator agents autonomously create bounties
for other agents; specialists and generalists compete to solve them;
validators evaluate submissions.

Classes
───────
  StrategyAgent               — wraps an Agent with its assigned strategy
  EconomicSimulation          — orchestrates a strategy-aware simulation
  EconomicSimulationEngine    — drop-in replacement for SimulationEngine
                                 with economic-strategy support

Usage::

    from simulation.economic_simulation import EconomicSimulationEngine

    engine = EconomicSimulationEngine(
        num_agents=20,
        base_url="http://localhost:8000",
    )
    await engine.start()
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from agentx_sdk.agent import Agent
from agentx_sdk.client import AgentXClient
from agentx_sdk.markets import MarketsClient

from .agent_factory import (
    CAPABILITY_POOL,
    AgentFactory,
    create_agents,
)
from .agent_runner import run_agent

# Import strategy engine (pure Python — no DB)
# Uses a local lightweight copy of strategy logic to avoid src/ import cycle
# when running outside the platform container.
try:
    from src.services.agent_strategy import (
        AgentStrategy,
        generate_work,
        hire_agents,
        select_strategy,
    )
except ImportError:
    # Fallback stubs for environments without the src package on PYTHONPATH
    from enum import Enum

    class AgentStrategy(str, Enum):  # type: ignore[no-redef]
        specialist  = "specialist"
        generalist  = "generalist"
        coordinator = "coordinator"
        validator   = "validator"

    def select_strategy(agent_id: str, capabilities: list[str]) -> AgentStrategy:  # type: ignore[misc]
        n = len(capabilities)
        if n == 0:
            return AgentStrategy.generalist
        if n == 1:
            return AgentStrategy.specialist
        if n >= 4:
            return AgentStrategy.coordinator
        return AgentStrategy.generalist

    def generate_work(agent_id, strategy, capability, *, reward_pool=50, extra=None):  # type: ignore[misc]
        return {
            "agent_id": agent_id, "strategy": strategy.value,
            "capability": capability,
            "title": f"Auto task: {capability}",
            "description": f"Economic sim work from {agent_id}",
            "reward_pool": reward_pool,
            "priority": "high" if strategy == AgentStrategy.coordinator else "normal",
        }

    def hire_agents(capability, available_agents):  # type: ignore[misc]
        return [a["did"] for a in available_agents if capability in a.get("capabilities", [])]


log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# StrategyAgent
# ─────────────────────────────────────────────────────────────────────────────

class StrategyAgent:
    """
    An Agent enriched with an assigned economic strategy.

    Attributes:
        agent:    The underlying Agent object.
        strategy: The AgentStrategy assigned to this agent.
    """

    def __init__(self, agent: Agent, strategy: AgentStrategy) -> None:
        self.agent    = agent
        self.strategy = strategy

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def capabilities(self) -> list[str]:
        return list(self.agent.capabilities)

    @property
    def did(self) -> str | None:
        return self.agent.did

    def __repr__(self) -> str:
        return (
            f"StrategyAgent(name={self.name!r}, "
            f"strategy={self.strategy.value}, "
            f"caps={self.capabilities})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# EconomicSimulation (market loop with strategy-aware behaviour)
# ─────────────────────────────────────────────────────────────────────────────

class EconomicSimulation:
    """
    Strategy-aware market simulation loop.

    Each cycle:
      1. Coordinator agents generate work proposals.
      2. The simulation posts those proposals as bounties.
      3. Specialist/generalist agents submit solutions.
      4. Validator agents (or the platform) distribute rewards.

    Args:
        markets_client:   MarketsClient for market API calls.
        strategy_agents:  List of StrategyAgent instances.
        cycle_interval:   Seconds between cycles (default 5.0).
        sim_logger:       Optional custom logger.
    """

    def __init__(
        self,
        markets_client: MarketsClient,
        strategy_agents: list[StrategyAgent],
        cycle_interval: float = 5.0,
        sim_logger: logging.Logger | None = None,
    ) -> None:
        self.markets_client  = markets_client
        self.strategy_agents = list(strategy_agents)
        self.cycle_interval  = cycle_interval
        self._log            = sim_logger or log
        self._running        = False

        # Statistics
        self.cycles_run          = 0
        self.bounties_created    = 0
        self.rewards_distributed = 0

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Run indefinitely until cancelled."""
        self._running = True
        try:
            while self._running:
                await self.run_cycle()
                self.cycles_run += 1
                await asyncio.sleep(self.cycle_interval)
        except asyncio.CancelledError:
            self._log.info("EconomicSimulation: cancelled after %d cycles", self.cycles_run)
            raise
        finally:
            self._running = False

    async def run_cycle(self) -> dict[str, Any]:
        """
        Execute one economic simulation cycle.

        Returns a summary dict with cycle stats.
        """
        result: dict[str, Any] = {
            "bounties_created": 0,
            "submissions":      0,
            "rewards":          0,
            "errors":           0,
        }

        # ── Coordinators create work ───────────────────────────────────────────
        coordinators = [
            sa for sa in self.strategy_agents
            if sa.strategy == AgentStrategy.coordinator and sa.capabilities
        ]

        for coord in coordinators:
            capability = random.choice(coord.capabilities)
            proposal   = generate_work(
                agent_id=coord.name,
                strategy=AgentStrategy.coordinator,
                capability=capability,
                reward_pool=random.randint(10, 100),
            )
            try:
                bounty = await self.markets_client.create_bounty(
                    title=proposal["title"],
                    capability_required=proposal["capability"],
                    reward_pool=proposal["reward_pool"],
                    description=proposal["description"],
                )
                bounty_id = bounty.get("bounty_id") or bounty.get("id", "unknown")
                result["bounties_created"] += 1
                self.bounties_created += 1
                self._log.debug(
                    "EconomicSimulation: coordinator %s created bounty %s",
                    coord.name, bounty_id,
                )

                # ── Solvers submit solutions ───────────────────────────────────
                solvers = [
                    sa for sa in self.strategy_agents
                    if sa.strategy in (AgentStrategy.specialist, AgentStrategy.generalist)
                    and (
                        capability in sa.capabilities
                        or sa.strategy == AgentStrategy.generalist
                    )
                ]
                for solver in solvers:
                    try:
                        await self.markets_client.submit_solution(
                            bounty_id=bounty_id,
                            solution_data={
                                "solver":     solver.name,
                                "strategy":   solver.strategy.value,
                                "capability": capability,
                                "result":     f"Simulation solution by {solver.name}",
                            },
                        )
                        result["submissions"] += 1
                    except Exception as exc:
                        self._log.debug(
                            "EconomicSimulation: solver %s submission error: %s",
                            solver.name, exc,
                        )
                        result["errors"] += 1

                # ── Distribute rewards ─────────────────────────────────────────
                if result["submissions"] > 0:
                    try:
                        await self.markets_client.distribute_rewards(bounty_id=bounty_id)
                        result["rewards"] += 1
                        self.rewards_distributed += 1
                    except Exception as exc:
                        self._log.debug(
                            "EconomicSimulation: reward distribution error: %s", exc
                        )
                        result["errors"] += 1

            except Exception as exc:
                self._log.warning(
                    "EconomicSimulation: coordinator %s error: %s", coord.name, exc
                )
                result["errors"] += 1

        return result


# ─────────────────────────────────────────────────────────────────────────────
# EconomicSimulationEngine (orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

class EconomicSimulationEngine:
    """
    Full economic simulation orchestrator: spawns agents with strategies,
    runs an agent-runner task per agent, and an EconomicSimulation loop.

    This is the Phase 19 equivalent of Phase 18's SimulationEngine but
    with strategy-aware agents and agent-created bounties.

    Args:
        num_agents:            Number of simulation agents to spawn.
        base_url:              AgentX API base URL.
        token:                 Optional Bearer token.
        poll_interval:         Seconds between agent contract polls.
        economy_cycle_interval: Seconds between economic simulation cycles.
        auto_register:         Register agents on startup (default True).
        capability_pool:       Custom capability pool (default CAPABILITY_POOL).
        sim_logger:            Optional custom logger.
    """

    def __init__(
        self,
        num_agents: int = 5,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        poll_interval: float = 2.0,
        economy_cycle_interval: float = 5.0,
        auto_register: bool = True,
        capability_pool: list[str] | None = None,
        sim_logger: logging.Logger | None = None,
    ) -> None:
        self.num_agents             = num_agents
        self.base_url               = base_url
        self.token                  = token
        self.poll_interval          = poll_interval
        self.economy_cycle_interval = economy_cycle_interval
        self.auto_register          = auto_register
        self.capability_pool        = capability_pool or CAPABILITY_POOL
        self._log                   = sim_logger or log

        self.strategy_agents: list[StrategyAgent] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ── Public methods ─────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def agent_count(self) -> int:
        return len(self.strategy_agents)

    def task_count(self) -> int:
        return len(self._tasks)

    def active_task_count(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    def summary(self) -> dict[str, Any]:
        return {
            "num_agents":   self.agent_count(),
            "active_tasks": self.active_task_count(),
            "is_running":   self._running,
            "strategies":   {
                s.name: s.strategy.value for s in self.strategy_agents
            },
        }

    async def start(self) -> None:
        """
        Start the economic simulation:
          1. Create N agents.
          2. Assign economic strategies.
          3. Launch an asyncio Task per agent (runtime loop).
          4. Launch the EconomicSimulation loop.
          5. Await all tasks until cancelled.
        """
        # ── 1. Create agents ──────────────────────────────────────────────────
        raw_agents = create_agents(
            n=self.num_agents,
            capability_pool=self.capability_pool,
        )

        # ── 2. Assign strategies ──────────────────────────────────────────────
        self.strategy_agents = [
            StrategyAgent(
                agent=a,
                strategy=select_strategy(a.name, list(a.capabilities)),
            )
            for a in raw_agents
        ]

        self._log.info(
            "EconomicSimulationEngine: starting %d agents with strategies",
            self.num_agents,
        )
        for sa in self.strategy_agents:
            self._log.debug("  %r", sa)

        # ── 3. Build shared clients ───────────────────────────────────────────
        client = AgentXClient(
            base_url=self.base_url,
            api_key=self.token,
        )
        markets_client = MarketsClient(
            base_url=self.base_url,
            token=self.token,
        )

        # ── 4. Spawn agent-runner tasks ───────────────────────────────────────
        self._tasks = []
        self._running = True

        for sa in self.strategy_agents:
            task = asyncio.create_task(
                run_agent(
                    agent=sa.agent,
                    client=client,
                    poll_interval=self.poll_interval,
                    auto_register=self.auto_register,
                ),
                name=f"econ-runner-{sa.name}",
            )
            self._tasks.append(task)

        # ── 5. Spawn economic simulation task ─────────────────────────────────
        econ_sim = EconomicSimulation(
            markets_client=markets_client,
            strategy_agents=self.strategy_agents,
            cycle_interval=self.economy_cycle_interval,
            sim_logger=self._log,
        )
        econ_task = asyncio.create_task(
            econ_sim.run(),
            name="economic-simulation",
        )
        self._tasks.append(econ_task)

        # ── 6. Wait for all tasks ─────────────────────────────────────────────
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        """Cancel all running tasks gracefully."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
