"""
AgentX SDK — Discovery Client
══════════════════════════════
Phase 16: Agent Discovery & Capability Registry.

DiscoveryClient wraps the /agents/discover, /agents/top, /agents/search,
and /agents/{id}/metrics REST endpoints.

Usage:
    from agentx_sdk.discovery import DiscoveryClient

    client = DiscoveryClient(base_url="http://localhost:8000", token="jwt...")

    # Find all agents that can collect_data, ranked by score
    agents = await client.discover_agents(capability="collect_data")

    # Top 5 agents across the whole network
    top = await client.get_top_agents(limit=5)

    # Natural-language semantic search
    results = await client.search_agents("agents that analyse financial data")

    # Metrics for a specific agent
    metrics = await client.get_agent_metrics("agent-uuid-here")
"""
from __future__ import annotations

from typing import Any

import httpx


class DiscoveryClient:
    """
    Async HTTP client for the AgentX /agents/* discovery endpoints.

    Args:
        base_url: AgentX platform API base URL (e.g. http://localhost:8000).
        token:    JWT bearer token (required for capability registration).
        timeout:  HTTP timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token    = token
        self._timeout  = timeout

    # ── Internals ─────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=params,
            )
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}{path}",
                headers=self._headers(),
                json=body or {},
            )
        resp.raise_for_status()
        return resp.json()

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def discover_agents(
        self,
        capability: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Discover agents by capability, ranked by composite score.

        Args:
            capability: Exact capability name to filter on. None = top agents.
            limit:      Maximum number of results.

        Returns:
            List of agent discovery dicts.
        """
        params: dict[str, Any] = {"limit": limit}
        if capability is not None:
            params["capability"] = capability
        return await self._get("/agents/discover", params=params)

    async def get_top_agents(self, limit: int = 10) -> list[dict]:
        """
        Return the highest-scoring agents in the network.

        Args:
            limit: Maximum number of results.

        Returns:
            List of agent discovery dicts, ordered by score.
        """
        return await self._get("/agents/top", params={"limit": limit})

    async def search_agents(self, query: str, limit: int = 10) -> list[dict]:
        """
        Semantic capability search using natural language.

        Args:
            query: Natural-language description of the capability needed.
            limit: Maximum number of results.

        Returns:
            List of matching agent discovery dicts.
        """
        return await self._post("/agents/search", body={"query": query, "limit": limit})

    async def get_agent_metrics(self, agent_id: str) -> dict:
        """
        Fetch performance metrics for a specific agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Agent metrics dict (contracts_completed, verification_success, etc.).
        """
        return await self._get(f"/agents/{agent_id}/metrics")

    async def register_capability(
        self,
        agent_id: str,
        capability: str,
        confidence: float = 1.0,
    ) -> dict:
        """
        Register a capability for an agent (requires bearer token).

        Args:
            agent_id:   UUID string of the agent.
            capability: Capability name to register.
            confidence: Declared confidence level in [0.0, 1.0].

        Returns:
            AgentCapability dict with registry_id and metadata.
        """
        return await self._post(
            f"/agents/{agent_id}/capabilities",
            body={"capability": capability, "confidence": confidence},
        )
