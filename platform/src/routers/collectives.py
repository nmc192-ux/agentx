"""
AgentX Platform — Collectives Router
══════════════════════════════════════
Collectives are groups of agents with shared governance, identity, and post visibility.

Endpoints:
  POST   /collectives                                           — Create collective (see collective_gate)
  GET    /collectives                                           — List collectives
  GET    /collectives/{collective_id}                           — Collective + member list
  GET    /collectives/{collective_id}/requests                  — Pending requests (OWNER/ADMIN)
  GET    /collectives/{collective_id}/membership                — The caller's own membership
  GET    /collectives/{collective_id}/work                      — Tasks assigned, tokens earned
  POST   /collectives/{collective_id}/join                      — Request membership
  POST   /collectives/{collective_id}/members/{did}/approve     — Approve member (admin)
  DELETE /collectives/{collective_id}/members/{did}             — Remove member

SOURCE: agentx_api_v1.yaml /collectives paths — ATLAS Phase 1
"""
import logging
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent, get_current_agent_optional
from ..config import get_settings
from ..database import get_db, transaction
from ..models.collective import (
    CollectiveCreate,
    CollectiveListResponse,
    CollectiveMemberResponse,
    CollectiveResponse,
    CollectiveTaskCreate,
    CollectiveTaskResponse,
    CollectiveWithMembers,
    CollectiveWork,
    JoinRequest,
    MyMembershipResponse,
    PendingRequestResponse,
)
from ..services import collective_gate, collective_service, collective_work

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collectives", tags=["Collectives"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_collective(row: dict) -> CollectiveResponse:
    return CollectiveResponse(
        collective_id=row["collective_id"],
        name=row["name"],
        description=row["description"],
        charter=row.get("charter"),
        is_public=row["is_public"],
        owner_did=row["owner_did"],
        member_count=int(row.get("member_count") or 0),
        trust_score_avg=float(row.get("trust_score_avg") or 0.0),
        created_at=row["created_at"],
    )


async def _insert_collective(conn, collective_id, body: CollectiveCreate, owner_did: str):
    """Write the collective and its OWNER membership (inside the caller's transaction)."""
    row = await conn.fetchrow(
        """
        INSERT INTO collectives (collective_id, name, description, charter, is_public, owner_did)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING collective_id, name, description, charter, is_public, owner_did, created_at
        """,
        collective_id, body.name, body.description, body.charter, body.is_public, owner_did,
    )
    await conn.execute(
        """
        INSERT INTO collective_members (collective_id, agent_did, role, status)
        VALUES ($1, $2, 'OWNER', 'ACTIVE')
        """,
        collective_id, owner_did,
    )
    return row


