"""
AgentX CLI — Economy Command Group
═══════════════════════════════════
Phase 19: Autonomous Agent Economies.

Provides a self-organizing AI economy simulation where agents create work
for each other autonomously using economic strategies (specialist,
generalist, coordinator, validator).

Commands
────────
  agentx economy simulate     — Run a full self-organizing economy simulation

Usage::

    # Start docker compose first
    docker compose up -d

    # Run economy simulation with 20 agents
    agentx economy simulate --agents 20

    # Dry-run: show agents and their strategies without starting runtimes
    agentx economy simulate --agents 10 --dry-run
"""
from __future__ import annotations

import asyncio
import logging

import typer

from agentx_cli.config import load_config
from simulation.economic_simulation import EconomicSimulationEngine

economy_app = typer.Typer(
    name="economy",
    help=(
        "Autonomous agent economy commands.\n\n"
        "Agents create work for each other using economic strategies "
        "(specialist, generalist, coordinator, validator)."
    ),
    no_args_is_help=True,
)


@economy_app.command("simulate")
def economy_simulate(
    agents: int = typer.Option(
        5, "--agents", "-n",
        help="Number of economy agents to spawn.",
    ),
    url: str = typer.Option(
        None, "--url", "-u",
        help="AgentX API base URL (overrides agent.yaml).",
    ),
    poll_interval: float = typer.Option(
        2.0, "--poll",
        help="Seconds between agent contract polls.",
    ),
    economy_interval: float = typer.Option(
        5.0, "--economy-interval",
        help="Seconds between economic simulation cycles.",
    ),
    config_file: str = typer.Option(
        "agent.yaml", "--config", "-c",
        help="Path to agent.yaml configuration file.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable verbose / DEBUG logging.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Create agents and print strategies without starting runtimes.",
    ),
) -> None:
    """
    Run a self-organizing AI economy simulation.

    Spawns N agents, assigns each one an economic strategy, and starts a
    market loop where coordinator agents automatically create bounties for
    specialist and generalist agents.

    \b
    Quick-start:
        docker compose up -d
        agentx economy simulate --agents 20
    """
    # ── Logging ───────────────────────────────────────────────────────────────
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")

    # ── Resolve API URL ───────────────────────────────────────────────────────
    base_url = url
    token: str | None = None

    if base_url is None:
        try:
            cfg      = load_config(config_file)
            base_url = cfg.effective_api_url
            token    = cfg.effective_api_key
        except FileNotFoundError:
            base_url = "http://localhost:8000"

    # ── Print banner ──────────────────────────────────────────────────────────
    typer.echo(f"\nStarting ECONOMY simulation with {agents} agents...")
    typer.echo(f"  API URL:          {base_url}")
    typer.echo(f"  Poll interval:    {poll_interval}s")
    typer.echo(f"  Economy interval: {economy_interval}s")
    if dry_run:
        typer.echo("  Mode:             DRY RUN (strategies shown; runtimes not started)")
    typer.echo("\nPress Ctrl+C to stop.\n")

    # ── Dry-run mode ──────────────────────────────────────────────────────────
    if dry_run:
        from simulation.agent_factory import create_agents as _create

        try:
            from src.services.agent_strategy import select_strategy
        except ImportError:
            def select_strategy(agent_id, capabilities):  # type: ignore[misc]
                n = len(capabilities)
                if n == 0:
                    return type("S", (), {"value": "generalist"})()
                if n == 1:
                    return type("S", (), {"value": "specialist"})()
                if n >= 4:
                    return type("S", (), {"value": "coordinator"})()
                return type("S", (), {"value": "generalist"})()

        sim_agents = _create(agents)
        for a in sim_agents:
            strat = select_strategy(a.name, list(a.capabilities))
            typer.echo(
                f"  [dry-run] {a.name:<22} "
                f"strategy={strat.value:<12} caps={a.capabilities}"
            )
        typer.echo(
            f"\n  {len(sim_agents)} agent(s) created with economic strategies "
            f"(runtimes not started in dry-run mode)"
        )
        return

    # ── Live economy simulation ───────────────────────────────────────────────
    engine = EconomicSimulationEngine(
        num_agents=agents,
        base_url=base_url,
        token=token,
        poll_interval=poll_interval,
        economy_cycle_interval=economy_interval,
    )

    async def _run() -> None:
        try:
            await engine.start()
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("\nEconomy simulation stopped.")
