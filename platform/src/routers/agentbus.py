"""
AgentX Platform — Agent Bus Router
════════════════════════════════════
Phase 11: Real-time agent-to-agent messaging.

Endpoints
─────────
  POST /agentbus/send    — send a direct message (requires auth)
  GET  /agentbus/inbox   — list received messages (requires auth)
  GET  /agentbus/stream  — SSE stream of incoming messages (requires auth)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..auth.middleware import get_current_agent
from ..models.agentbus import AgentMessageCreate, AgentMessageResponse
from ..services import agentbus_service

logger = logging.getLogger(__name__)

agentbus_router = APIRouter(prefix="/agentbus", tags=["Agent Bus"])


# ── POST /agentbus/send ───────────────────────────────────────────────────────

@agentbus_router.post(
    "/send",
    response_model=AgentMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a direct message to another agent",
)
async def send_message(
    body: AgentMessageCreate,
    agent=Depends(get_current_agent),
) -> AgentMessageResponse:
    """
    Send a direct message from the authenticated agent to receiver_did.
    The message is persisted and published to the receiver's SSE stream.
    Requires authentication.
    """
    try:
        return await agentbus_service.send_message(
            sender_did=agent.did,
            data=body,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


# ── GET /agentbus/inbox ───────────────────────────────────────────────────────

@agentbus_router.get(
    "/inbox",
    response_model=List[AgentMessageResponse],
    summary="List messages in the authenticated agent's inbox",
)
async def get_inbox(
    limit: Optional[int] = Query(default=50, ge=1, le=500),
    offset: Optional[int] = Query(default=0, ge=0),
    agent=Depends(get_current_agent),
) -> List[AgentMessageResponse]:
    """
    Return messages addressed to the authenticated agent, newest first.
    Supports pagination via ``limit`` and ``offset`` query parameters.
    Requires authentication.
    """
    return await agentbus_service.get_inbox(
        agent_did=agent.did,
        limit=limit,
        offset=offset,
    )


# ── GET /agentbus/stream ──────────────────────────────────────────────────────

@agentbus_router.get(
    "/stream",
    summary="Stream incoming messages via Server-Sent Events",
)
async def stream_messages(
    agent=Depends(get_current_agent),
) -> StreamingResponse:
    """
    Open a Server-Sent Events stream that delivers new messages to the
    authenticated agent in real time.

    The stream subscribes to the Redis pub/sub channel
    ``agentbus:{agent.did}`` and forwards each incoming message as an
    SSE ``data:`` frame.

    Requires authentication. Returns ``text/event-stream``.
    """
    return StreamingResponse(
        agentbus_service.stream_messages(agent.did),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
