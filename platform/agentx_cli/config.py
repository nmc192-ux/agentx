"""
AgentX CLI — Configuration Module
════════════════════════════════════
Phase 14: Agent CLI

Responsible for loading, validating, and persisting the ``agent.yaml``
configuration file that lives in every AgentX project directory.

Config file format (agent.yaml)
────────────────────────────────
    name: my_agent
    api_url: http://localhost:8000
    api_key: null            # JWT token (optional)
    did: null                # set after first run
    agent_id: null           # set after first run + registration
    capabilities:
      - example

Public API
──────────
    load_config(path)  → AgentConfig
    save_config(cfg, path)
    default_config(name) → AgentConfig

Environment variable overrides
────────────────────────────────
    AGENTX_API_URL     overrides api_url
    AGENTX_API_KEY     overrides api_key
    AGENTX_AGENT_DID   overrides did
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ── Constants ──────────────────────────────────────────────────────────────────

CONFIG_FILENAME = "agent.yaml"
DEFAULT_API_URL = "http://localhost:8000"


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    """
    Parsed representation of an ``agent.yaml`` project configuration.

    All fields map 1-to-1 to YAML keys.  After ``agentx init`` the file
    contains placeholder ``null`` values; they are filled in at runtime or
    by the user.
    """
    name: str
    api_url: str = DEFAULT_API_URL
    api_key: str | None = None
    did: str | None = None
    agent_id: str | None = None
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for YAML dumping."""
        return {
            "name":         self.name,
            "api_url":      self.api_url,
            "api_key":      self.api_key,
            "did":          self.did,
            "agent_id":     self.agent_id,
            "capabilities": self.capabilities,
        }

    @property
    def effective_api_url(self) -> str:
        """Return api_url, honouring AGENTX_API_URL env var override."""
        return os.environ.get("AGENTX_API_URL", self.api_url) or DEFAULT_API_URL

    @property
    def effective_api_key(self) -> str | None:
        """Return api_key, honouring AGENTX_API_KEY env var override."""
        return os.environ.get("AGENTX_API_KEY") or self.api_key

    @property
    def effective_did(self) -> str | None:
        """Return did, honouring AGENTX_AGENT_DID env var override."""
        return os.environ.get("AGENTX_AGENT_DID") or self.did


# ── Public helpers ────────────────────────────────────────────────────────────

def load_config(path: str = CONFIG_FILENAME) -> AgentConfig:
    """
    Load and parse an ``agent.yaml`` configuration file.

    Args:
        path: Path to the YAML file (default ``"agent.yaml"``).

    Returns:
        AgentConfig populated from the file.

    Raises:
        FileNotFoundError: The file does not exist.
        ValueError:        The file is empty or missing the required ``name`` key.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: '{path}'\n"
            "Run  agentx init <agent-name>  to create a new agent project."
        )

    with config_path.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    if not raw.get("name"):
        raise ValueError(f"Configuration file '{path}' is missing required key: name")

    return AgentConfig(
        name=raw["name"],
        api_url=raw.get("api_url", DEFAULT_API_URL) or DEFAULT_API_URL,
        api_key=raw.get("api_key"),
        did=raw.get("did"),
        agent_id=raw.get("agent_id"),
        capabilities=raw.get("capabilities") or [],
    )


def save_config(config: AgentConfig, path: str = CONFIG_FILENAME) -> None:
    """
    Serialise an AgentConfig and write it to ``agent.yaml``.

    Args:
        config: The config object to persist.
        path:   Target file path (default ``"agent.yaml"``).
    """
    config_path = Path(path)
    with config_path.open("w") as fh:
        yaml.dump(
            config.to_dict(),
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def default_config(name: str) -> AgentConfig:
    """
    Build a fresh AgentConfig for a newly initialised agent.

    Args:
        name: Agent name (used as the primary identifier).

    Returns:
        AgentConfig with sensible defaults.
    """
    # Generate a deterministic placeholder DID from the agent name.
    slug = name.lower().replace(" ", "-").replace("_", "-")
    return AgentConfig(
        name=name,
        api_url=DEFAULT_API_URL,
        api_key=None,
        did=f"did:agentx:{slug}",
        agent_id=None,
        capabilities=["example"],
    )
