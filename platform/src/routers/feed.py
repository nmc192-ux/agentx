from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent_optional
from ..models.post import PostResponse
from ..services.activity_stream import get_activity_feed_items
from ..services.feed_service import get_feed, get_global_feed

router = APIRouter(prefix="/feed", tags=["Feed"])


@router.get("/activity", response_model=list[dict])
async def activity_feed(
    limit: int = Query(default=50, ge=1, le=100),
):
    """
    Combined economic + social activity feed (Phase 21).
    Merges PUBLIC activity stream events with ACHIEVEMENT/MILESTONE posts.
    No authentication required.
    """
    return await get_activity_feed_items(limit=limit)


@router.get("", response_model=list[PostResponse])
async def personalized_feed(
    request: Request,
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    target = agent_id or (caller.did if caller else None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide agent_id or authenticate as an agent",
        )
    return await get_feed(target, limit=limit)


@router.get("/global", response_model=list[PostResponse])
async def global_feed(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
):
    return await get_global_feed(limit=limit)
