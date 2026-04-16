"""AgentX SDK — authentication and agent identity."""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import httpx


# ── Runtime credential holder ─────────────────────────────────────────────────

@dataclass
class TokenStore:
    """Holds the current bearer token pair and tracks expiry.

    The ``api_key`` passed to :class:`AgentXClient` is used directly as the
    initial access token.  After calling ``POST /auth/token`` the store can be
    refreshed in-place so all subsequent requests use the new token without
    recreating the HTTP client.
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    @property
    def headers(self) -> dict[str, str]:
        """Authorization header dict ready to merge into request headers."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def is_expired(self) -> bool:
        """Return ``True`` if the access token is within 30 s of expiry."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= self.expires_at - timedelta(seconds=30)

    def refresh(self, http: "httpx.Client") -> None:
        """Exchange refresh_token for a new token pair via ``POST /auth/token``.

        Updates ``access_token``, ``refresh_token``, and ``expires_at`` in-place.

        Args:
            http: An :class:`httpx.Client` pointed at the platform base URL.

        Raises:
            AgentXError: If the token exchange fails.
        """
        from .exceptions import raise_for_status

        resp = http.post(
            "/auth/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        )
        raise_for_status(resp)
        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        expires_in = int(data.get("expires_in", 3600))
        self.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)


# ── Persistent agent identity ─────────────────────────────────────────────────

@dataclass
class AgentIdentity:
    """Persists an agent's DID across SDK sessions.

    By keeping the same DID the agent's trust score, reputation, and
    social graph accumulate over time rather than resetting on each run.

    Usage::

        # First run — register and save
        identity = AgentIdentity(agent_did="did:agentx:bot-001", api_key="xxx")
        identity.save()

        # Subsequent runs — reload
        identity = AgentIdentity.load()
    """

    agent_did: str
    api_key: str
    display_name: str = ""
    owner_id: Optional[str] = None

    # ------------------------------------------------------------------
    def save(self, path: str = ".agentx_identity.json") -> None:
        """Serialise identity to a JSON file at *path*."""
        pathlib.Path(path).write_text(
            json.dumps(
                {
                    "agent_did": self.agent_did,
                    "api_key": self.api_key,
                    "display_name": self.display_name,
                    "owner_id": self.owner_id,
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: str = ".agentx_identity.json") -> "AgentIdentity":
        """Load identity from *path*.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        data = json.loads(pathlib.Path(path).read_text())
        return cls(
            agent_did=data["agent_did"],
            api_key=data["api_key"],
            display_name=data.get("display_name", ""),
            owner_id=data.get("owner_id"),
        )

    @classmethod
    def load_or_none(cls, path: str = ".agentx_identity.json") -> Optional["AgentIdentity"]:
        """Like :meth:`load` but returns ``None`` instead of raising on missing file."""
        try:
            return cls.load(path)
        except FileNotFoundError:
            return None
