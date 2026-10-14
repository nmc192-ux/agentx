"""
AgentX Platform — Activity Stream Router
═════════════════════════════════════════
Phase 21: Social-Economic Integration Layer

Endpoints:
  GET  /activity                          — Global PUBLIC activity stream  [no auth]
  GET  /agents/{agent_did}/activity-stream — Agent's activity stream: PUBLIC for anyone,
                                            everything for the agent itself
  POST /activity                          — Manually record activity        [auth required]
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..auth.middleware import AgentRecord, get_current_agent, get_current_agent_optional
from ..models.activity_stream import ActivityEvent, RecordActivityRequest
from ..pagination import NEXT_CURSOR_HEADER, decode_cursor, next_cursor
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
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="X-Next-Cursor from the previous page"),
    request: Request = None,
):
    """
    Return the most recent PUBLIC activity events across all agents.
    No authentication required.  The next page's cursor (if any) is in the
    X-Next-Cursor response header.
    """
    after = tuple(decode_cursor(cursor, (datetime, UUID))) if cursor else None
    events = await activity_stream_svc.get_global_activity_stream(limit=limit, after=after)
    _set_next_cursor(response, events, limit)
    return events


# ── GET /agents/{agent_did}/activity-stream ────────────────────────────────────

@router.get(
    "/agents/{agent_did}/activity-stream",
    response_model=list[ActivityEvent],
    summary="Agent activity stream",
)
async def get_agent_activity_stream(
    agent_did: str,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="X-Next-Cursor from the previous page"),
    request: Request = None,
    caller: AgentRecord | None = Depends(get_current_agent_optional),
):
    """
    Return the activity stream for a specific agent.
    Anyone sees its PUBLIC entries; the agent itself (logged in) sees all.

    S9-6e: this returned every entry whatever its visibility, so PRIVATE,
    FOLLOWERS and COLLECTIVE entries were readable without a login.
    FOLLOWERS / COLLECTIVE are not widened to followers or members here:
    nothing checks those relationships yet, so they stay owner-only.
    """
    after = tuple(decode_cursor(cursor, (datetime, UUID))) if cursor else None
    events = await activity_stream_svc.get_agent_activity_stream(
        agent_did=agent_did,
        limit=limit,
        public_only=caller is None or caller.did != agent_did,
        after=after,
    )
    _set_next_cursor(response, events, limit)
    return events


def _set_next_cursor(response: Response, events: list[ActivityEvent], limit: int) -> None:
    cur = next_cursor(events, limit, "created_at", "stream_id")
    if cur:
        response.headers[NEXT_CURSOR_HEADER] = cur


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
