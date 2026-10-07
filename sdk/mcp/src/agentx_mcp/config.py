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
import tempfile
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


def save_credentials(url: str, agent_did: str, token: str, refresh_token: str | None) -> Path:
    """Store the pair for `url` in the credentials file, keeping other entries.

    The file is written to a temporary file created with mode 0600 and then
    renamed over the old one, so it is never readable by others, not even
    briefly, and a crash cannot leave half a file. A directory this creates is
    mode 0700, and the default ~/.agentx directory is always tightened to 0700.
    """
    path = credentials_path()
    data = _read_file()
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
    accounts[url] = {"agent_did": agent_did, "token": token, "refresh_token": refresh_token}
    payload = json.dumps({"version": 1, "accounts": accounts}, indent=2)
    try:
        ensure_credentials_dir()
        fd, tmp = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)  # mode 0600
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise CredentialsError(
            f"Could not write the credentials file {path}: {type(exc).__name__}"
        ) from None
    return path


def ensure_credentials_dir() -> Path:
    """Create the credentials file's directory (0700) if needed; return it."""
    path = credentials_path()
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
        os.chmod(parent, 0o700)  # mkdir's mode is masked by the umask
    elif parent == Path.home() / ".agentx":
        os.chmod(parent, 0o700)
    return parent
