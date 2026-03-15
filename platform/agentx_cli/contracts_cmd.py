"""
AgentX CLI — contracts commands
═════════════════════════════════
Phase 14: Agent CLI

Subcommand group ``agentx contracts`` for managing contracts on the AgentX
platform via the SDK's ContractsClient.

Subcommands
───────────
    agentx contracts list    [--status STATUS]
    agentx contracts create  --title TITLE --capability CAP --budget AMOUNT
    agentx contracts submit  --id CONTRACT_ID --result JSON_STRING
    agentx contracts complete --id CONTRACT_ID
    agentx contracts info    <contract_id>

All commands read API URL and credentials from ``agent.yaml`` (config module)
and can be overridden with environment variables.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from agentx_sdk.contracts import ContractsClient

from .config import CONFIG_FILENAME, load_config

contracts_app = typer.Typer(
    name="contracts",
    help="List, create, and manage AgentX contracts.",
    no_args_is_help=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client(config_file: str) -> ContractsClient:
    """Load config and build a ContractsClient."""
    try:
        config = load_config(config_file)
    except FileNotFoundError as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)

    return ContractsClient(
        base_url=config.effective_api_url,
        token=config.effective_api_key or "",
    )


def _print_contract(contract: dict) -> None:
    """Pretty-print a single contract record."""
    cid    = contract.get("contract_id", "?")
    title  = contract.get("title", "untitled")
    status = contract.get("status", "?")
    budget = contract.get("budget", 0)
    cap    = contract.get("capability_required", "")
    typer.echo(f"  [{status:>10}]  {title:<35}  {budget:>8} tokens  ({cap})  id={cid}")


# ── list ──────────────────────────────────────────────────────────────────────

@contracts_app.command("list")
def contracts_list(
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: open | assigned | submitted | completed | disputed.",
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """List contracts on the platform, optionally filtered by status."""
    client = _get_client(config_file)

    async def _run() -> None:
        contracts = await client.list(status=status)
        if not contracts:
            label = f"with status '{status}'" if status else ""
            typer.echo(f"No contracts found {label}.")
            return

        label = f" (status={status})" if status else ""
        typer.echo(f"Contracts{label}:  {len(contracts)} result(s)\n")
        for c in contracts:
            _print_contract(c)

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── create ────────────────────────────────────────────────────────────────────

@contracts_app.command("create")
def contracts_create(
    title: str = typer.Option(..., "--title", "-t", help="Short descriptive title."),
    capability: str = typer.Option(
        ..., "--capability", "--cap", "-k", help="Capability slug the executor must advertise."
    ),
    budget: int = typer.Option(..., "--budget", "-b", help="Token budget for the contract."),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Detailed description of the work required."
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Create a new contract on the platform."""
    client = _get_client(config_file)

    async def _run() -> None:
        contract = await client.create(
            title=title,
            capability_required=capability,
            budget=budget,
            description=description,
        )
        cid = contract.get("contract_id", "?")
        typer.echo(f"Contract created — id={cid}  title='{title}'  budget={budget:,}  status=open")
        typer.echo(f"  Capability required: {capability}")
        if description:
            typer.echo(f"  Description: {description}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── submit ────────────────────────────────────────────────────────────────────

@contracts_app.command("submit")
def contracts_submit(
    contract_id: str = typer.Option(..., "--id", "-i", help="Contract UUID."),
    result: str = typer.Option(
        ...,
        "--result",
        "-r",
        help='Result payload as a JSON string, e.g. \'{"rows":42}\'.',
    ),
    summary: Optional[str] = typer.Option(
        None, "--summary", "-s", help="Optional human-readable summary of the result."
    ),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Submit a result for an assigned contract."""
    # Parse result JSON
    try:
        result_data: dict = json.loads(result)
    except json.JSONDecodeError as exc:
        typer.echo(f"[error] --result must be valid JSON: {exc}", err=True)
        raise typer.Exit(1)

    client = _get_client(config_file)

    async def _run() -> None:
        response = await client.submit_result(
            contract_id=contract_id,
            result_data=result_data,
            summary=summary,
        )
        rid = response.get("result_id", "?")
        typer.echo(f"Result submitted — result_id={rid}  contract_id={contract_id}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── complete ──────────────────────────────────────────────────────────────────

@contracts_app.command("complete")
def contracts_complete(
    contract_id: str = typer.Option(..., "--id", "-i", help="Contract UUID."),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Mark a submitted contract as completed (contract creator only)."""
    client = _get_client(config_file)

    async def _run() -> None:
        contract = await client.complete(contract_id=contract_id)
        status = contract.get("status", "?")
        typer.echo(f"Contract completed — id={contract_id}  status={status}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)


# ── info ──────────────────────────────────────────────────────────────────────

@contracts_app.command("info")
def contracts_info(
    contract_id: str = typer.Argument(..., help="Contract UUID to inspect."),
    config_file: str = typer.Option(
        CONFIG_FILENAME, "--config", "-c", help="Path to agent.yaml."
    ),
) -> None:
    """Show full details for a single contract."""
    client = _get_client(config_file)

    async def _run() -> None:
        contract = await client.get(contract_id=contract_id)
        typer.echo(f"Contract details — id={contract_id}")
        typer.echo("─" * 50)
        for key, value in contract.items():
            typer.echo(f"  {key:<25} {value}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)
