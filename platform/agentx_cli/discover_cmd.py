"""
AgentX CLI — Discover Commands
════════════════════════════════
Phase 16: Agent Discovery & Capability Registry.

Subcommands
───────────
  agentx discover capability <name>   — find agents by capability
  agentx discover top                 — list top-ranked agents
  agentx discover search "<query>"    — semantic capability search
  agentx discover metrics <agent-id>  — show performance metrics for an agent
"""
from __future__ import annotations

import asyncio
import logging

import typer

from agentx_sdk.discovery import DiscoveryClient
from .config import load_config

logger = logging.getLogger(__name__)

discover_app = typer.Typer(
    name="discover",
    help="Discover agents by capability, reputation, and performance.",
    no_args_is_help=True,
)

_CONFIG_OPT = typer.Option("agent.yaml", "--config", "-c", help="Path to agent.yaml.")
_LIMIT_OPT  = typer.Option(10, "--limit", "-n", help="Maximum number of results.")


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_client(config_file: str) -> DiscoveryClient:
    """Return a DiscoveryClient configured from agent.yaml."""
    cfg = load_config(config_file)
    return DiscoveryClient(base_url=cfg.api_url, token=cfg.api_key)


def _fmt_agent(a: dict, idx: int) -> None:
    """Print a single agent discovery result."""
    score = a.get("score", 0.0)
    name  = a.get("name") or a.get("agent_did", "?")
    did   = a.get("agent_did", "?")
    caps  = ", ".join(a.get("capabilities") or []) or "(none)"
    typer.echo(
        f"  #{idx:>2}  [{score:.3f}]  {name[:30]:<30}  {did[:40]}\n"
        f"        capabilities: {caps}\n"
        f"        completed={a.get('contracts_completed',0)}  "
        f"bounties={a.get('bounties_won',0)}  "
        f"trust={a.get('trust_score',0.0):.2f}"
    )


# ── discover capability ───────────────────────────────────────────────────────

@discover_app.command("capability")
def discover_capability(
    name: str = typer.Argument(..., help="Exact capability name to search for."),
    limit: int = _LIMIT_OPT,
    config_file: str = _CONFIG_OPT,
):
    """Find agents that have registered a specific capability, ranked by score."""
    client = _get_client(config_file)

    async def _run():
        return await client.discover_agents(capability=name, limit=limit)

    try:
        agents = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if not agents:
        typer.echo(f"No agents found for capability '{name}'.")
        return

    typer.echo(f"\nAgents with capability '{name}' ({len(agents)} found):\n")
    for i, a in enumerate(agents, 1):
        _fmt_agent(a, i)
    typer.echo()


# ── discover top ──────────────────────────────────────────────────────────────

@discover_app.command("top")
def discover_top(
    limit: int = _LIMIT_OPT,
    config_file: str = _CONFIG_OPT,
):
    """List the highest-ranked agents in the network."""
    client = _get_client(config_file)

    async def _run():
        return await client.get_top_agents(limit=limit)

    try:
        agents = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if not agents:
        typer.echo("No agents found.")
        return

    typer.echo(f"\nTop {len(agents)} agents in the network:\n")
    for i, a in enumerate(agents, 1):
        _fmt_agent(a, i)
    typer.echo()


# ── discover search ───────────────────────────────────────────────────────────

@discover_app.command("search")
def discover_search(
    query: str = typer.Argument(..., help="Natural-language capability description."),
    limit: int = _LIMIT_OPT,
    config_file: str = _CONFIG_OPT,
):
    """Semantically search for agents whose capabilities match the query."""
    client = _get_client(config_file)

    async def _run():
        return await client.search_agents(query=query, limit=limit)

    try:
        agents = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if not agents:
        typer.echo(f"No agents matched '{query}'.")
        return

    typer.echo(f"\nSearch results for '{query}' ({len(agents)} found):\n")
    for i, a in enumerate(agents, 1):
        _fmt_agent(a, i)
    typer.echo()


# ── discover metrics ─────────────────────────────────────────────────────────

@discover_app.command("metrics")
def discover_metrics(
    agent_id: str = typer.Argument(..., help="UUID of the agent."),
    config_file: str = _CONFIG_OPT,
):
    """Show performance metrics for a specific agent."""
    client = _get_client(config_file)

    async def _run():
        return await client.get_agent_metrics(agent_id)

    try:
        metrics = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"\nMetrics for agent {agent_id}:")
    typer.echo(f"  Contracts completed:  {metrics.get('contracts_completed', 0)}")
    typer.echo(f"  Contracts failed:     {metrics.get('contracts_failed', 0)}")
    typer.echo(f"  Verification success: {metrics.get('verification_success', 0.0):.1%}")
    typer.echo(f"  Bounties won:         {metrics.get('bounties_won', 0)}")
    if metrics.get("last_active"):
        typer.echo(f"  Last active:          {metrics['last_active']}")
    typer.echo()
