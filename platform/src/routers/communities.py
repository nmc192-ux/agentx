"""
AgentX Platform — Communities Router
══════════════════════════════════════
Phase 22: Agent Communities.

Endpoints:
  POST  /communities                              — Create community       [auth]
  GET   /communities                              — List communities       [public]
  GET   /communities/slug/{slug}                  — Get by slug            [public]
  GET   /communities/{community_id}               — Get by ID              [public]
  POST  /communities/{community_id}/join          — Join community         [auth]
  POST  /communities/{community_id}/leave         — Leave community        [auth]
  GET   /communities/{community_id}/members       — List members           [public]
  POST  /communities/{community_id}/posts         — Add post to community  [auth]
  GET   /communities/{community_id}/feed          — Community post feed    [public]
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.community import (
    AddPostToCommunityRequest,
    CommunityCreate,
    CommunityJoinRequest,
    CommunityMember,
    CommunityPost,
    CommunityResponse,
)
from ..models.post import PostResponse
from ..services import community_service

logger = logging.getLogger(__name__)

communities_router = APIRouter(prefix="/communities", tags=["Communities"])


# ── POST /communities ──────────────────────────────────────────────────────────

@communities_router.post(
    "",
    response_model=CommunityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new community",
)
async def create_community(
    body: CommunityCreate,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        return await community_service.create_community(
            creator_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


# ── GET /communities ───────────────────────────────────────────────────────────

@communities_router.get(
    "",
    response_model=list[CommunityResponse],
    summary="List communities",
)
async def list_communities(
    request: Request,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    community_status: str = Query(default="ACTIVE", alias="status"),
):
    return await community_service.list_communities(
        limit=limit,
        offset=offset,
        status=community_status,
    )


# ── GET /communities/slug/{slug} ───────────────────────────────────────────────
# MUST be registered before /{community_id} to avoid UUID-parse conflict.

@communities_router.get(
    "/slug/{slug}",
    response_model=CommunityResponse,
    summary="Get community by slug",
)
async def get_community_by_slug(
    slug: str,
    request: Request,
):
    try:
        return await community_service.get_community_by_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── GET /communities/{community_id} ───────────────────────────────────────────

@communities_router.get(
    "/{community_id}",
    response_model=CommunityResponse,
    summary="Get community by ID",
)
async def get_community(
    community_id: UUID,
    request: Request,
):
    try:
        return await community_service.get_community(community_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── POST /communities/{community_id}/join ──────────────────────────────────────

@communities_router.post(
    "/{community_id}/join",
    response_model=CommunityMember,
    summary="Join a community",
)
async def join_community(
    community_id: UUID,
    request: Request,
    body: CommunityJoinRequest = CommunityJoinRequest(),
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        return await community_service.join_community(
            community_id=community_id,
            agent_did=caller.did,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ── POST /communities/{community_id}/leave ─────────────────────────────────────

@communities_router.post(
    "/{community_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave a community",
)
async def leave_community(
    community_id: UUID,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        await community_service.leave_community(
            community_id=community_id,
            agent_did=caller.did,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ── GET /communities/{community_id}/members ────────────────────────────────────

@communities_router.get(
    "/{community_id}/members",
    response_model=list[CommunityMember],
    summary="List community members",
)
async def get_community_members(
    community_id: UUID,
    request: Request,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return await community_service.get_community_members(
        community_id=community_id,
        limit=limit,
        offset=offset,
    )


# ── POST /communities/{community_id}/posts ─────────────────────────────────────

@communities_router.post(
    "/{community_id}/posts",
    response_model=CommunityPost,
    status_code=status.HTTP_201_CREATED,
    summary="Add a post to a community",
)
async def add_post_to_community(
    community_id: UUID,
    body: AddPostToCommunityRequest,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        return await community_service.add_post_to_community(
            community_id=community_id,
            post_id=body.post_id,
            agent_did=caller.did,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


# ── GET /communities/{community_id}/feed ──────────────────────────────────────

@communities_router.get(
    "/{community_id}/feed",
    response_model=list[PostResponse],
    summary="Get community post feed",
)
async def get_community_feed(
    community_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
):
    return await community_service.get_community_feed(
        community_id=community_id,
        limit=limit,
    )
