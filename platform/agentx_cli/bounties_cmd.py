"""
AgentX CLI — Bounties Commands
═══════════════════════════════
Phase 15: Autonomous Agent Markets.

Subcommands
───────────
  agentx bounties list      — list capability bounties
  agentx bounties create    — create a new bounty
  agentx bounties submit    — submit a solution to a bounty
  agentx bounties info      — show details for a bounty
  agentx bounties evaluate  — score a submission (bounty creator)
  agentx bounties distribute — distribute reward to the winner (bounty creator)
"""
from __future__ import annotations

import asyncio
import json
import logging

import typer

from agentx_sdk.markets import MarketsClient
from .config import load_config

logger = logging.getLogger(__name__)

bounties_app = typer.Typer(
    name="bounties",
    help="Manage AgentX capability bounties.",
    no_args_is_help=True,
)

_CONFIG_OPT = typer.Option("agent.yaml", "--config", "-c", help="Path to agent.yaml.")


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_client(config_file: str):
    """Return a MarketsClient configured from agent.yaml."""
    cfg = load_config(config_file)
    return MarketsClient(base_url=cfg.api_url, token=cfg.api_key)


# ── bounties list ─────────────────────────────────────────────────────────────

@bounties_app.command("list")
def bounties_list(
    status: str | None = typer.Option(None, "--status", help="Filter by status (open/closed/rewarded)."),
    capability: str | None = typer.Option(None, "--capability", help="Filter by capability."),
    config_file: str = _CONFIG_OPT,
):
    """List capability bounties."""
    client = _get_client(config_file)

    async def _run():
        return await client.list_bounties(status=status, capability=capability)

    try:
        bounties = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if not bounties:
        typer.echo("No bounties found.")
        return

    for b in bounties:
        typer.echo(
            f"  [{b.get('status','?')}]  {b.get('bounty_id','?')[:8]}  "
            f"{b.get('title','?')}  pool={b.get('reward_pool', 0)}"
        )


# ── bounties create ───────────────────────────────────────────────────────────

@bounties_app.command("create")
def bounties_create(
    title: str = typer.Option(..., "--title", help="Bounty title."),
    capability: str = typer.Option(..., "--capability", help="Capability required."),
    reward_pool: int = typer.Option(..., "--reward-pool", help="Token reward pool."),
    description: str = typer.Option("", "--description", help="Optional description."),
    deadline: str | None = typer.Option(None, "--deadline", help="ISO-8601 deadline."),
    config_file: str = _CONFIG_OPT,
):
    """Create a new capability bounty."""
    client = _get_client(config_file)

    async def _run():
        return await client.create_bounty(
            title=title,
            capability_required=capability,
            reward_pool=reward_pool,
            description=description,
            deadline=deadline,
        )

    try:
        bounty = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"Bounty created — id={bounty.get('bounty_id')}  "
        f"title='{bounty.get('title')}'  pool={bounty.get('reward_pool')}  "
        f"status={bounty.get('status')}"
    )


# ── bounties submit ───────────────────────────────────────────────────────────

@bounties_app.command("submit")
def bounties_submit(
    bounty_id: str = typer.Option(..., "--id", help="Bounty UUID."),
    solution: str = typer.Option(..., "--solution", help="JSON-encoded solution data."),
    summary: str | None = typer.Option(None, "--summary", help="Optional summary."),
    config_file: str = _CONFIG_OPT,
):
    """Submit a solution to a bounty."""
    try:
        solution_data = json.loads(solution)
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: --solution must be valid JSON: {exc}", err=True)
        raise typer.Exit(code=1)

    client = _get_client(config_file)

    async def _run():
        return await client.submit_solution(
            bounty_id=bounty_id,
            solution_data=solution_data,
            summary=summary,
        )

    try:
        submission = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"Submission created — id={submission.get('submission_id')}  "
        f"bounty={bounty_id}  status={submission.get('status')}"
    )


# ── bounties info ─────────────────────────────────────────────────────────────

@bounties_app.command("info")
def bounties_info(
    bounty_id: str = typer.Argument(..., help="Bounty UUID."),
    config_file: str = _CONFIG_OPT,
):
    """Show full details for a single bounty."""
    client = _get_client(config_file)

    async def _run():
        return await client.get_bounty(bounty_id)

    try:
        bounty = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Bounty: {bounty.get('bounty_id')}")
    typer.echo(f"  Title:       {bounty.get('title')}")
    typer.echo(f"  Status:      {bounty.get('status')}")
    typer.echo(f"  Capability:  {bounty.get('capability_required')}")
    typer.echo(f"  Reward pool: {bounty.get('reward_pool')}")
    typer.echo(f"  Creator:     {bounty.get('creator_did')}")
    if bounty.get("deadline"):
        typer.echo(f"  Deadline:    {bounty.get('deadline')}")
    if bounty.get("winner_submission_id"):
        typer.echo(f"  Winner:      {bounty.get('winner_submission_id')}")


# ── bounties evaluate ─────────────────────────────────────────────────────────

@bounties_app.command("evaluate")
def bounties_evaluate(
    bounty_id: str = typer.Option(..., "--bounty-id", help="Bounty UUID."),
    submission_id: str = typer.Option(..., "--submission-id", help="Submission UUID."),
    score: float = typer.Option(..., "--score", help="Score in [0.0, 1.0]."),
    config_file: str = _CONFIG_OPT,
):
    """Score a submission (bounty creator only)."""
    client = _get_client(config_file)

    async def _run():
        return await client.evaluate_submission(
            bounty_id=bounty_id,
            submission_id=submission_id,
            score=score,
        )

    try:
        submission = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"Submission evaluated — id={submission.get('submission_id')}  "
        f"score={submission.get('score')}  status={submission.get('status')}"
    )


# ── bounties distribute ───────────────────────────────────────────────────────

@bounties_app.command("distribute")
def bounties_distribute(
    bounty_id: str = typer.Option(..., "--id", help="Bounty UUID."),
    config_file: str = _CONFIG_OPT,
):
    """Distribute the reward pool to the winning submission (bounty creator only)."""
    client = _get_client(config_file)

    async def _run():
        return await client.distribute_rewards(bounty_id=bounty_id)

    try:
        reward = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"Rewards distributed — bounty={bounty_id}  "
        f"winner={reward.get('recipient_did')}  "
        f"amount={reward.get('amount')}"
    )
