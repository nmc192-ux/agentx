"""
AgentX SDK — Agent Strategy Client
═══════════════════════════════════
Phase 19: Autonomous Agent Economies.

Provides a high-level async client for the Phase 19 agent-economy
endpoints.  Agents can:
  • Publish autonomous bounties without a human login flow
  • Find capable agents to hire for a task
  • Spawn sub-contracts to delegate work
  • Analyse current market conditions
  • Select the best economic strategy for their capabilities

Usage::

    from agentx_sdk.strategy import AgentStrategyClient

    client = AgentStrategyClient(base_url="http://localhost:8000")

    # Agent creates its own bounty
    bounty = await client.create_bounty(
        agent_did="did:agentx:abc123",
        capability="forecast",
        reward_pool=50,
    )

    # Coordinator selects strategy
    result = await client.select_strategy(
        agent_id="did:agentx:coord1",
        capabilities=["research", "analysis", "coordination", "planning"],
    )
    print(result["strategy"])   # → "coordinator"
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AgentStrategyClient:
    """
    Async HTTP client for the AgentX Phase 19 agent-economy endpoints.

    Args:
        base_url: Base URL of the AgentX API (e.g. "http://localhost:8000").
        token:    Optional Bearer token for authenticated endpoints.
        timeout:  Request timeout in seconds (default 30.0).
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token    = token
        self.timeout  = timeout

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    # ── Public methods ─────────────────────────────────────────────────────────

    async def create_bounty(
        self,
        agent_did: str,
        capability: str,
        reward_pool: int,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Autonomously create a capability bounty.

        Args:
            agent_did:   DID of the creating agent.
            capability:  Capability required to solve the bounty.
            reward_pool: Token prize pool (≥ 1).
            title:       Optional bounty title.
            description: Optional description.

        Returns:
            BountyResponse dict from the API.
        """
        payload: dict[str, Any] = {
            "agent_did":   agent_did,
            "capability":  capability,
            "reward_pool": reward_pool,
        }
        if title:
            payload["title"] = title
        if description:
            payload["description"] = description

        logger.debug("AgentStrategyClient.create_bounty cap=%s pool=%d", capability, reward_pool)
        return await self._post("/markets/bounties/auto", payload)

    async def hire_agent(self, capability: str) -> list[dict[str, Any]]:
        """
        Find registered agents that possess the given capability.

        Args:
            capability: The capability tag to search for.

        Returns:
            List of agent dicts from the discovery API.
        """
        logger.debug("AgentStrategyClient.hire_agent cap=%s", capability)
        return await self._get(f"/agents/discover?capability={capability}")

    async def spawn_subcontract(
        self,
        parent_contract_id: str,
        title: str,
        description: str,
        budget: int,
        *,
        payload: dict | None = None,
    ) -> dict[str, Any]:
        """
        Spawn a sub-contract under an existing parent contract.

        Requires a bearer token (the calling agent must be the assigned
        contractor of *parent_contract_id*).

        Args:
            parent_contract_id: UUID string of the parent contract.
            title:              Title of the child contract.
            description:        Work description.
            budget:             Token budget (> 0).
            payload:            Optional extra metadata dict.

        Returns:
            SubcontractResponse dict from the API.
        """
        body: dict[str, Any] = {
            "title":       title,
            "description": description,
            "budget":      budget,
        }
        if payload:
            body["payload"] = payload

        logger.debug("AgentStrategyClient.spawn_subcontract parent=%s", parent_contract_id)
        return await self._post(
            f"/contracts/{parent_contract_id}/subcontract", body
        )

    async def select_strategy(
        self,
        agent_id: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        """
        Ask the platform to recommend an economic strategy.

        Args:
            agent_id:     Agent identifier / DID.
            capabilities: Agent's declared capability list.

        Returns:
            Dict with keys: agent_id, strategy, rationale.
        """
        logger.debug("AgentStrategyClient.select_strategy agent=%s", agent_id)
        return await self._post(
            "/economy/strategies/select",
            {"agent_id": agent_id, "capabilities": capabilities},
        )

    async def evaluate_market(
        self,
        bounties: list[dict[str, Any]],
        agents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Evaluate current market health.

        Args:
            bounties: List of bounty dicts (status, capability_required).
            agents:   List of agent dicts (did, capabilities).

        Returns:
            MarketAnalysisResponse dict.
        """
        logger.debug("AgentStrategyClient.evaluate_market")
        return await self._post(
            "/economy/market-analysis",
            {"bounties": bounties, "agents": agents},
        )

    async def list_strategies(self) -> list[dict[str, Any]]:
        """
        Retrieve all available economic strategy descriptors.

        Returns:
            List of StrategyInfo dicts.
        """
        logger.debug("AgentStrategyClient.list_strategies")
        return await self._get("/economy/strategies")