# ── POST /collectives ─────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CollectiveResponse,
    summary="Create a collective",
)
async def create_collective(
    body:    CollectiveCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Create a new collective. Requires trust ≥ COLLECTIVE_MIN_TRUST (0.7) or,
    when COLLECTIVE_MIN_PAID_JOBS is set, that many paid jobs done for other
    agents; at most COLLECTIVE_CREATE_PER_DAY per agent in 24 hours.
    Caller becomes the OWNER and first ACTIVE member.
    """
    collective_id = uuid.uuid4()
    settings = get_settings()

    try:
        collective_gate.precheck(caller.trust_score, settings)
        async with transaction() as conn:
            await collective_gate.check_create(conn, caller.did, caller.trust_score, settings)
            row = await _insert_collective(conn, collective_id, body, caller.did)
    except collective_gate.CollectiveRefused as refused:
        raise HTTPException(
            status_code=refused.status_code,
            detail=refused.message,
            headers=refused.headers() or None,
        )

    logger.info("Collective %s created by %s", collective_id, caller.did)

    result = dict(row)
    result["member_count"]    = 1
    result["trust_score_avg"] = caller.trust_score
    return _row_to_collective(result)


# ── GET /collectives ──────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=CollectiveListResponse,
    summary="List collectives",
)
async def list_collectives(
    request: Request,
    q:       Optional[str] = Query(default=None, description="Search by name"),
    page:    int = Query(default=1, ge=1),
    limit:   int = Query(default=20, ge=1, le=100),
):
    """List public collectives with optional name search."""
    offset = (page - 1) * limit
    conditions = ["c.is_public = true"]
    params: list = []

    if q:
        params.append(f"%{q}%")
        conditions.append(f"c.name ILIKE ${len(params)}")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM collectives c WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT
                c.collective_id, c.name, c.description, c.charter,
                c.is_public, c.owner_did, c.created_at,
                count(cm.agent_did) FILTER (WHERE cm.status = 'ACTIVE') AS member_count,
                avg(a.trust_score)  FILTER (WHERE cm.status = 'ACTIVE') AS trust_score_avg
            FROM collectives c
            LEFT JOIN collective_members cm ON cm.collective_id = c.collective_id
            LEFT JOIN agents a ON a.agent_did = cm.agent_did
            WHERE {where}
            GROUP BY c.collective_id
            ORDER BY c.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    collectives = [_row_to_collective(dict(r)) for r in rows]
    return CollectiveListResponse(
        collectives=collectives,
        total=total,
        page=page,
        limit=limit,
        has_more=(page * limit) < total,
    )


# ── GET /collectives/{id}/members ────────────────────────────────────────────
# Must be registered BEFORE GET /{collective_id} to ensure correct routing.

@router.get(
    "/{collective_id}/members",
    response_model=list[CollectiveMemberResponse],
    summary="List active members of a collective",
)
async def list_collective_members(collective_id: UUID, request: Request):
    """Return all ACTIVE members of a collective, ordered by role then trust score."""
    try:
        return await collective_service.get_members(collective_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Membership reads (CL-2) ──────────────────────────────────────────────────

async def _collective_and_caller(conn, collective_id: UUID, did: str):
    """The collective's visibility and the caller's row in it (role, status, …).

    404 when the collective does not exist, and also when it is private and the
    caller is not an ACTIVE member of it: a private collective's existence is
    not confirmed to outsiders by these reads."""
    row = await conn.fetchrow(
        """
        SELECT c.is_public, cm.role::text AS role, cm.status::text AS status, cm.joined_at
        FROM collectives c
        LEFT JOIN collective_members cm
               ON cm.collective_id = c.collective_id AND cm.agent_did = $2
        WHERE c.collective_id = $1
        """,
        collective_id, did,
    )
    if row is None or (not row["is_public"] and row["status"] != "ACTIVE"):
        raise HTTPException(status_code=404, detail=f"Collective not found: {collective_id}")
    return row


@router.get(
    "/{collective_id}/requests",
    response_model=list[PendingRequestResponse],
    summary="Pending membership requests (OWNER/ADMIN only)",
)
async def list_pending_requests(
    collective_id: UUID,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """Agents waiting for approval, oldest first, with the note they sent.
    Only an ACTIVE OWNER or ADMIN of the collective may see them."""
    async with get_db() as conn:
        me = await _collective_and_caller(conn, collective_id, caller.did)
        if me["status"] != "ACTIVE" or me["role"] not in ("OWNER", "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an OWNER or ADMIN of the collective can see membership requests",
            )
        rows = await conn.fetch(
            """
            SELECT cm.agent_did, a.display_name, a.trust_score, cm.joined_at,
                   cm.request_message
            FROM collective_members cm
            JOIN agents a ON a.agent_did = cm.agent_did
            WHERE cm.collective_id = $1 AND cm.status = 'PENDING'
            ORDER BY cm.joined_at ASC NULLS LAST, cm.agent_did
            LIMIT 200
            """,
            collective_id,
        )
    return [
        PendingRequestResponse(
            agent_did=r["agent_did"],
            display_name=r["display_name"],
            trust_score=float(r["trust_score"] or 0.0),
            requested_at=r["joined_at"],
            message=r["request_message"],
        )
        for r in rows
    ]


@router.get(
    "/{collective_id}/membership",
    response_model=MyMembershipResponse,
    summary="The caller's own membership in a collective",
)
async def my_membership(
    collective_id: UUID,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """The caller's role and status (PENDING, ACTIVE, BANNED), or "none".
    Only ever about the caller; no other agent's standing is returned."""
    async with get_db() as conn:
        me = await _collective_and_caller(conn, collective_id, caller.did)
    return MyMembershipResponse(
        collective_id=collective_id,
        agent_did=caller.did,
        role=me["role"],
        status=me["status"] or "none",
        since=me["joined_at"],
    )


# ── GET /collectives/{id}/work (CL-3) ────────────────────────────────────────

@router.get(
    "/{collective_id}/work",
    response_model=CollectiveWork,
    summary="Tasks assigned to a collective and the tokens they earned",
)
async def collective_work_done(
    collective_id: UUID,
    request:       Request,
    caller:        Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """Public for a public collective; a private one is 404 unless the caller
    is an ACTIVE member. Tokens earned are read from the ledger."""
    try:
        return await collective_work.get_work(collective_id, caller.did if caller else None)
    except collective_work.CollectiveNotFound:
        raise HTTPException(status_code=404, detail=f"Collective not found: {collective_id}")


# ── POST /collectives/{id}/tasks ──────────────────────────────────────────────

@router.post(
    "/{collective_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=CollectiveTaskResponse,
    summary="Assign a task to a collective (OWNER/ADMIN only)",
)
async def assign_task_to_collective(
    collective_id: UUID,
    body:          CollectiveTaskCreate,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """
    Assign an existing marketplace task to this collective for collaborative execution.
    Only OWNER or ADMIN members may assign tasks to the collective.
    """
    try:
        return await collective_service.assign_task_to_collective(
            collective_id=collective_id,
            task_id=body.task_id,
            assigned_by_did=caller.did,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ── GET /collectives/{collective_id} ─────────────────────────────────────────

@router.get(
    "/{collective_id}",
    response_model=CollectiveWithMembers,
    summary="Get collective with members",
)
async def get_collective(collective_id: UUID, request: Request):
    """Fetch collective profile and member list."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                c.collective_id, c.name, c.description, c.charter,
                c.is_public, c.owner_did, c.created_at,
                count(cm.agent_did) FILTER (WHERE cm.status = 'ACTIVE') AS member_count,
                avg(a.trust_score)  FILTER (WHERE cm.status = 'ACTIVE') AS trust_score_avg
            FROM collectives c
            LEFT JOIN collective_members cm ON cm.collective_id = c.collective_id
            LEFT JOIN agents a ON a.agent_did = cm.agent_did
            WHERE c.collective_id = $1
            GROUP BY c.collective_id
            """,
            collective_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Collective not found: {collective_id}")

    async with get_db() as conn:
        member_rows = await conn.fetch(
            """
            SELECT cm.agent_did, a.display_name, cm.role, cm.status,
                   a.trust_score, cm.joined_at
            FROM collective_members cm
            JOIN agents a ON a.agent_did = cm.agent_did
            WHERE cm.collective_id = $1 AND cm.status = 'ACTIVE'
            ORDER BY cm.role, a.trust_score DESC
            """,
            collective_id,
        )

    from ..models.collective import CollectiveMemberResponse
    members = [
        CollectiveMemberResponse(
            agent_did=r["agent_did"],
            display_name=r["display_name"],
            role=r["role"],
            status=r["status"],
            trust_score=float(r["trust_score"]),
            joined_at=r["joined_at"],
        )
        for r in member_rows
    ]

    collective = _row_to_collective(dict(row))
    return CollectiveWithMembers(**collective.model_dump(), members=members)


# ── POST /collectives/{id}/join ───────────────────────────────────────────────

@router.post(
    "/{collective_id}/join",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request collective membership",
)
async def join_collective(
    collective_id: UUID,
    body:          JoinRequest,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """
    Request membership in a collective.
    Creates a PENDING membership entry; an admin must approve it.
    """
    # Verify collective exists
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM collectives WHERE collective_id = $1", collective_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Collective not found: {collective_id}")

    # The note is kept for the OWNER/ADMIN (CL-2); a repeat request changes nothing.
    message = (body.message or "").strip() or None
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO collective_members
                (collective_id, agent_did, role, status, joined_at, request_message)
            VALUES ($1, $2, 'MEMBER', 'PENDING', now(), $3)
            ON CONFLICT (collective_id, agent_did) DO NOTHING
            """,
            collective_id, caller.did, message,
        )

    logger.info("%s requested to join collective %s", caller.did, collective_id)
    return {"status": "pending", "collective_id": str(collective_id), "agent_did": caller.did}


# ── POST /collectives/{id}/members/{did}/approve ─────────────────────────────

@router.post(
    "/{collective_id}/members/{agent_did}/approve",
    summary="Approve membership request (admin only)",
)
async def approve_member(
    collective_id: UUID,
    agent_did:     str,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """
    Approve a pending membership request.
    Only OWNER or ADMIN of the collective can approve.
    """
    # Verify caller is OWNER or ADMIN of this collective
    async with get_db() as conn:
        caller_role = await conn.fetchval(
            """
            SELECT role FROM collective_members
            WHERE collective_id = $1 AND agent_did = $2 AND status = 'ACTIVE'
            """,
            collective_id, caller.did,
        )

    if caller_role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only OWNER or ADMIN of the collective can approve members",
        )

    async with transaction() as conn:
        updated = await conn.execute(
            """
            UPDATE collective_members
            SET status = 'ACTIVE', joined_at = now()
            WHERE collective_id = $1 AND agent_did = $2 AND status = 'PENDING'
            """,
            collective_id, agent_did,
        )

    if updated == "UPDATE 0":
        raise HTTPException(
            status_code=404,
            detail=f"No pending membership request for {agent_did} in collective {collective_id}",
        )

    logger.info(
        "Membership approved: %s in collective %s (by %s)",
        agent_did, collective_id, caller.did,
    )
    return {"status": "approved", "collective_id": str(collective_id), "agent_did": agent_did}


# ── DELETE /collectives/{id}/members/{did} ────────────────────────────────────

@router.delete(
    "/{collective_id}/members/{agent_did}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from collective",
)
async def remove_member(
    collective_id: UUID,
    agent_did:     str,
    request:       Request,
    caller:        AgentRecord = Depends(get_current_agent),
):
    """
    Remove a member from the collective.
    - Members can remove themselves (leave).
    - OWNER/ADMIN can remove any MEMBER.
    - OWNER cannot be removed (must transfer ownership first).
    """
    is_self = caller.did == agent_did

    if not is_self:
        async with get_db() as conn:
            caller_role = await conn.fetchval(
                """
                SELECT role FROM collective_members
                WHERE collective_id = $1 AND agent_did = $2 AND status = 'ACTIVE'
                """,
                collective_id, caller.did,
            )
        if caller_role not in ("OWNER", "ADMIN"):
            raise HTTPException(status_code=403, detail="Insufficient role to remove members")

    # Cannot remove OWNER
    async with get_db() as conn:
        target_role = await conn.fetchval(
            "SELECT role FROM collective_members WHERE collective_id = $1 AND agent_did = $2",
            collective_id, agent_did,
        )

    if target_role == "OWNER":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot remove the collective OWNER. Transfer ownership first.",
        )

    async with transaction() as conn:
        deleted = await conn.execute(
            "DELETE FROM collective_members WHERE collective_id = $1 AND agent_did = $2",
            collective_id, agent_did,
        )

    if deleted == "DELETE 0":
        raise HTTPException(status_code=404, detail=f"Member not found: {agent_did}")

    logger.info("Member %s removed from collective %s by %s", agent_did, collective_id, caller.did)
