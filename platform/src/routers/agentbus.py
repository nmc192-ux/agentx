"""
AgentX Platform — Agent Bus Router
════════════════════════════════════
Phase 11: Real-time agent-to-agent messaging.

All inbound messages are validated against the ACP-1.0 envelope schema
defined in ``models.acp``.  Malformed messages are rejected with HTTP 422
before they reach the service layer.

Endpoints
─────────
  POST /agentbus/send    — send an ACP message (requires auth)
  GET  /agentbus/inbox   — list received messages (requires auth)
  GET  /agentbus/inbox?type=<acp_type> — filter by message type
  GET  /agentbus/stream  — SSE stream of incoming messages (requires auth)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..auth.middleware import get_current_agent
from ..models.acp import ACPMessageCreate, ACPMessageResponse
from ..services import agentbus_service

logger = logging.getLogger(__name__)

agentbus_router = APIRouter(prefix="/agentbus", tags=["Agent Bus"])


# ── POST /agentbus/send ───────────────────────────────────────────────────────

@agentbus_router.post(
    "/send",
    response_model=ACPMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an ACP-1.0 message to another agent (or broadcast)",
)
async def send_message(
    body: ACPMessageCreate,
    agent=Depends(get_current_agent),
) -> ACPMessageResponse:
    """
    Send an ACP-1.0 message from the authenticated agent.

    The request body is validated against the full ACP envelope schema:
    - ``protocol_version`` must be ``"ACP-1.0"``
    - ``type`` must be one of the seven allowed message types
    - ``agent_id`` must match ``did:method:id`` format
    - ``message_id`` and ``timestamp`` may be omitted (server fills them in)

    Returns HTTP 422 with field-level errors for any validation failure.
    Returns HTTP 404 if ``receiver_did`` is not a registered agent.
    Requires authentication.
    """
    try:
        return await agentbus_service.send_acp_message(
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
    response_model=List[ACPMessageResponse],
    summary="List ACP messages in the authenticated agent's inbox",
)
async def get_inbox(
    limit: Optional[int] = Query(default=50, ge=1, le=500),
    offset: Optional[int] = Query(default=0, ge=0),
    type: Optional[str] = Query(  # noqa: A002
        default=None,
        description="Filter by ACP message type (e.g. task_request)",
    ),
    since: Optional[str] = Query(
        default=None,
        description="ISO-8601 datetime — return only messages after this time",
    ),
    agent=Depends(get_current_agent),
) -> List[ACPMessageResponse]:
    """
    Return ACP messages addressed to the authenticated agent, newest first.

    Supports filtering by ``type`` (ACP message type) and ``since``
    (ISO-8601 datetime).  Pagination via ``limit`` / ``offset``.
    Requires authentication.
    """
    return await agentbus_service.get_acp_inbox(
        agent_did=agent.did,
        limit=limit,
        offset=offset,
        acp_type=type,
        since=since,
    )


# ── GET /agentbus/stream ──────────────────────────────────────────────────────

@agentbus_router.get(
    "/stream",
    summary="Stream incoming ACP messages via Server-Sent Events",
)
async def stream_messages(
    agent=Depends(get_current_agent),
) -> StreamingResponse:
    """
    Open a Server-Sent Events stream that delivers new ACP messages to the
    authenticated agent in real time.

    The stream subscribes to the Redis pub/sub channel
    ``agentbus:{agent.did}`` and forwards each incoming message as an
    SSE ``data:`` frame containing the full ACP envelope JSON.

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
