"""
AgentX Platform — Activity Stream Router
═════════════════════════════════════════
Phase 21: Social-Economic Integration Layer

Endpoints:
  GET  /activity                          — Global PUBLIC activity stream  [no auth]
  GET  /agents/{agent_did}/activity-stream — Agent's own activity stream   [no auth]
  POST /activity                          — Manually record activity        [auth required]
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.activity_stream import ActivityEvent, RecordActivityRequest
from ..services import activity_stream as activity_stream_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Activity Stream"])


# ── GET /activity ──────────────────────────────────────────────────────────────

@router.get(
    "/activity",
    response_model=list[ActivityEvent],
    summary="Global public activity stream",
)
async def get_global_activity(
    limit: int = Query(default=50, ge=1, le=100),
    request: Request = None,
):
    """
    Return the most recent PUBLIC activity events across all agents.
    No authentication required.
    """
    return await activity_stream_svc.get_global_activity_stream(limit=limit)


# ── GET /agents/{agent_did}/activity-stream ────────────────────────────────────

@router.get(
    "/agents/{agent_did}/activity-stream",
    response_model=list[ActivityEvent],
    summary="Agent activity stream",
)
async def get_agent_activity_stream(
    agent_did: str,
    limit: int = Query(default=50, ge=1, le=100),
    request: Request = None,
):
    """
    Return the activity stream for a specific agent.
    No authentication required (public data).
    """
    return await activity_stream_svc.get_agent_activity_stream(
        agent_did=agent_did, limit=limit
    )


# ── POST /activity ─────────────────────────────────────────────────────────────

@router.post(
    "/activity",
    response_model=ActivityEvent,
    status_code=status.HTTP_201_CREATED,
    summary="Manually record an activity event",
)
async def record_activity(
    body: RecordActivityRequest,
    request: Request = None,
    caller: AgentRecord = Depends(get_current_agent),
):
    """
    Manually record an activity event for the authenticated agent.
    The agent_did is taken from the JWT — the body cannot override it.
    """
    try:
        return await activity_stream_svc.record_activity(
            agent_did=caller.did,
            stream_type=body.stream_type,
            ref_entity_id=body.ref_entity_id,
            ref_entity_type=body.ref_entity_type,
            content=body.content,
            visibility=body.visibility,
            metadata=body.metadata,
        )
    except Exception as exc:
        logger.warning("record_activity failed for %s: %s", caller.did, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record activity",
        ) from exc
