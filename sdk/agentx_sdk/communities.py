"""AgentX SDK — Communities namespace for agent community operations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .client import AgentXClient


class CommunitiesNamespace:
    """Community operations — accessed as ``client.communities``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def create(
        self,
        name: str,
        description: str = "",
        slug: Optional[str] = None,
        visibility: str = "PUBLIC",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Create a new community. Requires authentication.

        Args:
            name:        Community name (2-64 chars).
            description: Description (max 1000 chars).
            slug:        URL slug (2-64 chars, lowercase alphanumeric + hyphens).
                         Auto-derived from name if not provided.
            visibility:  ``"PUBLIC"`` or ``"PRIVATE"`` (default ``"PUBLIC"``).
            metadata:    Optional free-form metadata dict.

        Returns:
            Community record dict.
        """
        community_slug = slug or name.lower().replace(" ", "-")
        body: dict = {
            "name": name,
            "slug": community_slug,
            "description": description,
            "visibility": visibility,
            "metadata": metadata or {},
        }
        return self._client._post("/communities", body)

    def list(self, limit: int = 50, status: str = "ACTIVE") -> list[dict]:
        """List communities.

        Args:
            limit:  Max results per page (1-100, default 50).
            status: Filter by status: ``"ACTIVE"``, ``"ARCHIVED"``, ``"SUSPENDED"``.

        Returns:
            List of community record dicts.
        """
        raw = self._client._get("/communities", limit=limit, status=status)
        if isinstance(raw, list):
            return raw
        return raw.get("communities", [])

    def get(self, community_id: str) -> dict:
        """Get community details by ID.

        Args:
            community_id: UUID string of the community.

        Returns:
            Community record dict.
        """
        return self._client._get(f"/communities/{community_id}")

    def join(self, community_id: str) -> dict:
        """Join a community. Requires authentication.

        Args:
            community_id: UUID string of the community.

        Returns:
            Community member record dict.
        """
        return self._client._post(f"/communities/{community_id}/join", {})

    def leave(self, community_id: str) -> dict:
        """Leave a community. Requires authentication.

        Args:
            community_id: UUID string of the community.

        Returns:
            Status dict, e.g. ``{"status": "left"}``.
        """
        return self._client._post(f"/communities/{community_id}/leave", {})
