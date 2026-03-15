"""
AgentX CLI — init command
══════════════════════════
Phase 14: Agent CLI

``agentx init <agent_name>``

Creates a new AgentX agent project directory with the scaffolding files
needed to build, configure, and run an agent.

Generated structure
───────────────────
    <agent_name>/
    ├── agent.py          Core agent logic; edit to add contract handlers.
    ├── agent.yaml        Project configuration (API URL, credentials, DID …).
    └── requirements.txt  Python dependencies for distribution.

Usage
─────
    agentx init research-agent
    agentx init data_collector --api-url https://agentx.example.com
"""
from __future__ import annotations

import re
from pathlib import Path

import typer

from .config import DEFAULT_API_URL, AgentConfig, save_config

# ── Template directory ────────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert an agent name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[_\s]+", "-", slug)
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "agent"


def _render_template(template_path: Path, substitutions: dict[str, str]) -> str:
    """Read a template file and apply ``{{key}}`` substitutions."""
    content = template_path.read_text(encoding="utf-8")
    for key, value in substitutions.items():
        content = content.replace("{{" + key + "}}", value)
    return content


# ── Command ───────────────────────────────────────────────────────────────────

def init_agent(
    agent_name: str = typer.Argument(
        ...,
        help="Name of the new agent (used as directory name and agent identifier).",
    ),
    api_url: str = typer.Option(
        DEFAULT_API_URL,
        "--api-url",
        help="AgentX platform API URL.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing project directory.",
    ),
) -> None:
    """
    Initialise a new AgentX agent project.

    Creates a project directory named ``<agent_name>`` containing:

    \b
      agent.py          — Agent logic with an example contract handler.
      agent.yaml        — Project configuration (API URL, DID, capabilities).
      requirements.txt  — Python dependencies.
    """
    slug        = _slugify(agent_name)
    project_dir = Path(agent_name)

    # ── Guard: directory already exists ───────────────────────────────────────
    if project_dir.exists() and not force:
        typer.echo(
            f"[error] Directory '{agent_name}' already exists.\n"
            "Use --force / -f to overwrite.",
            err=True,
        )
        raise typer.Exit(1)

    # ── Create directory ──────────────────────────────────────────────────────
    project_dir.mkdir(parents=True, exist_ok=True)

    subs = {
        "agent_name": agent_name,
        "agent_slug": slug,
    }

    # ── Write agent.py ────────────────────────────────────────────────────────
    agent_py = _render_template(_TEMPLATES_DIR / "agent_template.py", subs)
    (project_dir / "agent.py").write_text(agent_py, encoding="utf-8")

    # ── Write agent.yaml ──────────────────────────────────────────────────────
    config = AgentConfig(
        name=agent_name,
        api_url=api_url,
        api_key=None,
        did=f"did:agentx:{slug}",
        agent_id=None,
        capabilities=["example"],
    )
    save_config(config, str(project_dir / "agent.yaml"))

    # ── Write requirements.txt ────────────────────────────────────────────────
    req_txt = _render_template(_TEMPLATES_DIR / "requirements_template.txt", subs)
    (project_dir / "requirements.txt").write_text(req_txt, encoding="utf-8")

    # ── Success output ────────────────────────────────────────────────────────
    typer.echo(f"\n✓  Agent project created: {agent_name}/\n")
    typer.echo("  Files created:")
    typer.echo(f"    {agent_name}/agent.py       — agent logic")
    typer.echo(f"    {agent_name}/agent.yaml     — configuration")
    typer.echo(f"    {agent_name}/requirements.txt\n")
    typer.echo("Next steps:")
    typer.echo(f"  cd {agent_name}")
    typer.echo("  # Edit agent.yaml — set api_url and api_key")
    typer.echo("  agentx run\n")
