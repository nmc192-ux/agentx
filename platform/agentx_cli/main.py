"""
AgentX CLI — main entrypoint
══════════════════════════════
Phase 14: Agent CLI

Creates the root Typer application and wires together all sub-commands.

Commands
────────
    agentx init <name>      Scaffold a new agent project directory.
    agentx run              Start the agent runtime loop.
    agentx wallet …         Wallet: balance, transfer, stake, history.
    agentx contracts …      Contracts: list, create, submit, complete, info.
    agentx info             Show current agent configuration.

Installation (after pip install -e .)
──────────────────────────────────────
    agentx --help
    agentx init my_agent
    agentx run
    agentx wallet balance
    agentx contracts list
"""
from __future__ import annotations

from typing import Optional

import typer

from .bounties_cmd import bounties_app
from .config import CONFIG_FILENAME, load_config
from .contracts_cmd import contracts_app
from .discover_cmd import discover_app
from .economy_cmd import economy_app
from .init_cmd import init_agent
from .node_cmd import node_app
from .run_cmd import run_agent
from .simulate_cmd import simulate
from .wallet_cmd import wallet_app

# ── Root application ──────────────────────────────────────────────────────────

app = typer.Typer(
    name="agentx",
    help=(
        "AgentX CLI — the developer entrypoint for the AgentX agent network.\n\n"
        "Run 'agentx COMMAND --help' for detailed usage of each command."
    ),
    add_completion=False,   # keep output clean in CI / docs
    no_args_is_help=True,
)

# ── Register sub-command groups ───────────────────────────────────────────────

app.add_typer(wallet_app,    name="wallet")
app.add_typer(contracts_app, name="contracts")
app.add_typer(bounties_app,  name="bounties")
app.add_typer(discover_app,  name="discover")
app.add_typer(node_app,      name="node")
app.add_typer(economy_app,   name="economy")

# ── Register single-call commands ─────────────────────────────────────────────

app.command("init")(init_agent)
app.command("run")(run_agent)
app.command("simulate")(simulate)


# ── agentx info ───────────────────────────────────────────────────────────────

@app.command("info")
def info(
    config_file: str = typer.Option(
        CONFIG_FILENAME,
        "--config",
        "-c",
        help="Path to agent.yaml configuration file.",
    ),
) -> None:
    """
    Display the current agent configuration and status.

    Reads agent.yaml from the current directory (or --config) and prints
    all configuration values so you can verify the setup before running.
    """
    try:
        config = load_config(config_file)
    except FileNotFoundError as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)

    typer.echo("\nAgentX Agent Configuration")
    typer.echo("══════════════════════════")
    typer.echo(f"  Name:          {config.name}")
    typer.echo(f"  DID:           {config.effective_did or '(not set)'}")
    typer.echo(f"  Agent ID:      {config.agent_id or '(not set — run agentx run to register)'}")
    typer.echo(f"  API URL:       {config.effective_api_url}")
    typer.echo(f"  API Key:       {'(set)' if config.effective_api_key else '(not set)'}")
    caps = ", ".join(config.capabilities) if config.capabilities else "(none)"
    typer.echo(f"  Capabilities:  {caps}")
    typer.echo()


# ── Entry point for `python -m agentx_cli` ────────────────────────────────────

if __name__ == "__main__":
    app()
