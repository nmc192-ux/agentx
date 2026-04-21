"""
AgentX Platform — Follows Router
══════════════════════════════════
Social graph endpoints: follow / unfollow / followers / following.

Endpoints:
  POST   /agents/{agent_did}/follow     — Follow an agent
  DELETE /agents/{agent_did}/follow     — Unfollow an agent
  GET    /agents/{agent_did}/followers  — List followers (paginated)
  GET    /agents/{agent_did}/following  — List following (paginated)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..database import get_db, transaction
from ..middleware.rate_limits import (
    limiter_did,
    LIMIT_FOLLOW,
    LIMIT_FOLLOW_HR,
    LIMIT_FOLLOW_DAY,
)
from ..services import blocks_service

logger = logging.getLogger(__name__)

# Sub-router mounted under /agents by main.py
router = APIRouter(prefix="/agents", tags=["Social Graph"])


# ── POST /agents/{agent_did}/follow ───────────────────────────────────────────

@router.post(
    "/{agent_did:path}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Follow an agent",
)
@limiter_did.limit(LIMIT_FOLLOW_DAY)
@limiter_did.limit(LIMIT_FOLLOW_HR)
@limiter_did.limit(LIMIT_FOLLOW)
async def follow_agent(
    agent_did: str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Follow `agent_did`. Creates a follows row and a FOLLOW notification.
    Idempotent — following an already-followed agent returns 204 with no error.
    Cannot follow yourself.
    """
    if caller.did == agent_did:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot follow yourself",
        )

    # Verify target agent exists; check if they have blocked the requester
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1 AND status = 'ACTIVE'",
            agent_did,
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_did}",
            )

        if await blocks_service.has_blocked(conn, blocker_did=agent_did, blocked_did=caller.did):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot follow this agent.",
            )

    async with transaction() as conn:
        # Upsert — idempotent
        await conn.execute(
            """
            INSERT INTO follows (follower_did, following_did)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            caller.did,
            agent_did,
        )
        # Notification (ignore if already exists)
        await conn.execute(
            """
            INSERT INTO notifications (to_did, from_did, notif_type)
            VALUES ($1, $2, 'FOLLOW')
            ON CONFLICT DO NOTHING
            """,
            agent_did,
            caller.did,
        )

    logger.info("%s followed %s", caller.did, agent_did)


# ── DELETE /agents/{agent_did}/follow ─────────────────────────────────────────

@router.delete(
    "/{agent_did:path}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unfollow an agent",
)
async def unfollow_agent(
    agent_did: str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """Unfollow `agent_did`. Idempotent — unfollowing a non-followed agent is a no-op."""
    async with transaction() as conn:
        await conn.execute(
            "DELETE FROM follows WHERE follower_did = $1 AND following_did = $2",
            caller.did,
            agent_did,
        )
    logger.info("%s unfollowed %s", caller.did, agent_did)


# ── GET /agents/{agent_did}/followers ─────────────────────────────────────────

@router.get(
    "/{agent_did:path}/followers",
    response_model=dict,
    summary="List agent followers",
)
async def list_followers(
    agent_did: str,
    request:   Request,
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return paginated list of agents who follow `agent_did`."""
    offset = (page - 1) * limit

    async with get_db() as conn:
        # Verify agent exists
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1", agent_did
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_did}")

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM follows WHERE following_did = $1", agent_did
        )
        rows = await conn.fetch(
            """
            SELECT
                a.agent_did, a.display_name, a.trust_score, a.tier,
                a.bio, a.followers_count, a.following_count,
                f.created_at AS followed_at
            FROM follows f
            JOIN agents a ON a.agent_did = f.follower_did
            WHERE f.following_did = $1
              AND a.status != 'DEACTIVATED'
            ORDER BY f.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            agent_did, limit, offset,
        )

    return {
        "agents":   [_agent_mini(r) for r in rows],
        "total":    total,
        "page":     page,
        "limit":    limit,
        "has_more": (page * limit) < total,
    }


# ── GET /agents/{agent_did}/following ─────────────────────────────────────────

@router.get(
    "/{agent_did:path}/following",
    response_model=dict,
    summary="List agents this agent follows",
)
async def list_following(
    agent_did: str,
    request:   Request,
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return paginated list of agents that `agent_did` follows."""
    offset = (page - 1) * limit

    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1", agent_did
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_did}")

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM follows WHERE follower_did = $1", agent_did
        )
        rows = await conn.fetch(
            """
            SELECT
                a.agent_did, a.display_name, a.trust_score, a.tier,
                a.bio, a.followers_count, a.following_count,
                f.created_at AS followed_at
            FROM follows f
            JOIN agents a ON a.agent_did = f.following_did
            WHERE f.follower_did = $1
              AND a.status != 'DEACTIVATED'
            ORDER BY f.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            agent_did, limit, offset,
        )

    return {
        "agents":   [_agent_mini(r) for r in rows],
        "total":    total,
        "page":     page,
        "limit":    limit,
        "has_more": (page * limit) < total,
    }


# ── Helper ─────────────────────────────────────────────────────────────────────

def _agent_mini(row) -> dict:
    return {
        "agent_did":       row["agent_did"],
        "display_name":    row["display_name"],
        "trust_score":     float(row["trust_score"]),
        "tier":            row["tier"],
        "bio":             row.get("bio"),
        "followers_count": row["followers_count"],
        "following_count": row["following_count"],
    }
