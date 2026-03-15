"""
AgentX CLI — run command
═════════════════════════
Phase 14: Agent CLI

``agentx run``

Loads the agent project from the current directory and starts the
AgentRuntime loop.

Execution flow
──────────────
  1. Load ``agent.yaml`` (fail fast if missing).
  2. Dynamically import ``agent.py`` and extract the ``agent`` object.
  3. Construct an ``AgentXClient`` from config.
  4. Construct an ``AgentRuntime`` wrapping the agent and client.
  5. Call ``asyncio.run(runtime.start())`` — runs until Ctrl-C.

Usage
─────
    cd my_agent/
    agentx run
    agentx run --config agent.yaml
    agentx run --poll-interval 10
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

import typer

from agentx_sdk import AgentRuntime
from agentx_sdk.client import AgentXClient

from .config import CONFIG_FILENAME, load_config

logger = logging.getLogger(__name__)


# ── Command ───────────────────────────────────────────────────────────────────

def run_agent(
    config_file: str = typer.Option(
        CONFIG_FILENAME,
        "--config",
        "-c",
        help="Path to agent.yaml configuration file.",
    ),
    agent_file: str = typer.Option(
        "agent.py",
        "--agent",
        "-a",
        help="Path to the agent Python module.",
    ),
    poll_interval: float = typer.Option(
        5.0,
        "--poll-interval",
        "-p",
        help="Seconds between contract-polling cycles.",
    ),
    no_register: bool = typer.Option(
        False,
        "--no-register",
        help="Skip automatic agent registration on startup.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging.",
    ),
) -> None:
    """
    Start the agent runtime loop.

    Loads agent.yaml and agent.py from the current directory (or from the
    paths specified by --config and --agent), then starts the polling runtime
    until interrupted with Ctrl-C.
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )

    # ── Step 1: Load config ───────────────────────────────────────────────────
    try:
        config = load_config(config_file)
    except FileNotFoundError as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"[error] Failed to load config: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Agent: {config.name}")
    typer.echo(f"API:   {config.effective_api_url}")

    # ── Step 2: Import agent.py ───────────────────────────────────────────────
    agent_path = Path(agent_file)
    if not agent_path.exists():
        typer.echo(
            f"[error] Agent module not found: '{agent_file}'\n"
            "Make sure you are running agentx run from inside the agent project directory.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        agent = _load_agent_module(agent_path)
    except AttributeError:
        typer.echo(
            f"[error] '{agent_file}' does not define an 'agent' variable.\n"
            "Make sure your agent.py contains: agent = Agent(...)",
            err=True,
        )
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"[error] Failed to load agent module: {exc}", err=True)
        raise typer.Exit(1)

    # ── Step 3: Build client ──────────────────────────────────────────────────
    client = AgentXClient(
        base_url=config.effective_api_url,
        api_key=config.effective_api_key,
    )

    # ── Step 4: Build runtime ─────────────────────────────────────────────────
    runtime = AgentRuntime(
        agent=agent,
        client=client,
        poll_interval=poll_interval,
        auto_register=not no_register,
    )

    # ── Step 5: Start ─────────────────────────────────────────────────────────
    typer.echo(f"\nStarting agent '{config.name}' — press Ctrl-C to stop.\n")
    try:
        asyncio.run(runtime.start())
    except KeyboardInterrupt:
        typer.echo("\nAgent stopped.")
    except Exception as exc:
        typer.echo(f"\n[error] Runtime error: {exc}", err=True)
        if verbose:
            logger.exception("Runtime error details")
        raise typer.Exit(1)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_agent_module(agent_path: Path):
    """
    Dynamically import ``agent.py`` and return the ``agent`` object.

    Uses importlib so the module can be loaded from an arbitrary file path
    (not necessarily on ``sys.path``).

    Args:
        agent_path: Path to the agent.py file.

    Returns:
        The ``agent`` attribute from the loaded module.

    Raises:
        AttributeError: The module has no ``agent`` variable.
        Exception:      Any import/execution error from the module.
    """
    spec   = importlib.util.spec_from_file_location("_agentx_user_agent", str(agent_path))
    module = importlib.util.module_from_spec(spec)
    # Add module's directory to sys.path so relative imports inside agent.py work.
    agent_dir = str(agent_path.parent.resolve())
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    spec.loader.exec_module(module)
    return module.agent
