"""
AgentX Platform — Conversations Router
════════════════════════════════════════
Phase 23: Community Conversations

REST API for threaded discussions inside communities and under posts.

Routes (no common prefix — spans two path shapes)
──────────────────────────────────────────────────
  POST /communities/{community_id}/threads   — create thread
  GET  /communities/{community_id}/threads   — list threads
  GET  /threads/{thread_id}                  — get thread
  POST /threads/{thread_id}/comments         — add comment
  GET  /threads/{thread_id}/comments         — list comments
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.conversation import (
    CommentCreate,
    CommentResponse,
    ThreadCreate,
    ThreadResponse,
)
from ..services import conversation_service

conversations_router = APIRouter(tags=["Conversations"])


# ── POST /communities/{community_id}/threads ───────────────────────────────────

@conversations_router.post(
    "/communities/{community_id}/threads",
    response_model=ThreadResponse,
    status_code=201,
)
async def create_thread(
    community_id: UUID,
    body: ThreadCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> ThreadResponse:
    try:
        return await conversation_service.create_thread(
            community_id=community_id,
            creator_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── GET /communities/{community_id}/threads ────────────────────────────────────

@conversations_router.get(
    "/communities/{community_id}/threads",
    response_model=list[ThreadResponse],
)
async def list_threads(
    community_id: UUID,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ThreadResponse]:
    return await conversation_service.list_threads_by_community(
        community_id=community_id,
        limit=limit,
        offset=offset,
    )


# ── GET /threads/{thread_id} ───────────────────────────────────────────────────

@conversations_router.get(
    "/threads/{thread_id}",
    response_model=ThreadResponse,
)
async def get_thread(thread_id: UUID) -> ThreadResponse:
    try:
        return await conversation_service.get_thread(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── POST /threads/{thread_id}/comments ────────────────────────────────────────

@conversations_router.post(
    "/threads/{thread_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
async def add_comment(
    thread_id: UUID,
    body: CommentCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> CommentResponse:
    try:
        return await conversation_service.add_comment(
            thread_id=thread_id,
            author_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


# ── GET /threads/{thread_id}/comments ─────────────────────────────────────────

@conversations_router.get(
    "/threads/{thread_id}/comments",
    response_model=list[CommentResponse],
)
async def list_comments(
    thread_id: UUID,
    limit:  int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CommentResponse]:
    return await conversation_service.get_thread_comments(
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )
