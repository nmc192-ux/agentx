"""
AgentX Simulation — Simulation Engine
═══════════════════════════════════════
Main orchestrator for multi-agent local simulations.

Usage::

    import asyncio
    from simulation.simulation_engine import SimulationEngine

    engine = SimulationEngine(num_agents=10, base_url="http://localhost:8000")
    asyncio.run(engine.start())   # blocks; Ctrl-C to stop

The engine:
  1. Creates N agents via AgentFactory
  2. Builds a shared AgentXClient and MarketsClient
  3. Spawns one asyncio Task per agent (via agent_runner.run_agent)
  4. Spawns one MarketSimulation task for economic activity
  5. Awaits all tasks (runs indefinitely until cancelled)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentx_sdk import AgentXClient
from agentx_sdk.markets import MarketsClient

from .agent_factory import create_agents
from .agent_runner import run_agent
from .market_simulation import MarketSimulation

logger = logging.getLogger(__name__)


class SimulationEngine:
    """Multi-agent simulation orchestrator.

    Args:
        num_agents:            Number of agents to spawn.
        base_url:              AgentX API base URL.
        token:                 Bearer token / API key (optional for localhost).
        poll_interval:         Seconds between agent contract polls.
        market_cycle_interval: Seconds between market simulation cycles.
        auto_register:         Register each agent with the API on start.
        capability_pool:       Custom pool of capabilities; defaults to CAPABILITY_POOL.
        sim_logger:            Optional custom logger.
    """

    def __init__(
        self,
        num_agents: int = 5,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        poll_interval: float = 2.0,
        market_cycle_interval: float = 5.0,
        auto_register: bool = True,
        capability_pool: list[str] | None = None,
        sim_logger: logging.Logger | None = None,
    ) -> None:
        self.num_agents            = num_agents
        self.base_url              = base_url
        self.token                 = token
        self.poll_interval         = poll_interval
        self.market_cycle_interval = market_cycle_interval
        self.auto_register         = auto_register
        self.capability_pool       = capability_pool
        self.logger                = sim_logger or logger

        # State (populated on start)
        self.agents: list[Any] = []
        self._tasks: list[asyncio.Task] = []
        self._running: bool = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the simulation.

        Creates agents, builds clients, spawns asyncio Tasks, and awaits them.
        This coroutine runs indefinitely until cancelled (KeyboardInterrupt /
        ``asyncio.CancelledError``) or until all tasks complete naturally.
        """
        self.logger.info(
            "[sim] Starting simulation — %d agents  url=%s",
            self.num_agents, self.base_url,
        )

        # 1. Create agents
        self.agents = create_agents(
            n=self.num_agents,
            capability_pool=self.capability_pool,
        )
        for agent in self.agents:
            self.logger.info(
                "[sim] Agent created: %s  caps=%s",
                agent.name, agent.capabilities,
            )

        # 2. Build shared clients
        client         = AgentXClient(base_url=self.base_url, api_key=self.token)
        markets_client = MarketsClient(base_url=self.base_url, token=self.token)

        self._running = True
        self._tasks   = []

        # 3. Spawn one task per agent
        for agent in self.agents:
            task = asyncio.create_task(
                run_agent(
                    agent=agent,
                    client=client,
                    poll_interval=self.poll_interval,
                    auto_register=self.auto_register,
                    sim_logger=self.logger,
                ),
                name=f"runner-{agent.name}",
            )
            self._tasks.append(task)

        # 4. Spawn market simulation task
        market_sim  = MarketSimulation(
            markets_client=markets_client,
            agents=self.agents,
            cycle_interval=self.market_cycle_interval,
            sim_logger=self.logger,
        )
        market_task = asyncio.create_task(market_sim.run(), name="market-simulation")
        self._tasks.append(market_task)

        self.logger.info(
            "[sim] %d agent tasks + 1 market task spawned",
            len(self.agents),
        )

        # 5. Wait for all tasks (runs until Ctrl-C / CancelledError)
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            self.logger.info("[sim] simulation cancelled")
            raise
        finally:
            self._running = False
            self.logger.info("[sim] simulation finished")

    async def stop(self) -> None:
        """Cancel all running tasks and stop the simulation."""
        self._running = False
        cancelled = 0
        for task in self._tasks:
            if not task.done():
                task.cancel()
                cancelled += 1
        self.logger.info("[sim] stopped — cancelled %d tasks", cancelled)

    # ── Properties ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def agent_count(self) -> int:
        return len(self.agents)

    def task_count(self) -> int:
        return len(self._tasks)

    def active_task_count(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    def summary(self) -> dict[str, Any]:
        """Return a status summary dict."""
        return {
            "num_agents":     self.num_agents,
            "base_url":       self.base_url,
            "running":        self._running,
            "tasks":          len(self._tasks),
            "active_tasks":   self.active_task_count(),
            "agent_names":    [a.name for a in self.agents],
        }
