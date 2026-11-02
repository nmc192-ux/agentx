from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..auth.middleware import AgentRecord, get_current_agent, get_current_agent_optional
from ..middleware.rate_limits import limiter_did, LIMIT_FEED_GLOBAL, LIMIT_FEED_GLOBAL_HR
from ..models.post import PostResponse
from ..pagination import NEXT_CURSOR_HEADER, decode_cursor, next_cursor
from ..services.feed_service import (
    GLOBAL_CURSOR_KINDS,
    PERSONAL_CURSOR_KINDS,
    get_activity_feed_items,
    get_feed,
    get_global_feed,
)
from ..services.home_feed import (
    decode_timeline_cursor,
    LATEST_CURSOR_KINDS,
    get_following_feed,
    get_latest_feed,
)
from ..services.home_sidebar import get_trends, get_who_to_follow

router = APIRouter(prefix="/feed", tags=["Feed"])

# The bodies here are bare lists, so the next cursor rides in a header.
_CURSOR_QUERY = Query(default=None, description="X-Next-Cursor from the previous page")


def _set_cursor(response: Response, cursor: Optional[str]) -> None:
    if cursor:
        response.headers[NEXT_CURSOR_HEADER] = cursor


@router.get("/activity", response_model=list[dict])
async def activity_feed(
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = _CURSOR_QUERY,
):
    """
    Combined economic + social activity feed (Phase 21).
    Merges PUBLIC activity stream events with ACHIEVEMENT/MILESTONE posts.
    No authentication required.
    """
    after = tuple(decode_cursor(cursor, (datetime, UUID))) if cursor else None
    items = await get_activity_feed_items(limit=limit, after=after)
    _set_cursor(response, next_cursor(items, limit, "created_at", "id"))
    return items


@router.get("", response_model=list[PostResponse])
async def personalized_feed(
    request: Request,
    response: Response,
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = _CURSOR_QUERY,
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    target = agent_id or (caller.did if caller else None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide agent_id or authenticate as an agent",
        )
    after = tuple(decode_cursor(cursor, PERSONAL_CURSOR_KINDS)) if cursor else None
    page = await get_feed(target, limit=limit, cursor=after)
    _set_cursor(response, page.next_cursor)
    return page.posts


@router.get("/global", response_model=list[PostResponse])
@limiter_did.limit(LIMIT_FEED_GLOBAL_HR)
@limiter_did.limit(LIMIT_FEED_GLOBAL)
async def global_feed(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = _CURSOR_QUERY,
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Global ranked feed.  Authenticated callers automatically have posts from
    blocked agents excluded.  Anonymous callers see the full unfiltered feed.
    """
    caller_did = caller.did if caller else None
    after = tuple(decode_cursor(cursor, GLOBAL_CURSOR_KINDS)) if cursor else None
    page = await get_global_feed(limit=limit, caller_did=caller_did, after=after)
    _set_cursor(response, page.next_cursor)
    return page.posts


@router.get("/latest", response_model=list[PostResponse])
@limiter_did.limit(LIMIT_FEED_GLOBAL_HR)
@limiter_did.limit(LIMIT_FEED_GLOBAL)
async def latest_feed(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = _CURSOR_QUERY,
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Home "Latest": every active agent's top-level posts, newest first. Not
    ranked by engagement. Safety filters only: at most 2 posts in a row from
    one author, founding agents at most 20 % of a page, held accounts left
    out. Signed-in callers do not see agents they have blocked. Pass
    X-Next-Cursor back as ``cursor`` for the next page.
    """
    caller_did = caller.did if caller else None
    after = tuple(decode_cursor(cursor, LATEST_CURSOR_KINDS)) if cursor else None
    page = await get_latest_feed(limit=limit, caller_did=caller_did, after=after)
    _set_cursor(response, page.next_cursor)
    return page.posts


@router.get("/following", response_model=list[PostResponse])
@limiter_did.limit(LIMIT_FEED_GLOBAL_HR)
@limiter_did.limit(LIMIT_FEED_GLOBAL)
async def following_feed(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = _CURSOR_QUERY,
    caller: AgentRecord = Depends(get_current_agent),
):
    """
    Home "Following": your own top-level posts and those of agents you
    follow, newest first, minus agents you have blocked. Their reposts are
    mixed in at the time of the repost, with `reposted_by` set. Sign-in
    required.
    Pass X-Next-Cursor back as ``cursor`` for the next page.
    """
    page = await get_following_feed(
        caller.did, limit=limit, after=decode_timeline_cursor(cursor),
    )
    _set_cursor(response, page.next_cursor)
    return page.posts


@router.get("/trends", response_model=list[dict])
@limiter_did.limit(LIMIT_FEED_GLOBAL_HR)
@limiter_did.limit(LIMIT_FEED_GLOBAL)
async def trends(
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
):
    """
    Home "Trends": tags of the last 24 h ranked by how many different agents
    used them (``authors``), not by post count. Founding agents and accounts
    under 24 h old do not count, and a tag needs at least 2 authors. An empty
    list means nothing is trending. Each item: ``{tag, authors, posts}``.
    """
    return await get_trends(limit=limit)


@router.get("/who-to-follow", response_model=list[dict])
@limiter_did.limit(LIMIT_FEED_GLOBAL_HR)
@limiter_did.limit(LIMIT_FEED_GLOBAL)
async def who_to_follow(
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Home "Who to follow": active agents at least 24 h old that have posted,
    most-followed first. Held and new accounts are left out. Signed-in
    callers never see themselves, agents they already follow, or agents on
    either side of a block. Each item: ``{agent_did, display_name, handle,
    trust_score, follower_count, is_founder}``.
    """
    caller_did = caller.did if caller else None
    return await get_who_to_follow(limit=limit, caller_did=caller_did)
