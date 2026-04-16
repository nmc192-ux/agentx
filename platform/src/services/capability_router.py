"""
AgentX Platform — Capability Router Service
════════════════════════════════════════════
Phase 5: Agent Capability Graph

Bridges the capability registry with automatic task routing:
  register_capability()        — add a capability to the global registry
  assign_capability_to_agent() — link a capability to an agent
  find_best_agents()           — rank agents by capability fit for a task

All DB access uses asyncpg via get_db() / transaction() context managers.
Heavy lifting for ranking delegates to capability_matcher.find_eligible_agents().
"""
from __future__ import annotations

import logging

from ..database import transaction
from ..models.capability import CapabilityCreate, CapabilityResponse, EligibleAgentResponse
from .capability_matcher import EligibleAgent, find_eligible_agents

logger = logging.getLogger(__name__)


# ── Capability registration ────────────────────────────────────────────────────

async def register_capability(data: CapabilityCreate) -> CapabilityResponse:
    """
    Insert a new capability into the global registry.
    If the capability_id already exists, the existing record is returned unchanged
    (idempotent via ON CONFLICT DO NOTHING).

    Raises:
        ValueError: if capability_id already exists with different attributes.
    """
    async with transaction() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM capabilities WHERE capability_id = $1",
            data.capability_id,
        )
        if existing is not None:
            # Return existing without modification — caller can update via PATCH if needed
            return _row_to_capability(dict(existing))

        row = await conn.fetchrow(
            """
            INSERT INTO capabilities (
                capability_id,
                name,
                description,
                domain,
                level,
                requires_verification,
                rep_reward,
                prerequisites
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING
                capability_id, name, description, domain, level,
                requires_verification, rep_reward, prerequisites,
                verified_by, created_at
            """,
            data.capability_id,
            data.name,
            data.description,
            data.domain.value,
            data.level.value,
            data.requires_verification,
            data.rep_reward,
            list(data.prerequisites),
        )

    logger.info("Capability registered: %s", data.capability_id)
    return _row_to_capability(dict(row))


# ── Capability assignment ──────────────────────────────────────────────────────

async def assign_capability_to_agent(agent_did: str, capability_id: str) -> dict:
    """
    Assign a registered capability to an agent (idempotent).

    Returns the agent_capabilities row as a plain dict.

    Raises:
        ValueError: if agent or capability does not exist.
    """
    async with transaction() as conn:
        agent_exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if not agent_exists:
            raise ValueError(f"Agent not found: {agent_did}")

        cap_exists = await conn.fetchval(
            "SELECT 1 FROM capabilities WHERE capability_id = $1",
            capability_id,
        )
        if not cap_exists:
            raise ValueError(f"Capability not found in registry: {capability_id}")

        row = await conn.fetchrow(
            """
            INSERT INTO agent_capabilities (agent_did, capability_id)
            VALUES ($1, $2)
            ON CONFLICT (agent_did, capability_id) DO UPDATE
                SET acquired_at = agent_capabilities.acquired_at
            RETURNING agent_did, capability_id, verified, verified_by_count, acquired_at
            """,
            agent_did,
            capability_id,
        )

    logger.info("Capability %s assigned to agent %s", capability_id, agent_did)
    return dict(row)


# ── Agent ranking ──────────────────────────────────────────────────────────────

async def find_best_agents(
    required_capabilities: list[str],
    limit: int = 5,
    min_trust_score: float = 0.0,
) -> list[EligibleAgentResponse]:
    """
    Find and rank agents best suited to handle the given capability requirements.

    Delegates scoring to capability_matcher.find_eligible_agents() and converts
    the result to Pydantic-serialisable EligibleAgentResponse models.

    Returns:
        Ranked list (highest composite score first). Fully-qualified agents appear
        before partially-qualified ones.
    """
    agents: list[EligibleAgent] = await find_eligible_agents(
        required_capabilities=required_capabilities,
        limit=limit,
        min_trust_score=min_trust_score,
    )
    return [_eligible_to_response(a) for a in agents]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_capability(row: dict) -> CapabilityResponse:
    from ..models.capability import CapabilityDomain, CapabilityLevel
    return CapabilityResponse(
        capability_id=row["capability_id"],
        name=row["name"],
        description=row.get("description", ""),
        domain=CapabilityDomain(row["domain"]),
        level=CapabilityLevel(row["level"]),
        requires_verification=row["requires_verification"],
        rep_reward=row["rep_reward"],
        prerequisites=list(row.get("prerequisites") or []),
        verified_by=list(row.get("verified_by") or []),
        created_at=row["created_at"],
    )


def _eligible_to_response(agent: EligibleAgent) -> EligibleAgentResponse:
    return EligibleAgentResponse(
        agent_did=agent.agent_did,
        display_name=agent.display_name,
        score=agent.score,
        capability_match_score=agent.capability_match_score,
        trust_score=agent.trust_score,
        rep_balance=agent.rep_balance,
        missing_capabilities=agent.missing_capabilities,
    )
