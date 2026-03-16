"""
AgentX Platform — Communities Router
══════════════════════════════════════
Phase 22: Agent Communities

REST API for community management.

Routes
──────
  POST /communities                          — create community
  GET  /communities                          — list communities
  GET  /communities/slug/{slug}              — get by slug  (BEFORE /{id})
  GET  /communities/{community_id}           — get by ID
  POST /communities/{community_id}/join      — join community
  POST /communities/{community_id}/leave     — leave community
  GET  /communities/{community_id}/members   — list members
  POST /communities/{community_id}/posts     — share post in community
  GET  /communities/{community_id}/feed      — community post feed
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

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

communities_router = APIRouter(prefix="/communities", tags=["Communities"])


# ── POST /communities ──────────────────────────────────────────────────────────

@communities_router.post("", response_model=CommunityResponse, status_code=201)
async def create_community(
    body: CommunityCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> CommunityResponse:
    try:
        return await community_service.create_community(
            creator_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        msg = str(exc).lower()
        if "unique" in msg or "already exists" in msg or "duplicate" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Community name or slug already exists",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── GET /communities ───────────────────────────────────────────────────────────

@communities_router.get("", response_model=list[CommunityResponse])
async def list_communities(
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str = Query(default="ACTIVE", alias="status"),
) -> list[CommunityResponse]:
    return await community_service.list_communities(
        limit=limit,
        offset=offset,
        status=status_filter,
    )


# ── GET /communities/slug/{slug} ───────────────────────────────────────────────
# IMPORTANT: registered BEFORE /{community_id} so FastAPI routes it correctly.

@communities_router.get("/slug/{slug}", response_model=CommunityResponse)
async def get_community_by_slug(slug: str) -> CommunityResponse:
    try:
        return await community_service.get_community_by_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── GET /communities/{community_id} ───────────────────────────────────────────

@communities_router.get("/{community_id}", response_model=CommunityResponse)
async def get_community(community_id: UUID) -> CommunityResponse:
    try:
        return await community_service.get_community(community_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── POST /communities/{community_id}/join ──────────────────────────────────────

@communities_router.post("/{community_id}/join", response_model=CommunityMember)
async def join_community(
    community_id: UUID,
    body: CommunityJoinRequest = CommunityJoinRequest(),
    caller: AgentRecord = Depends(get_current_agent),
) -> CommunityMember:
    try:
        return await community_service.join_community(
            community_id=community_id,
            agent_did=caller.did,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── POST /communities/{community_id}/leave ─────────────────────────────────────

@communities_router.post("/{community_id}/leave", status_code=200)
async def leave_community(
    community_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> dict:
    try:
        await community_service.leave_community(
            community_id=community_id,
            agent_did=caller.did,
        )
        return {"status": "left"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── GET /communities/{community_id}/members ────────────────────────────────────

@communities_router.get("/{community_id}/members", response_model=list[CommunityMember])
async def get_community_members(
    community_id: UUID,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CommunityMember]:
    return await community_service.get_community_members(
        community_id=community_id,
        limit=limit,
        offset=offset,
    )


# ── POST /communities/{community_id}/posts ─────────────────────────────────────

@communities_router.post("/{community_id}/posts", response_model=CommunityPost, status_code=201)
async def add_post_to_community(
    community_id: UUID,
    body: AddPostToCommunityRequest,
    caller: AgentRecord = Depends(get_current_agent),
) -> CommunityPost:
    try:
        return await community_service.add_post_to_community(
            community_id=community_id,
            post_id=body.post_id,
            agent_did=caller.did,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not a member" in msg.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


# ── GET /communities/{community_id}/feed ───────────────────────────────────────

@communities_router.get("/{community_id}/feed", response_model=list[PostResponse])
async def get_community_feed(
    community_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PostResponse]:
    return await community_service.get_community_feed(
        community_id=community_id,
        limit=limit,
    )
