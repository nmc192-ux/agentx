"""
AgentX Simulation — Agent Runner
══════════════════════════════════
Wraps ``AgentRuntime`` to run one or many agents concurrently.

Usage::

    import asyncio
    from agentx_sdk import AgentXClient
    from simulation.agent_factory import create_agents
    from simulation.agent_runner import run_agents_concurrently

    client = AgentXClient(base_url="http://localhost:8000")
    agents = create_agents(5)
    asyncio.run(run_agents_concurrently(agents, client))
"""
from __future__ import annotations

import asyncio
import logging

from agentx_sdk import Agent, AgentRuntime
from agentx_sdk.client import AgentXClient

logger = logging.getLogger(__name__)


async def run_agent(
    agent: Agent,
    client: AgentXClient,
    poll_interval: float = 2.0,
    auto_register: bool = True,
    sim_logger: logging.Logger | None = None,
) -> None:
    """Run a single simulation agent via ``AgentRuntime``.

    This coroutine runs until cancelled or until the runtime raises an
    unrecoverable exception.

    Args:
        agent:          The agent instance to run.
        client:         Authenticated ``AgentXClient`` for API calls.
        poll_interval:  Seconds between polling for new contracts.
        auto_register:  When *True* the runtime registers the agent on start.
        sim_logger:     Optional logger for simulation-specific output.
    """
    log = sim_logger or logger
    runtime = AgentRuntime(
        agent=agent,
        client=client,
        poll_interval=poll_interval,
        auto_register=auto_register,
    )
    log.info("[%s] runtime starting (caps=%s)", agent.name, agent.capabilities)
    try:
        await runtime.start()
    except asyncio.CancelledError:
        log.info("[%s] runtime cancelled", agent.name)
        raise
    except Exception as exc:
        log.warning("[%s] runtime error: %s — agent stopped", agent.name, exc)


async def run_agents_concurrently(
    agents: list[Agent],
    client: AgentXClient,
    poll_interval: float = 2.0,
    auto_register: bool = True,
    sim_logger: logging.Logger | None = None,
) -> list[BaseException | None]:
    """Run multiple agents concurrently using ``asyncio.gather``.

    All agents share a single ``AgentXClient`` instance.  Exceptions from
    individual agents are collected and returned rather than propagated, so
    the failure of one agent does not stop the others.

    Args:
        agents:         List of agents to run.
        client:         Shared API client.
        poll_interval:  Polling interval for each agent.
        auto_register:  Register each agent on start.
        sim_logger:     Optional logger for simulation-specific output.

    Returns:
        List of results / exceptions, one per agent (same order as *agents*).
    """
    log = sim_logger or logger
    log.info("[runner] launching %d agents concurrently", len(agents))

    coroutines = [
        run_agent(
            agent=agent,
            client=client,
            poll_interval=poll_interval,
            auto_register=auto_register,
            sim_logger=log,
        )
        for agent in agents
    ]
    results = await asyncio.gather(*coroutines, return_exceptions=True)
    log.info("[runner] all agents finished")
    return list(results)
