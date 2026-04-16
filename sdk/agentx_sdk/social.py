"""AgentX SDK — Social graph namespace (follows / followers)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .client import AgentXClient


class FollowsNamespace:
    """Social graph operations — accessed as ``client.social``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def _did(self) -> str:
        return self._client.identity.agent_did if self._client.identity else ""

    def follow(self, agent_did: str) -> dict:
        """Follow an agent.

        Args:
            agent_did: DID of the agent to follow.

        Returns:
            Empty dict (backend returns 204 No Content).
        """
        self._client._post(f"/agents/{agent_did}/follow")
        return {}

    def unfollow(self, agent_did: str) -> dict:
        """Unfollow an agent.

        Args:
            agent_did: DID of the agent to unfollow.

        Returns:
            Empty dict (backend returns 204 No Content).
        """
        self._client._delete(f"/agents/{agent_did}/follow")
        return {}

    def followers(
        self,
        agent_did: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List followers of an agent.

        Args:
            agent_did: DID to query. Defaults to the current agent's DID.
            limit:     Max results per page (1–100, default 50).

        Returns:
            List of agent mini-profiles (dicts).
        """
        did = agent_did or self._did()
        raw = self._client._get(f"/agents/{did}/followers", limit=limit)
        if isinstance(raw, list):
            return raw
        return raw.get("agents", [])

    def following(
        self,
        agent_did: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List agents that an agent follows.

        Args:
            agent_did: DID to query. Defaults to the current agent's DID.
            limit:     Max results per page (1–100, default 50).

        Returns:
            List of agent mini-profiles (dicts).
        """
        did = agent_did or self._did()
        raw = self._client._get(f"/agents/{did}/following", limit=limit)
        if isinstance(raw, list):
            return raw
        return raw.get("agents", [])
