"""
AgentX CLI — wallet commands
══════════════════════════════
Phase 14: Agent CLI

Subcommand group ``agentx wallet`` for interacting with the AgentX token
economy via the SDK's WalletClient.

Subcommands
───────────
    agentx wallet balance   [--agent-id UUID]
    agentx wallet transfer  <to_agent_id> <amount>
    agentx wallet stake     <amount>  [--agent-id UUID]
    agentx wallet history   [--agent-id UUID] [--limit N]

All commands read API URL and credentials from ``agent.yaml`` (config module)
and can be overridden with environment variables (AGENTX_API_URL, AGENTX_API_KEY).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import typer

from agentx_sdk.wallet import WalletClient

from .config import CONFIG_FILENAME, load_config

wallet_app = typer.Typer(
    name="wallet",
    help="Manage your AgentX token wallet — balance, transfers, and stakes.",
    no_args_is_help=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_and_id(
    config_file: str,
    agent_id_override: str | None,
) -> tuple[WalletClient, str]:
    """Load config, build WalletClient, and resolve the agent_id to use."""
    try:
        config = load_config(config_file)
    except FileNotFoundError as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)

    aid = agent_id_override or config.agent_id
    if not aid:
        typer.echo(
            "[error] No agent_id found.\n"
            "Either set agent_id in agent.yaml (run 'agentx run' once to register)\n"
            "or pass --agent-id <uuid>.",
            err=True,
        )
        raise typer.Exit(1)

    client = WalletClient(
        base_url=config.effective_api_url,
        token=config.effective_api_key or "",
    )
    return client, aid


# ── balance ───────────────────────────────────────────────────────────────────

@wallet_app.command("balance")
def wallet_balance(
    agent_id: Optional[str] = typer.Option(
        None, "--agent-id", "-a", help="Agent UUID (defaults to agent_id in agent.yaml)."
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Show the current token balance for this agent."""
    client, aid = _get_client_and_id(config_file, agent_id)

    async def _run() -> None:
        balance = await client.get_balance(aid)
        typer.echo(f"Balance: {balance:,} tokens  (agent_id={aid})")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── transfer ──────────────────────────────────────────────────────────────────

@wallet_app.command("transfer")
def wallet_transfer(
    to_agent_id: str = typer.Argument(..., help="Recipient agent UUID."),
    amount: int = typer.Argument(..., help="Number of tokens to transfer."),
    from_agent_id: Optional[str] = typer.Option(
        None,
        "--from",
        "-f",
        help="Sender agent UUID (defaults to agent_id in agent.yaml).",
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Transfer tokens from this agent to another agent."""
    client, fid = _get_client_and_id(config_file, from_agent_id)

    async def _run() -> None:
        tx = await client.transfer(
            from_agent_id=fid,
            to_agent_id=to_agent_id,
            amount=amount,
        )
        tx_id = tx.get("transaction_id") or tx.get("tx_id", "unknown")
        typer.echo(f"Transfer complete — tx_id={tx_id}  amount={amount:,}  to={to_agent_id}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── stake ─────────────────────────────────────────────────────────────────────

@wallet_app.command("stake")
def wallet_stake(
    amount: int = typer.Argument(..., help="Number of tokens to stake."),
    agent_id: Optional[str] = typer.Option(
        None, "--agent-id", "-a", help="Agent UUID (defaults to agent_id in agent.yaml)."
    ),
    locked_until: Optional[str] = typer.Option(
        None,
        "--locked-until",
        help="ISO-8601 datetime until which stake is locked (e.g. 2026-12-31T00:00:00Z).",
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Stake tokens to increase voting power and reputation weight."""
    client, aid = _get_client_and_id(config_file, agent_id)

    async def _run() -> None:
        stake = await client.stake(
            agent_id=aid,
            amount=amount,
            locked_until=locked_until,
        )
        stake_id = stake.get("stake_id", "unknown")
        typer.echo(
            f"Stake created — stake_id={stake_id}  amount={amount:,}  agent_id={aid}"
        )
        if locked_until:
            typer.echo(f"  Locked until: {locked_until}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── history ───────────────────────────────────────────────────────────────────

@wallet_app.command("history")
def wallet_history(
    agent_id: Optional[str] = typer.Option(
        None, "--agent-id", "-a", help="Agent UUID (defaults to agent_id in agent.yaml)."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of records to return."),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Show recent token transaction history for this agent."""
    client, aid = _get_client_and_id(config_file, agent_id)

    async def _run() -> None:
        txs = await client.get_transactions(agent_id=aid, limit=limit)
        if not txs:
            typer.echo(f"No transactions found for agent {aid}.")
            return

        typer.echo(f"Transaction history for agent_id={aid}:")
        typer.echo(f"{'Type':<20} {'Amount':>10}  {'ID'}")
        typer.echo("─" * 60)
        for tx in txs:
            tx_type = tx.get("tx_type") or tx.get("transaction_type", "transfer")
            amount  = tx.get("amount", 0)
            tx_id   = str(tx.get("transaction_id") or tx.get("tx_id", ""))[:16]
            typer.echo(f"{tx_type:<20} {amount:>10}  {tx_id}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)
