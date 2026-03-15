"""
AgentX CLI — Node Commands
═══════════════════════════
Phase 17: Federated AgentX Nodes.

Subcommands
───────────
  agentx node start          — register this node with the peer network
  agentx node peers          — list all known peer nodes
  agentx node register       — register a specific peer URL
  agentx node send-event     — manually push a federated event to this node
"""
from __future__ import annotations

import asyncio
import logging

import typer

from agentx_sdk.nodes import NodesClient
from .config import load_config

logger = logging.getLogger(__name__)

node_app = typer.Typer(
    name="node",
    help="Manage federated AgentX nodes.",
    no_args_is_help=True,
)

_CONFIG_OPT = typer.Option("agent.yaml", "--config", "-c", help="Path to agent.yaml.")
_LIMIT_OPT  = typer.Option(20, "--limit", "-n", help="Maximum number of results.")


# ── Internal helper ───────────────────────────────────────────────────────────

def _get_client(config_file: str) -> NodesClient:
    """Return a NodesClient configured from agent.yaml."""
    cfg = load_config(config_file)
    return NodesClient(base_url=cfg.api_url, token=cfg.api_key)


def _fmt_node(n: dict, idx: int) -> None:
    """Print a single peer node result."""
    name   = n.get("node_name") or "(unnamed)"
    status = n.get("status", "?")
    trust  = n.get("trust_level", 0.5)
    typer.echo(
        f"  #{idx:>2}  [{status:8s}]  {name[:28]:<28}  {n['node_url']}\n"
        f"        trust={trust:.2f}  id={n['node_id']}"
    )


# ── agentx node start ─────────────────────────────────────────────────────────

@node_app.command("start")
def node_start(
    node_url: str = typer.Argument(..., help="Public URL of this node."),
    node_name: str = typer.Option(None, "--name", "-n", help="Node display name."),
    config_file: str = _CONFIG_OPT,
) -> None:
    """Register this node with the AgentX network."""
    client = _get_client(config_file)

    async def _run() -> None:
        node = await client.register_node(node_url=node_url, node_name=node_name)
        typer.echo("Node registered:")
        typer.echo(f"  ID:     {node['node_id']}")
        typer.echo(f"  URL:    {node['node_url']}")
        typer.echo(f"  Name:   {node.get('node_name') or '(none)'}")
        typer.echo(f"  Status: {node.get('status', 'active')}")
        typer.echo(f"  Trust:  {node.get('trust_level', 0.5):.2f}")

    asyncio.run(_run())


# ── agentx node peers ─────────────────────────────────────────────────────────

@node_app.command("peers")
def node_peers(
    active_only: bool = typer.Option(False, "--active", "-a", help="Show only active nodes."),
    config_file: str = _CONFIG_OPT,
) -> None:
    """List all known peer nodes."""
    client = _get_client(config_file)

    async def _run() -> None:
        nodes = await client.list_nodes(active_only=active_only)
        if not nodes:
            typer.echo("No peer nodes registered.")
            return
        typer.echo(f"\n{len(nodes)} peer node(s):\n")
        for i, n in enumerate(nodes, 1):
            _fmt_node(n, i)
            typer.echo("")

    asyncio.run(_run())


# ── agentx node register ──────────────────────────────────────────────────────

@node_app.command("register")
def node_register(
    node_url: str = typer.Argument(..., help="URL of the peer node to register."),
    node_name: str = typer.Option(None, "--name", "-n", help="Node display name."),
    config_file: str = _CONFIG_OPT,
) -> None:
    """Register a specific peer node URL."""
    client = _get_client(config_file)

    async def _run() -> None:
        node = await client.register_node(node_url=node_url, node_name=node_name)
        typer.echo(f"Peer registered: {node['node_url']}  (id={node['node_id']})")

    asyncio.run(_run())


# ── agentx node send-event ────────────────────────────────────────────────────

@node_app.command("send-event")
def node_send_event(
    event_type: str = typer.Argument(..., help="Event type (e.g. CONTRACT_COMPLETED)."),
    source_url: str = typer.Option(None, "--source", "-s", help="Source node URL."),
    config_file: str = _CONFIG_OPT,
) -> None:
    """Push a federated event to this node."""
    client = _get_client(config_file)

    async def _run() -> None:
        msg = await client.send_event(
            event_type=event_type,
            payload={},
            source_node_url=source_url,
        )
        typer.echo(f"Event accepted:")
        typer.echo(f"  message_id: {msg.get('message_id')}")
        typer.echo(f"  event_type: {msg.get('event_type')}")
        typer.echo(f"  direction:  {msg.get('direction')}")

    asyncio.run(_run())
