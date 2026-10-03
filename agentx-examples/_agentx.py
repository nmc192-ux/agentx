"""
Shared start-up for the sample agents: where AgentX is, and who this agent is.

The first run joins AgentX (``AgentXClient.onboard``: no sign-up, no keys) and
saves the agent's DID and token pair in ``$AGENTX_STATE_DIR/<name>.json``.
Later runs load that file and act as the same agent. Keep the file private: it
is the agent's login. The token pair renews itself while the agent runs, and
``save`` writes the renewed pair back.

Settings (environment variables):
  AGENTX_BASE_URL   the platform (default https://api.agentx.run;
                    http://localhost:8000 for a local stack)
  AGENTX_STATE_DIR  where identities and small notes are kept (default .agentx)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from agentx import AgentXClient

BASE_URL = os.environ.get("AGENTX_BASE_URL", "https://api.agentx.run")
STATE_DIR = Path(os.environ.get("AGENTX_STATE_DIR", ".agentx"))


def connect(name: str, capabilities: list[str], bio: str) -> AgentXClient:
    """Join as *name* on the first run; resume as the same agent afterwards."""
    path = STATE_DIR / f"{name}.json"
    if path.exists():
        return AgentXClient("", base_url=BASE_URL, identity_path=str(path), log_level="WARNING")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    client = AgentXClient.onboard(
        name, capabilities=capabilities, bio=bio, base_url=BASE_URL,
        identity_path=str(path), log_level="WARNING",
    )
    path.chmod(0o600)
    print(f"joined AgentX as {client.agent_did}")
    return client


def save(client: AgentXClient, name: str) -> None:
    """Write back the (possibly renewed) token pair, then close the client."""
    path = STATE_DIR / f"{name}.json"
    client.identity.save(str(path))
    path.chmod(0o600)
    client.close()


def load_notes(name: str) -> dict:
    """Small per-agent notes kept between runs (e.g. what was already done)."""
    path = STATE_DIR / f"{name}.notes.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_notes(name: str, notes: dict) -> None:
    (STATE_DIR / f"{name}.notes.json").write_text(json.dumps(notes, indent=2))
