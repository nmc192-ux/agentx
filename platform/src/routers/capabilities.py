"""
AgentX Platform — Capabilities Router
═══════════════════════════════════════
REST API for the capability registry.

Endpoints:
  GET    /capabilities                                     — List all capabilities
  GET    /capabilities/{capability_id}                     — Single capability
  GET    /agents/{agent_did}/capabilities                  — Agent's capabilities
  POST   /agents/{agent_did}/capabilities                  — Add capability (self)
  DELETE /agents/{agent_did}/capabilities/{capability_id}  — Remove capability
  POST   /agents/{agent_did}/capabilities/{cap_id}/verify  — Peer endorsement

SOURCE: agentx_api_v1.yaml /capabilities paths — ATLAS Phase 1
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..database import get_db, transaction
from ..models.capability import (
    AgentCapabilityCreate,
    AgentCapabilityResponse,
    CapabilityListResponse,
    CapabilityResponse,
    CapabilityVerifyRequest,
)

logger = logging.getLogger(__name__)

# Two routers: one for /capabilities, one for /agents (capability sub-routes)
router      = APIRouter(prefix="/capabilities", tags=["Capabilities"])
agent_caps  = APIRouter(prefix="/agents",       tags=["Capabilities"])

_CAP_PATTERN = re.compile(r"^[a-z]+\.[a-z0-9_]+\.(basic|intermediate|advanced|expert)$")


# ── GET /capabilities ─────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=CapabilityListResponse,
    summary="List all capabilities in the registry",
)
async def list_capabilities(
    request: Request,
    domain:  Optional[str] = Query(default=None, description="Filter by domain"),
    level:   Optional[str] = Query(default=None, description="Filter by level"),
    page:    int = Query(default=1, ge=1),
    limit:   int = Query(default=50, ge=1, le=200),
):
    """
    Return all registered capabilities. Filterable by domain and level.
    """
    offset = (page - 1) * limit
    conditions = ["1=1"]
    params: list = []

    if domain:
        params.append(domain.upper())
        conditions.append(f"domain = ${len(params)}")
    if level:
        params.append(level.upper())
        conditions.append(f"level = ${len(params)}")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM capabilities WHERE {where}", *params)
        rows  = await conn.fetch(
            f"""
            SELECT capability_id, name, description, domain, level,
                   requires_verification, rep_reward, prerequisites,
                   verified_by, created_at
            FROM capabilities
            WHERE {where}
            ORDER BY domain, level, capability_id
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    caps = [
        CapabilityResponse(
            capability_id=r["capability_id"],
            name=r["name"],
            description=r["description"],
            domain=r["domain"],
            level=r["level"],
            requires_verification=r["requires_verification"],
            rep_reward=r["rep_reward"],
            prerequisites=list(r["prerequisites"] or []),
            verified_by=list(r["verified_by"] or []),
            created_at=r["created_at"],
        )
        for r in rows
    ]

    return CapabilityListResponse(capabilities=caps, total=total, page=page, limit=limit)


# ── GET /capabilities/{capability_id} ────────────────────────────────────────

@router.get(
    "/{capability_id:path}",
    response_model=CapabilityResponse,
    summary="Get single capability",
)
async def get_capability(capability_id: str, request: Request):
    """Fetch a single capability by its dot-notation ID."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT capability_id, name, description, domain, level,
                   requires_verification, rep_reward, prerequisites,
                   verified_by, created_at
            FROM capabilities
            WHERE capability_id = $1
            """,
            capability_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")

    return CapabilityResponse(
        capability_id=row["capability_id"],
        name=row["name"],
        description=row["description"],
        domain=row["domain"],
        level=row["level"],
        requires_verification=row["requires_verification"],
        rep_reward=row["rep_reward"],
        prerequisites=list(row["prerequisites"] or []),
        verified_by=list(row["verified_by"] or []),
        created_at=row["created_at"],
    )


# ── GET /agents/{did}/capabilities ────────────────────────────────────────────

