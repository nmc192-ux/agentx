"""
AgentX Platform — Collective Service
═════════════════════════════════════
Phase 6: Agent Collectives

Business logic for collective management.  All DB access uses asyncpg via
get_db() / transaction() context managers (no ORM).

Functions:
  create_collective()          — persist collective + OWNER membership
  join_collective()            — create PENDING membership request
  list_collectives()           — paginated public list with live member counts
  get_members()                — fetch ACTIVE members of a collective
  assign_task_to_collective()  — link a marketplace task to a collective

SOURCE: ATLAS Phase 1 / Phase 6 implementation plan
"""
from __future__ import annotations

import logging
import uuid
from uuid import UUID

from ..database import get_db, transaction
from ..models.collective import (
    CollectiveListResponse,
    CollectiveMemberResponse,
    CollectiveResponse,
    CollectiveTaskResponse,
)

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

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


# ── create_collective ──────────────────────────────────────────────────────────

async def create_collective(
    name: str,
    description: str,
    charter: str | None,
    is_public: bool,
    owner_did: str,
) -> CollectiveResponse:
    """
    Create a collective and add the owner as the first ACTIVE OWNER member.

    Args:
        name:        Collective name (1–128 chars).
        description: Collective description (1–1024 chars).
        charter:     Optional governance charter text (max 5 000 chars).
        is_public:   Whether the collective is publicly discoverable.
        owner_did:   DID of the founding agent (becomes OWNER).

    Returns:
        CollectiveResponse for the newly created collective.
    """
    collective_id = uuid.uuid4()

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO collectives (collective_id, name, description, charter, is_public, owner_did)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING collective_id, name, description, charter, is_public, owner_did, created_at
            """,
            collective_id, name, description, charter, is_public, owner_did,
        )
        await conn.execute(
            """
            INSERT INTO collective_members (collective_id, agent_did, role, status)
            VALUES ($1, $2, 'OWNER', 'ACTIVE')
            """,
            collective_id, owner_did,
        )

    logger.info("Collective %s created by %s", collective_id, owner_did)
    result = dict(row)
    result["member_count"] = 1
    result["trust_score_avg"] = 0.0
    return _row_to_collective(result)


# ── join_collective ────────────────────────────────────────────────────────────

async def join_collective(collective_id: UUID, agent_did: str) -> dict:
    """
    Create a PENDING membership request for an agent.

    Idempotent: ON CONFLICT DO NOTHING means repeated calls are safe.

    Returns:
        Dict with status, collective_id, agent_did.

    Raises:
        ValueError: if collective does not exist.
    """
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM collectives WHERE collective_id = $1",
            collective_id,
        )
    if not exists:
        raise ValueError(f"Collective not found: {collective_id}")

    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO collective_members (collective_id, agent_did, role, status)
            VALUES ($1, $2, 'MEMBER', 'PENDING')
            ON CONFLICT (collective_id, agent_did) DO NOTHING
            """,
            collective_id, agent_did,
        )

    logger.info("%s requested to join collective %s", agent_did, collective_id)
    return {"status": "pending", "collective_id": str(collective_id), "agent_did": agent_did}


# ── list_collectives ───────────────────────────────────────────────────────────

async def list_collectives(
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> CollectiveListResponse:
    """
    Return a paginated list of public collectives with live member counts.

    Args:
        q:     Optional substring search on collective name (case-insensitive).
        page:  1-based page number.
        limit: Results per page (1–100).

    Returns:
        CollectiveListResponse with pagination metadata.
    """
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
        total=int(total),
        page=page,
        limit=limit,
        has_more=(page * limit) < total,
    )


# ── get_members ────────────────────────────────────────────────────────────────

async def get_members(collective_id: UUID) -> list[CollectiveMemberResponse]:
    """
    Fetch ACTIVE members of a collective, ordered by role then trust score.

    Raises:
        ValueError: if collective does not exist.
    """
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM collectives WHERE collective_id = $1",
            collective_id,
        )
        if not exists:
            raise ValueError(f"Collective not found: {collective_id}")

        rows = await conn.fetch(
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

    return [
        CollectiveMemberResponse(
            agent_did=r["agent_did"],
            display_name=r["display_name"],
            role=r["role"],
            status=r["status"],
            trust_score=float(r["trust_score"]),
            joined_at=r["joined_at"],
        )
        for r in rows
    ]


# ── assign_task_to_collective ──────────────────────────────────────────────────

async def assign_task_to_collective(
    collective_id: UUID,
    task_id: UUID,
    assigned_by_did: str,
) -> CollectiveTaskResponse:
    """
    Assign a marketplace task to a collective for collaborative execution.

    Validates:
      - Collective exists.
      - Task exists.
      - The assigning agent is an OWNER or ADMIN of the collective.

    Creates a collective_tasks record (idempotent via UNIQUE constraint) and
    stamps executor_collective_id on the task row.

    Returns:
        CollectiveTaskResponse for the assignment record.

    Raises:
        ValueError: on any validation failure.
    """
    async with transaction() as conn:
        # Verify collective
        collective_exists = await conn.fetchval(
            "SELECT 1 FROM collectives WHERE collective_id = $1",
            collective_id,
        )
        if not collective_exists:
            raise ValueError(f"Collective not found: {collective_id}")

        # Verify task
        task_row = await conn.fetchrow(
            "SELECT task_id, status FROM tasks WHERE task_id = $1",
            task_id,
        )
        if task_row is None:
            raise ValueError(f"Task not found: {task_id}")

        # Verify assigner is OWNER or ADMIN
        assigner_role = await conn.fetchval(
            """
            SELECT role FROM collective_members
            WHERE collective_id = $1 AND agent_did = $2 AND status = 'ACTIVE'
            """,
            collective_id, assigned_by_did,
        )
        if assigner_role not in ("OWNER", "ADMIN"):
            raise ValueError(
                f"Agent {assigned_by_did!r} must be OWNER or ADMIN of collective {collective_id}"
            )

        # Upsert collective_task record
        row = await conn.fetchrow(
            """
            INSERT INTO collective_tasks (collective_id, task_id, assigned_by_did, status)
            VALUES ($1, $2, $3, 'assigned')
            ON CONFLICT (collective_id, task_id) DO UPDATE
                SET status = collective_tasks.status
            RETURNING
                collective_task_id, collective_id, task_id,
                assigned_by_did, status, assigned_at
            """,
            collective_id, task_id, assigned_by_did,
        )

        # Stamp executor_collective_id on the task
        await conn.execute(
            "UPDATE tasks SET executor_collective_id = $1 WHERE task_id = $2",
            collective_id, task_id,
        )

    logger.info(
        "Task %s assigned to collective %s by %s",
        task_id, collective_id, assigned_by_did,
    )
    return CollectiveTaskResponse(
        collective_task_id=row["collective_task_id"],
        collective_id=row["collective_id"],
        task_id=row["task_id"],
        assigned_by_did=row["assigned_by_did"],
        status=row["status"],
        assigned_at=row["assigned_at"],
    )
