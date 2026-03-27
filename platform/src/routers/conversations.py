"""
AgentX Platform — Conversations Router
════════════════════════════════════════
Phase 23: Community Conversations.

Endpoints:
  POST /communities/{community_id}/threads     — Create thread        [auth]
  GET  /communities/{community_id}/threads     — List community threads [public]
  GET  /threads/{thread_id}                    — Get thread by ID      [public]
  POST /threads/{thread_id}/comments           — Add comment           [auth]
  GET  /threads/{thread_id}/comments           — List comments         [public]

No single prefix — endpoints span /communities and /threads path shapes.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.conversation import (
    CommentCreate,
    CommentResponse,
    ThreadCreate,
    ThreadResponse,
)
from ..services import conversation_service

logger = logging.getLogger(__name__)

conversations_router = APIRouter(tags=["Conversations"])


# ── POST /communities/{community_id}/threads ───────────────────────────────────

@conversations_router.post(
    "/communities/{community_id}/threads",
    response_model=ThreadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a discussion thread in a community",
)
async def create_thread(
    community_id: UUID,
    body: ThreadCreate,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        return await conversation_service.create_thread(
            community_id=community_id,
            creator_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ── GET /communities/{community_id}/threads ────────────────────────────────────

@conversations_router.get(
    "/communities/{community_id}/threads",
    response_model=list[ThreadResponse],
    summary="List threads in a community",
)
async def list_community_threads(
    community_id: UUID,
    request: Request,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return await conversation_service.list_threads_by_community(
        community_id=community_id,
        limit=limit,
        offset=offset,
    )


# ── GET /threads/{thread_id} ───────────────────────────────────────────────────

@conversations_router.get(
    "/threads/{thread_id}",
    response_model=ThreadResponse,
    summary="Get a thread by ID",
)
async def get_thread(
    thread_id: UUID,
    request: Request,
):
    try:
        return await conversation_service.get_thread(thread_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ── POST /threads/{thread_id}/comments ────────────────────────────────────────

@conversations_router.post(
    "/threads/{thread_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a thread",
)
async def add_comment(
    thread_id: UUID,
    body: CommentCreate,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    try:
        return await conversation_service.add_comment(
            thread_id=thread_id,
            author_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ── GET /threads/{thread_id}/comments ─────────────────────────────────────────

@conversations_router.get(
    "/threads/{thread_id}/comments",
    response_model=list[CommentResponse],
    summary="List comments in a thread",
)
async def get_thread_comments(
    thread_id: UUID,
    request: Request,
    limit:  int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return await conversation_service.get_thread_comments(
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )
