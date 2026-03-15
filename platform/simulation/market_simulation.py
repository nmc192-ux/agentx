"""
AgentX Simulation — Market Simulation
═══════════════════════════════════════
Simulates economic activity: creates random bounties, submits solutions on
behalf of capable agents, and distributes rewards.

Usage::

    from simulation.market_simulation import MarketSimulation
    from agentx_sdk.markets import MarketsClient

    markets = MarketsClient(base_url="http://localhost:8000", token="jwt")
    sim     = MarketSimulation(markets_client=markets, agents=agents)
    await sim.run()           # loops until cancelled
    # or a single cycle:
    result  = await sim.run_cycle()
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from agentx_sdk import Agent
from agentx_sdk.markets import MarketsClient

logger = logging.getLogger(__name__)

# ── Simulation data ───────────────────────────────────────────────────────────

BOUNTY_TITLES: list[str] = [
    "Generate market forecast",
    "Analyse sentiment data",
    "Research competitive landscape",
    "Translate product documentation",
    "Summarise daily news feed",
    "Review codebase for security issues",
    "Build ETL data pipeline",
    "Create quarterly financial report",
    "Predict user churn patterns",
    "Generate recommendation model",
]

MIN_REWARD: int = 10
MAX_REWARD: int = 100


class MarketSimulation:
    """Continuous economic activity loop.

    Each *cycle*:

    1. Selects a random capability from the registered agents.
    2. Creates a bounty for that capability with a random reward.
    3. Every capable agent submits a solution.
    4. Distributes rewards to the best submission.

    The loop sleeps ``cycle_interval`` seconds between cycles and can be
    cancelled cleanly via ``asyncio.CancelledError``.
    """

    def __init__(
        self,
        markets_client: MarketsClient,
        agents: list[Agent],
        cycle_interval: float = 5.0,
        sim_logger: logging.Logger | None = None,
    ) -> None:
        self.markets_client  = markets_client
        self.agents          = list(agents)
        self.cycle_interval  = cycle_interval
        self.logger          = sim_logger or logger
        self._running        = False
        self.cycles_run      = 0
        self.bounties_created = 0
        self.rewards_distributed = 0

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run market cycles indefinitely until cancelled."""
        self._running = True
        self.logger.info("[market] simulation started (cycle_interval=%.1fs)", self.cycle_interval)
        try:
            while self._running:
                await self.run_cycle()
                self.cycles_run += 1
                await asyncio.sleep(self.cycle_interval)
        except asyncio.CancelledError:
            self.logger.info(
                "[market] simulation cancelled after %d cycles", self.cycles_run
            )
            raise
        except Exception as exc:
            self.logger.warning("[market] unexpected error in run loop: %s", exc)
        finally:
            self._running = False

    # ── Single cycle ──────────────────────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one market cycle.

        Returns:
            Dict with keys:
                bounty_created      (bool)
                bounty_id           (str | None)
                capability          (str | None)
                submissions         (int)
                reward_distributed  (bool)
        """
        result: dict[str, Any] = {
            "bounty_created":      False,
            "bounty_id":           None,
            "capability":          None,
            "submissions":         0,
            "reward_distributed":  False,
        }

        if not self.agents:
            self.logger.debug("[market] no agents available — skipping cycle")
            return result

        # 1. Pick a random capability that at least one agent has
        all_caps: list[str] = []
        for agent in self.agents:
            all_caps.extend(agent.capabilities)

        if not all_caps:
            self.logger.debug("[market] agents have no capabilities — skipping cycle")
            return result

        capability = random.choice(all_caps)
        title      = random.choice(BOUNTY_TITLES)
        reward     = random.randint(MIN_REWARD, MAX_REWARD)

        result["capability"] = capability

        # 2. Create the bounty
        try:
            bounty    = await self.markets_client.create_bounty(
                title=title,
                capability_required=capability,
                reward_pool=reward,
                description=f"Simulation bounty — capability: {capability}",
            )
            bounty_id = bounty.get("bounty_id") or bounty.get("id", "unknown")
            result["bounty_created"] = True
            result["bounty_id"]      = bounty_id
            self.bounties_created   += 1
            self.logger.info(
                "[market] bounty created: '%s'  cap=%s  reward=%d  id=%s",
                title, capability, reward, str(bounty_id)[:8],
            )
        except Exception as exc:
            self.logger.warning("[market] failed to create bounty: %s", exc)
            return result

        # 3. Capable agents submit solutions
        capable = [a for a in self.agents if capability in a.capabilities]
        for agent in capable:
            try:
                await self.markets_client.submit_solution(
                    bounty_id=bounty_id,
                    solution_data={
                        "agent":      agent.name,
                        "capability": capability,
                        "output":     f"Simulation output by {agent.name}",
                    },
                    summary=f"Submitted by {agent.name}",
                )
                result["submissions"] += 1
                self.logger.info(
                    "[%s] submitted solution for bounty %s",
                    agent.name, str(bounty_id)[:8],
                )
            except Exception as exc:
                self.logger.warning(
                    "[%s] failed to submit solution: %s", agent.name, exc
                )

        # 4. Distribute rewards (only if at least one submission succeeded)
        if result["submissions"] > 0:
            try:
                await self.markets_client.distribute_rewards(bounty_id=bounty_id)
                result["reward_distributed"] = True
                self.rewards_distributed    += 1
                self.logger.info(
                    "[market] rewards distributed for bounty %s", str(bounty_id)[:8]
                )
            except Exception as exc:
                self.logger.warning(
                    "[market] failed to distribute rewards for %s: %s",
                    str(bounty_id)[:8], exc,
                )

        return result

    # ── Control ───────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the run loop to stop after the current cycle."""
        self._running = False

    def is_running(self) -> bool:
        return self._running

    # ── Agent management ──────────────────────────────────────────────────────

    def add_agents(self, agents: list[Agent]) -> None:
        """Add more agents to the simulation dynamically."""
        self.agents.extend(agents)

    def all_capabilities(self) -> list[str]:
        """Return a flat, deduplicated list of all agent capabilities."""
        caps: set[str] = set()
        for agent in self.agents:
            caps.update(agent.capabilities)
        return sorted(caps)
