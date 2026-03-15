"""
AgentX Simulation — Agent Factory
═══════════════════════════════════
Creates Agent instances with realistic random capabilities so they can
compete against each other in local market simulations.

Usage::

    from simulation.agent_factory import create_agent, create_agents, AgentFactory

    # One agent with random caps
    agent = create_agent(1)

    # Ten agents, each with 1-3 random capabilities
    agents = create_agents(10)

    # Configurable factory
    factory = AgentFactory(min_caps=2, max_caps=4)
    agents = factory.create_many(5)
"""
from __future__ import annotations

import random
from typing import Callable, Coroutine, Any

from agentx_sdk import Agent

# ── Capability pool ───────────────────────────────────────────────────────────

CAPABILITY_POOL: list[str] = [
    "forecast",
    "research",
    "summarization",
    "analysis",
    "translation",
    "code_review",
    "data_pipeline",
    "sentiment_analysis",
]


# ── Handler factory (avoids closure / late-binding issues in loops) ────────────

def _make_handler(capability: str, agent_name: str) -> Callable:
    """Return an async handler that returns a simulation result dict.

    Using a factory avoids the classic Python closure bug where all loop
    iterations capture the *last* value of the loop variable.
    """
    async def _handler(data: dict) -> dict:
        return {
            "status": "completed",
            "capability": capability,
            "agent": agent_name,
            "result": f"Simulation result for '{capability}' by {agent_name}",
            "input_keys": list(data.keys()),
        }
    _handler.__name__ = f"sim_handler_{capability}"
    return _handler


# ── Public helpers ────────────────────────────────────────────────────────────

def create_agent(
    index: int,
    capabilities: list[str] | None = None,
    capability_pool: list[str] | None = None,
    min_caps: int = 1,
    max_caps: int = 3,
) -> Agent:
    """Create a single simulation agent.

    Args:
        index:          Numeric index used to build the agent name
                        (``sim_agent_<index>``).
        capabilities:   Explicit capability list.  When *None* a random
                        sample is drawn from *capability_pool*.
        capability_pool: Pool to sample from (defaults to CAPABILITY_POOL).
        min_caps:       Minimum random capabilities when sampling.
        max_caps:       Maximum random capabilities when sampling.

    Returns:
        An ``Agent`` instance with handlers registered for every capability.
    """
    pool = capability_pool or CAPABILITY_POOL

    if capabilities is None:
        n     = random.randint(min_caps, min(max_caps, len(pool)))
        capabilities = random.sample(pool, n)

    name  = f"sim_agent_{index}"
    agent = Agent(name=name, capabilities=list(capabilities))

    # Register a handler for every declared capability
    for cap in capabilities:
        handler = _make_handler(cap, name)
        agent.contract(cap)(handler)

    return agent


def create_agents(
    n: int,
    capability_pool: list[str] | None = None,
    min_caps: int = 1,
    max_caps: int = 3,
) -> list[Agent]:
    """Create *n* simulation agents with random capabilities.

    Args:
        n:              Number of agents to create.
        capability_pool: Pool to sample capabilities from.
        min_caps:       Minimum capabilities per agent.
        max_caps:       Maximum capabilities per agent.

    Returns:
        List of ``Agent`` instances indexed from 1 to *n*.
    """
    return [
        create_agent(
            index=i,
            capability_pool=capability_pool,
            min_caps=min_caps,
            max_caps=max_caps,
        )
        for i in range(1, n + 1)
    ]


class AgentFactory:
    """Stateful factory that tracks a monotonically increasing agent index.

    Useful when you want to add agents to a running simulation without
    resetting the index::

        factory = AgentFactory(min_caps=2, max_caps=3)
        initial_batch = factory.create_many(5)   # sim_agent_1 … 5
        later_batch   = factory.create_many(3)   # sim_agent_6 … 8
    """

    def __init__(
        self,
        capability_pool: list[str] | None = None,
        min_caps: int = 1,
        max_caps: int = 3,
    ) -> None:
        self.capability_pool = capability_pool or CAPABILITY_POOL
        self.min_caps  = min_caps
        self.max_caps  = max_caps
        self._counter  = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def create(self, capabilities: list[str] | None = None) -> Agent:
        """Create one agent (auto-increments internal counter)."""
        self._counter += 1
        return create_agent(
            index=self._counter,
            capabilities=capabilities,
            capability_pool=self.capability_pool,
            min_caps=self.min_caps,
            max_caps=self.max_caps,
        )

    def create_many(self, n: int) -> list[Agent]:
        """Create *n* agents (consecutive indices)."""
        return [self.create() for _ in range(n)]

    def reset(self) -> None:
        """Reset the internal counter to 0."""
        self._counter = 0

    @property
    def agents_created(self) -> int:
        """Total number of agents created so far."""
        return self._counter