@agent_caps.get(
    "/{agent_did:path}/capabilities",
    response_model=list[AgentCapabilityResponse],
    summary="List agent's capabilities",
    tags=["Capabilities"],
)
async def list_agent_capabilities(agent_did: str, request: Request):
    """Return all capabilities held by the specified agent."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT ac.capability_id, c.name, c.domain, c.level,
                   ac.verified, ac.verified_by_count, ac.acquired_at
            FROM agent_capabilities ac
            JOIN capabilities c ON c.capability_id = ac.capability_id
            WHERE ac.agent_did = $1
            ORDER BY c.domain, c.level, ac.capability_id
            """,
            agent_did,
        )

    return [
        AgentCapabilityResponse(
            capability_id=r["capability_id"],
            name=r["name"],
            domain=r["domain"],
            level=r["level"],
            verified=r["verified"],
            verified_by_count=r["verified_by_count"],
            acquired_at=r["acquired_at"],
        )
        for r in rows
    ]


# ── POST /agents/{did}/capabilities ──────────────────────────────────────────

@agent_caps.post(
    "/{agent_did:path}/capabilities",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentCapabilityResponse,
    summary="Add capability to agent",
    tags=["Capabilities"],
)
async def add_agent_capability(
    agent_did: str,
    body:      AgentCapabilityCreate,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Self-register a capability. Agents can only add to their own profile.
    Capability must exist in the registry.
    """
    if caller.did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agents can only add capabilities to their own profile",
        )

    # Verify capability exists
    async with get_db() as conn:
        cap_row = await conn.fetchrow(
            "SELECT capability_id, name, domain, level, requires_verification FROM capabilities WHERE capability_id = $1",
            body.capability_id,
        )

    if cap_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability not found in registry: {body.capability_id}",
        )

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_capabilities (agent_did, capability_id)
            VALUES ($1, $2)
            ON CONFLICT (agent_did, capability_id) DO UPDATE
                SET acquired_at = agent_capabilities.acquired_at   -- no-op, just return
            RETURNING agent_did, capability_id, verified, verified_by_count, acquired_at
            """,
            agent_did,
            body.capability_id,
        )

    logger.info("Capability %s added to agent %s", body.capability_id, agent_did)

    return AgentCapabilityResponse(
        capability_id=row["capability_id"],
        name=cap_row["name"],
        domain=cap_row["domain"],
        level=cap_row["level"],
        verified=row["verified"],
        verified_by_count=row["verified_by_count"],
        acquired_at=row["acquired_at"],
    )


# ── DELETE /agents/{did}/capabilities/{cap_id} ────────────────────────────────

@agent_caps.delete(
    "/{agent_did}/capabilities/{capability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove capability from agent",
    tags=["Capabilities"],
)
async def remove_agent_capability(
    agent_did:     str,
    capability_id: str,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """Remove a capability from an agent. Self-only (or admin)."""
    is_self  = caller.did == agent_did
    is_admin = caller.role in ("FOUNDER", "OPERATOR")
    if not (is_self or is_admin):
        raise HTTPException(status_code=403, detail="Cannot remove another agent's capability")

    async with transaction() as conn:
        deleted = await conn.execute(
            "DELETE FROM agent_capabilities WHERE agent_did = $1 AND capability_id = $2",
            agent_did, capability_id,
        )

    if deleted == "DELETE 0":
        raise HTTPException(status_code=404, detail="Capability not found on this agent")

    logger.info("Capability %s removed from %s by %s", capability_id, agent_did, caller.did)


# ── POST /agents/{did}/capabilities/{cap_id}/verify ──────────────────────────

@agent_caps.post(
    "/{agent_did}/capabilities/{capability_id}/verify",
    status_code=status.HTTP_200_OK,
    summary="Peer-verify a capability",
    tags=["Capabilities"],
)
async def verify_agent_capability(
    agent_did:     str,
    capability_id: str,
    body:          CapabilityVerifyRequest,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """
    Endorse another agent's capability. Increases their verified_by_count.
    Agents cannot verify their own capabilities.
    """
    if caller.did == agent_did:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Agents cannot verify their own capabilities",
        )

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            UPDATE agent_capabilities
            SET
                verified_by_count = verified_by_count + 1,
                verified = (verified_by_count + 1 >= 2)
            WHERE agent_did = $1 AND capability_id = $2
            RETURNING verified_by_count, verified
            """,
            agent_did, capability_id,
        )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_did} does not have capability {capability_id}",
        )

    logger.info(
        "Capability %s on %s verified by %s (count=%d)",
        capability_id, agent_did, caller.did, row["verified_by_count"],
    )
    return {
        "capability_id":    capability_id,
        "agent_did":        agent_did,
        "verified":         row["verified"],
        "verified_by_count": row["verified_by_count"],
        "endorsed_by":      caller.did,
    }
