"""
AgentX Platform — Agent Directory & Discovery Service
══════════════════════════════════════════════════════
Search and profile helpers for discovering agents by skill, capability,
and reputation score.

This service centralises discovery logic so routers can remain thin.
"""
import logging
from typing import Optional

from ..database import get_db
from ..models.agent import AgentResponse, AgentWithTrust, TrustScoreBreakdown
from .trust_score import get_trust_score

logger = logging.getLogger(__name__)


async def _search_agents(
    *,
    skill: Optional[str] = None,
    capability: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 100,
) -> list[AgentResponse]:
    """Shared discovery query with optional filters."""
    conditions = ["a.status != 'DEACTIVATED'"]
    params: list[object] = []

    if skill:
        skill_term = f"%{skill.strip().lower()}%"
        params.extend([skill_term, skill_term, skill_term, skill_term, skill_term])
        p1, p2, p3, p4, p5 = (
            len(params) - 4,
            len(params) - 3,
            len(params) - 2,
            len(params) - 1,
            len(params),
        )
        conditions.append(
            "("  # noqa: E131 - SQL readability
            f"LOWER(COALESCE(a.specialization, '')) LIKE ${p1} "
            f"OR LOWER(COALESCE(a.bio, '')) LIKE ${p2} "
            f"OR LOWER(COALESCE(c.name, '')) LIKE ${p3} "
            f"OR LOWER(COALESCE(c.description, '')) LIKE ${p4} "
            f"OR LOWER(COALESCE(a.skills::text, '')) LIKE ${p5}"
            ")"
        )

    if capability:
        cap_term = f"%{capability.strip().lower()}%"
        params.extend([cap_term, cap_term, cap_term, cap_term])
        p1, p2, p3, p4 = len(params) - 3, len(params) - 2, len(params) - 1, len(params)
        conditions.append(
            "("  # noqa: E131 - SQL readability
            f"LOWER(COALESCE(ac.capability_id, '')) LIKE ${p1} "
            f"OR LOWER(COALESCE(c.name, '')) LIKE ${p2} "
            f"OR LOWER(COALESCE(c.domain::text, '')) LIKE ${p3} "
            f"OR LOWER(COALESCE(a.capabilities::text, '')) LIKE ${p4}"
            ")"
        )

    if min_score is not None:
        params.append(min_score)
        conditions.append(f"a.trust_score >= ${len(params)}")

    params.append(limit)
    where = " AND ".join(conditions)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT
                a.agent_did,
                COALESCE(a.display_name, a.name, a.agent_did) AS display_name,
                a.agent_type,
                a.governance_role,
                a.tier,
                a.status,
                a.trust_score,
                a.bio,
                a.specialization,
                a.created_at,
                a.last_seen_at
            FROM agents a
            LEFT JOIN agent_capabilities ac ON ac.agent_did = a.agent_did
            LEFT JOIN capabilities c ON c.capability_id = ac.capability_id
            WHERE {where}
            ORDER BY a.trust_score DESC, a.created_at ASC
            LIMIT ${len(params)}
            """,
            *params,
        )

    results = [
        AgentResponse(
            agent_did=r["agent_did"],
            display_name=r["display_name"] or r["agent_did"],
            agent_type=r["agent_type"],
            governance_role=r["governance_role"],
            tier=r["tier"],
            status=r["status"],
            trust_score=float(r["trust_score"]),
            bio=r["bio"],
            specialization=r["specialization"],
            created_at=r["created_at"],
            last_seen_at=r["last_seen_at"],
        )
        for r in rows
    ]

    # Integrate with trust service for freshest score values.
    for agent in results:
        trust = await get_trust_score(agent.agent_did)
        agent.trust_score = trust.composite

    return results


async def search_agents_by_skill(skill: str) -> list[AgentResponse]:
    """Return active agents that match a given skill keyword."""
    return await _search_agents(skill=skill)


async def search_agents_by_capability(capability: str) -> list[AgentResponse]:
    """Return active agents that match a capability id/name/domain keyword."""
    return await _search_agents(capability=capability)


async def search_agents_by_reputation(min_score: float) -> list[AgentResponse]:
    """Return active agents whose trust score is above the minimum threshold."""
    return await _search_agents(min_score=min_score)


async def get_agent_profile(agent_id: str) -> AgentWithTrust:
    """Return a single agent profile with trust breakdown for directory details."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                agent_did,
                display_name,
                agent_type,
                governance_role,
                tier,
                status,
                trust_score,
                bio,
                specialization,
                created_at,
                last_seen_at
            FROM agents
            WHERE agent_did = $1
              AND status != 'DEACTIVATED'
            """,
            agent_id,
        )

    if row is None:
        raise ValueError(f"Agent not found: {agent_id}")

    trust = await get_trust_score(agent_id)

    return AgentWithTrust(
        agent_did=row["agent_did"],
        display_name=row["display_name"],
        agent_type=row["agent_type"],
        governance_role=row["governance_role"],
        tier=row["tier"],
        status=row["status"],
        trust_score=trust.composite,
        bio=row["bio"],
        specialization=row["specialization"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        trust_breakdown=TrustScoreBreakdown(
            execution_success=trust.execution_success,
            sla_compliance=trust.sla_compliance,
            peer_endorsements=trust.peer_endorsements,
            audit_transparency=trust.audit_transparency,
            security_record=trust.security_record,
            composite=trust.composite,
        ),
    )
