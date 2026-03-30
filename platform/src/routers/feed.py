from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent_optional
from ..models.post import PostResponse
from ..services.feed_service import generate_feed, get_feed, get_global_feed, get_trending_posts

router = APIRouter(prefix="/feed", tags=["Feed"])


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


@router.get("/trending", response_model=list[PostResponse], summary="Trending posts")
async def trending_feed(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168, description="Time window in hours"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return posts ranked by engagement velocity (likes, replies, interactions)."""
    return await get_trending_posts(hours=hours, limit=limit)


@router.get("/global", response_model=list[PostResponse])
async def global_feed(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
):
    return await get_global_feed(limit=limit)
