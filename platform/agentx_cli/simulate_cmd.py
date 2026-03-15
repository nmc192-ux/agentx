"""
AgentX CLI — Simulate Command
══════════════════════════════
Launch a multi-agent local simulation to stress-test markets and agent
economies on a local docker compose environment.

Usage::

    # Start docker compose first
    docker compose up -d

    # Then spawn agents
    agentx simulate --agents 10

    # Dry-run: create agents without starting runtimes
    agentx simulate --agents 5 --dry-run

    # Point at a specific API
    agentx simulate --agents 20 --url http://localhost:8000 --verbose
"""
from __future__ import annotations

import asyncio
import logging

import typer

from agentx_cli.config import load_config
from simulation.simulation_engine import SimulationEngine


def simulate(
    agents: int = typer.Option(
        5, "--agents", "-n",
        help="Number of simulation agents to spawn.",
    ),
    url: str = typer.Option(
        None, "--url", "-u",
        help="AgentX API base URL (overrides agent.yaml).",
    ),
    poll_interval: float = typer.Option(
        2.0, "--poll",
        help="Seconds between agent contract polls.",
    ),
    market_interval: float = typer.Option(
        5.0, "--market-interval",
        help="Seconds between market simulation cycles.",
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
        help="Create agents and print info without starting runtimes.",
    ),
) -> None:
    """Launch a multi-agent local simulation.

    Spawns N agents, registers them with the AgentX API, and kicks off an
    economic market loop (bounties → solutions → rewards).  Press Ctrl-C to
    stop gracefully.

    \b
    Quick-start:
        docker compose up -d
        agentx simulate --agents 10
    """
    # ── Logging ───────────────────────────────────────────────────────────────
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
    )

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
    typer.echo(f"\nStarting simulation with {agents} agents...")
    typer.echo(f"  API URL:       {base_url}")
    typer.echo(f"  Poll interval: {poll_interval}s")
    typer.echo(f"  Market cycle:  {market_interval}s")
    if dry_run:
        typer.echo("  Mode:          DRY RUN (runtimes not started)")
    typer.echo("\nPress Ctrl+C to stop.\n")

    # ── Dry-run mode ──────────────────────────────────────────────────────────
    if dry_run:
        from simulation.agent_factory import create_agents as _create
        sim_agents = _create(agents)
        for a in sim_agents:
            typer.echo(f"  [dry-run] {a.name:<22} caps={a.capabilities}")
        typer.echo(
            f"\n  {len(sim_agents)} agent(s) created  "
            f"(runtimes not started in dry-run mode)"
        )
        return

    # ── Live simulation ───────────────────────────────────────────────────────
    engine = SimulationEngine(
        num_agents=agents,
        base_url=base_url,
        token=token,
        poll_interval=poll_interval,
        market_cycle_interval=market_interval,
    )

    async def _run() -> None:
        try:
            await engine.start()
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("\nSimulation stopped.")
