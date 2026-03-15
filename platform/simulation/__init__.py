"""
AgentX — Multi-Agent Local Simulation
═══════════════════════════════════════
Allows developers to spin up many agents locally to stress-test markets,
contracts, bounties, and agent economies — no cloud required.

Quick-start
───────────
    agentx simulate --agents 10

Or programmatically::

    import asyncio
    from simulation.simulation_engine import SimulationEngine

    engine = SimulationEngine(num_agents=10, base_url="http://localhost:8000")
    asyncio.run(engine.start())

Modules
───────
    agent_factory      — create Agent instances with random capabilities
    agent_runner       — run single / multiple agents concurrently
    simulation_engine  — main orchestrator (N agents + market loop)
    market_simulation  — economic activity: bounties, solutions, rewards
"""
from .agent_factory import AgentFactory, create_agent, create_agents
from .agent_runner import run_agent, run_agents_concurrently
from .market_simulation import MarketSimulation
from .simulation_engine import SimulationEngine

__all__ = [
    "AgentFactory",
    "create_agent",
    "create_agents",
    "run_agent",
    "run_agents_concurrently",
    "MarketSimulation",
    "SimulationEngine",
]
