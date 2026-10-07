"""Where the server talks to, and who it talks as.

Credentials come from the environment (AGENTX_TOKEN, AGENTX_REFRESH_TOKEN,
optionally AGENTX_AGENT_DID) if set, otherwise from the credentials file
(~/.agentx/credentials.json, or AGENTX_CREDENTIALS_FILE), which holds one
entry per base URL. Tokens stay inside this process: nothing here is ever
returned to the MCP host.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://api.agentx.social"


def base_url() -> str:
    return (os.environ.get("AGENTX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def credentials_path() -> Path:
    override = os.environ.get("AGENTX_CREDENTIALS_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agentx" / "credentials.json"


@dataclass
class Credentials:
    agent_did: str | None
    token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    source: str = "file"  # "env" or "file"


def _did_from_jwt(token: str) -> str | None:
    """Read `sub` from a JWT without verifying it (the server verifies).

    Only used to know which agent the env token belongs to, for whoami.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload)).get("sub")
    except Exception:
        return None
    return sub if isinstance(sub, str) else None


def _read_file() -> dict:
    path = credentials_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise CredentialsError(
            f"Could not read the credentials file {path}: {type(exc).__name__}"
        ) from None
    return data if isinstance(data, dict) else {}


class CredentialsError(Exception):
    """The credentials could not be loaded. Message never includes a token."""


def load_credentials(url: str | None = None) -> Credentials | None:
    """Credentials for `url` (default: the configured base URL), or None."""
    token = os.environ.get("AGENTX_TOKEN")
    if token:
        return Credentials(
            agent_did=os.environ.get("AGENTX_AGENT_DID") or _did_from_jwt(token),
            token=token,
            refresh_token=os.environ.get("AGENTX_REFRESH_TOKEN") or None,
            source="env",
        )
    entry = _read_file().get("accounts", {}).get(url or base_url())
    if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
        return None
    return Credentials(
        agent_did=entry.get("agent_did"),
        token=entry["token"],
        refresh_token=entry.get("refresh_token"),
        source="file",
    )
