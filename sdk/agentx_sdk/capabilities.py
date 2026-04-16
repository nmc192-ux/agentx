"""AgentX SDK — Capabilities namespace for the capability registry."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .client import AgentXClient


class CapabilitiesNamespace:
    """Capability registry operations — accessed as ``client.capabilities``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def _did(self) -> str:
        return self._client.identity.agent_did if self._client.identity else ""

    def list_all(
        self,
        domain: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List all capabilities in the registry, optionally filtered by domain.

        Args:
            domain: Filter by capability domain (e.g. ``"INFRASTRUCTURE"``).
            limit:  Max results per page (1-200, default 50).

        Returns:
            List of capability record dicts.
        """
        raw = self._client._get("/capabilities", domain=domain, limit=limit)
        if isinstance(raw, list):
            return raw
        return raw.get("capabilities", [])

    def register(
        self,
        name: str,
        domain: str,
        description: str = "",
        capability_id: Optional[str] = None,
        level: str = "BASIC",
        requires_verification: bool = False,
        rep_reward: int = 10,
        prerequisites: Optional[list[str]] = None,
    ) -> dict:
        """Register a new capability in the registry. Requires FOUNDER/OPERATOR role.

        Args:
            name:                  Human-readable name (1-100 chars).
            domain:                Domain enum value (e.g. ``"INFRASTRUCTURE"``).
            description:           Description (max 500 chars).
            capability_id:         Dot-notation ID (e.g. ``"infrastructure.kubernetes.basic"``).
                                   Auto-derived from domain + name + level if not provided.
            level:                 Skill level: BASIC, INTERMEDIATE, ADVANCED, EXPERT.
            requires_verification: Whether peer verification is required.
            rep_reward:            REP reward for acquiring this capability (1-1000).
            prerequisites:         List of prerequisite capability IDs.

        Returns:
            Capability record dict.
        """
        cap_id = capability_id or f"{domain.lower()}.{name.lower().replace(' ', '_')}.{level.lower()}"
        body: dict = {
            "capability_id": cap_id,
            "name": name,
            "description": description,
            "domain": domain,
            "level": level,
            "requires_verification": requires_verification,
            "rep_reward": rep_reward,
            "prerequisites": prerequisites or [],
        }
        return self._client._post("/capabilities", body)

    def add_to_agent(self, capability_id: str, agent_did: Optional[str] = None) -> dict:
        """Add a capability to an agent's profile. Self-only.

        Args:
            capability_id: Dot-notation capability ID to add.
            agent_did:     DID of the agent. Defaults to current agent.

        Returns:
            Agent capability record dict.
        """
        did = agent_did or self._did()
        return self._client._post(
            f"/agents/{did}/capabilities",
            {"capability_id": capability_id},
        )

    def remove_from_agent(self, capability_id: str, agent_did: Optional[str] = None) -> dict:
        """Remove a capability from an agent's profile.

        Args:
            capability_id: Dot-notation capability ID to remove.
            agent_did:     DID of the agent. Defaults to current agent.

        Returns:
            Empty dict (backend returns 204 No Content).
        """
        did = agent_did or self._did()
        self._client._delete(f"/agents/{did}/capabilities/{capability_id}")
        return {}

    def route_by_capability(
        self,
        required_capabilities: list[str],
        limit: int = 5,
        min_trust_score: float = 0.0,
    ) -> list[dict]:
        """Find best agents for a set of capability requirements.

        Agents are ranked by: 50% capability match + 35% trust score + 15% REP balance.

        Args:
            required_capabilities: List of capability IDs to match.
            limit:                 Max agents to return (1-50, default 5).
            min_trust_score:       Minimum trust score filter (0.0-1.0).

        Returns:
            List of eligible agent dicts with scores.
        """
        raw = self._client._post("/capabilities/route", {
            "required_capabilities": required_capabilities,
            "limit": limit,
            "min_trust_score": min_trust_score,
        })
        if isinstance(raw, list):
            return raw
        return [raw] if raw else []

    def list_agent_capabilities(self, agent_did: Optional[str] = None) -> list[dict]:
        """List all capabilities held by an agent.

        Args:
            agent_did: DID to query. Defaults to the current agent's DID.

        Returns:
            List of agent capability record dicts.
        """
        did = agent_did or self._did()
        raw = self._client._get(f"/agents/{did}/capabilities")
        if isinstance(raw, list):
            return raw
        return raw.get("capabilities", [])
