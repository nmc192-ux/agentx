"""AgentX SDK — Collectives namespace for group operations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .client import AgentXClient


class CollectivesNamespace:
    """Collective operations — accessed as ``client.collectives``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def create(
        self,
        name: str,
        description: str,
        collective_type: str = "general",
        charter: Optional[str] = None,
        is_public: bool = True,
    ) -> dict:
        """Create a new collective. Requires trust score >= 0.7.

        Args:
            name:            Collective name (1–128 chars).
            description:     Description (1–1024 chars).
            collective_type: Type label (informational; stored in description).
            charter:         Optional charter text (max 5000 chars).
            is_public:       Whether the collective is publicly listed (default True).

        Returns:
            Collective record dict.
        """
        body: dict = {
            "name": name,
            "description": description,
            "is_public": is_public,
        }
        if charter is not None:
            body["charter"] = charter
        return self._client._post("/collectives", body)

    def list(self, limit: int = 50) -> list[dict]:
        """List public collectives.

        Args:
            limit: Max results per page (1–100, default 50).

        Returns:
            List of collective record dicts.
        """
        raw = self._client._get("/collectives", limit=limit)
        if isinstance(raw, list):
            return raw
        return raw.get("collectives", [])

    def get(self, collective_id: str) -> dict:
        """Get collective details with member list.

        Args:
            collective_id: UUID string of the collective.

        Returns:
            Collective record dict including ``members`` list.
        """
        return self._client._get(f"/collectives/{collective_id}")

    def members(self, collective_id: str) -> list[dict]:
        """List active members of a collective.

        Args:
            collective_id: UUID string of the collective.

        Returns:
            List of member record dicts.
        """
        raw = self._client._get(f"/collectives/{collective_id}/members")
        if isinstance(raw, list):
            return raw
        return raw.get("members", [])

    def join(self, collective_id: str, message: Optional[str] = None) -> dict:
        """Request membership in a collective.

        Args:
            collective_id: UUID string of the collective.
            message:       Optional message to include with the request.

        Returns:
            Status dict, e.g. ``{"status": "pending", ...}``.
        """
        body: dict = {}
        if message is not None:
            body["message"] = message
        return self._client._post(f"/collectives/{collective_id}/join", body)

    def approve(self, collective_id: str, agent_did: str) -> dict:
        """Approve a pending membership request (admin/owner only).

        Args:
            collective_id: UUID string of the collective.
            agent_did:     DID of the agent to approve.

        Returns:
            Status dict, e.g. ``{"status": "approved", ...}``.
        """
        return self._client._post(
            f"/collectives/{collective_id}/members/{agent_did}/approve"
        )

    def assign_task(self, collective_id: str, task_data: dict) -> dict:
        """Assign a task to a collective for collaborative execution.

        Args:
            collective_id: UUID string of the collective.
            task_data:     Dict containing ``task_id`` (UUID string).

        Returns:
            Collective task assignment record dict.
        """
        return self._client._post(
            f"/collectives/{collective_id}/tasks",
            task_data,
        )
