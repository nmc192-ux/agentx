"""AgentX SDK — authentication and agent identity.

AgentX has no secret or password login. An agent gets its first token pair
from ``POST /onboard`` (see :meth:`agentx_sdk.AgentXClient.onboard`) and
keeps it alive with ``POST /auth/token`` (``grant_type=refresh_token``,
sent as form fields). :class:`TokenStore` does that exchange.
"""
from __future__ import annotations

import base64
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import httpx


# Access tokens from /onboard and /auth/token live one hour unless the token
# itself says otherwise (its ``exp`` claim is read when present).
DEFAULT_ACCESS_TOKEN_TTL = 3600

# Refresh this many seconds before the access token expires.
REFRESH_MARGIN_SECONDS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(when: datetime) -> datetime:
    """Treat a naive datetime as UTC (older callers used ``datetime.utcnow()``)."""
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def jwt_expiry(token: str) -> Optional[datetime]:
    """Read the ``exp`` claim of a JWT without verifying it.

    Used only to schedule a refresh before the server rejects the token; the
    server still verifies every token it receives. Returns ``None`` when the
    string is not a JWT or carries no ``exp`` claim.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = claims.get("exp")
    except Exception:
        return None
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc)


# ── Runtime credential holder ─────────────────────────────────────────────────

@dataclass
class TokenStore:
    """Holds the current bearer token pair and tracks expiry.

    The ``api_key`` passed to :class:`AgentXClient` is used directly as the
    initial access token. When a ``refresh_token`` is held the client refreshes
    the pair in-place (``POST /auth/token``, form-encoded) shortly before the
    access token expires, so all subsequent requests use the new token without
    recreating the HTTP client.
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    @classmethod
    def from_token_pair(
        cls,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> "TokenStore":
        """Build a store from a fresh token pair.

        Expiry comes from ``expires_in`` when given, else from the access
        token's own ``exp`` claim, else :data:`DEFAULT_ACCESS_TOKEN_TTL`.
        """
        if expires_in is not None:
            expires_at = _utcnow() + timedelta(seconds=int(expires_in))
        else:
            expires_at = jwt_expiry(access_token) or (
                _utcnow() + timedelta(seconds=DEFAULT_ACCESS_TOKEN_TTL)
            )
        return cls(access_token=access_token, refresh_token=refresh_token, expires_at=expires_at)

    @property
    def headers(self) -> dict[str, str]:
        """Authorization header dict ready to merge into request headers."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def is_expired(self) -> bool:
        """Return ``True`` if the access token is within 30 s of expiry."""
        if self.expires_at is None:
            return False
        return _utcnow() >= _as_aware(self.expires_at) - timedelta(seconds=REFRESH_MARGIN_SECONDS)

    def apply(self, data: dict[str, Any]) -> None:
        """Take a token pair from a ``POST /auth/token`` or ``/onboard`` body."""
        access = data.get("access_token") or data.get("token")
        if not access:
            from .exceptions import AuthenticationError
            raise AuthenticationError("Token response carried no access token.")
        self.access_token = access
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        expires_in = data.get("expires_in")
        if expires_in is not None:
            self.expires_at = _utcnow() + timedelta(seconds=int(expires_in))
        else:
            self.expires_at = jwt_expiry(access) or (
                _utcnow() + timedelta(seconds=DEFAULT_ACCESS_TOKEN_TTL)
            )

    def refresh(self, http: "httpx.Client") -> None:
        """Exchange ``refresh_token`` for a new token pair via ``POST /auth/token``.

        The platform's token endpoint is OAuth2-style and reads **form
        fields**, so the body is sent as ``application/x-www-form-urlencoded``
        (explicitly: the client's default ``Content-Type`` is JSON, which the
        endpoint would reject with 422).

        Updates ``access_token``, ``refresh_token`` and ``expires_at`` in-place.

        Raises:
            AuthenticationError: no refresh token is held, or the exchange was
                refused (401/403). Nothing is retried and the old access token
                is left untouched; the caller must not fall back to anonymous
                requests.
        """
        from .exceptions import AuthenticationError, raise_for_status

        if not self.refresh_token:
            raise AuthenticationError(
                "The access token has expired and no refresh token is held. "
                "Get a new pair with AgentXClient.onboard(...) for a new agent, "
                "or POST /auth/token with your refresh token."
            )
        resp = http.post(
            "/auth/token",
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                "Token refresh was refused (HTTP "
                f"{resp.status_code}): the refresh token is invalid, expired or the agent "
                "is not active. Re-onboard with AgentXClient.onboard(...) or obtain a fresh pair."
            )
        raise_for_status(resp)
        self.apply(resp.json())


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
    refresh_token: Optional[str] = None

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
                    "refresh_token": self.refresh_token,
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
            refresh_token=data.get("refresh_token"),
        )

    @classmethod
    def load_or_none(cls, path: str = ".agentx_identity.json") -> Optional["AgentIdentity"]:
        """Like :meth:`load` but returns ``None`` instead of raising on missing file."""
        try:
            return cls.load(path)
        except FileNotFoundError:
            return None
