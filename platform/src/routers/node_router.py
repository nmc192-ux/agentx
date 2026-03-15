"""
AgentX Platform — Federated Node Router
════════════════════════════════════════
Phase 17: Federated AgentX Nodes.

Endpoints
─────────
  POST /nodes/register  — register (upsert) a peer node
  GET  /nodes           — list all known peer nodes
  POST /nodes/events    — receive a federated event from a peer node

Design notes
────────────
• /nodes/register is intentionally open (no auth) so peer nodes can
  self-register without needing a JWT from this node's auth system.
• /nodes/events is similarly open so peers can push events in; the
  source_node_url in the body is used for correlation only.
• Future hardening: signature verification on inbound events and
  mandatory auth on /nodes/register.
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from ..models.node import (
    FederatedEventRequest,
    NodeMessageResponse,
    NodeResponse,
    RegisterNodeRequest,
)
from ..services import node_service

logger = logging.getLogger(__name__)

nodes_router = APIRouter(prefix="/nodes", tags=["Federated Nodes"])


# ── POST /nodes/register ──────────────────────────────────────────────────────

@nodes_router.post(
    "/register",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a peer AgentX node",
)
async def register_node(body: RegisterNodeRequest) -> NodeResponse:
    """Register (or update) a peer node by URL.

    If the URL is already known the record is updated with the supplied
    name / public_key and last_seen_at is refreshed.  This endpoint is
    intentionally unauthenticated so peer nodes can self-register.
    """
    try:
        return await node_service.register_node(
            node_url=body.node_url,
            node_name=body.node_name,
            public_key=body.public_key,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


# ── GET /nodes ────────────────────────────────────────────────────────────────

@nodes_router.get(
    "",
    response_model=List[NodeResponse],
    summary="List known peer nodes",
)
async def list_nodes(
    active_only: bool = Query(
        default=False,
        description="When true, return only nodes with status='active'",
    ),
) -> List[NodeResponse]:
    """Return all registered peer nodes ordered by registration time."""
    return await node_service.list_nodes(active_only=active_only)


# ── POST /nodes/events ────────────────────────────────────────────────────────

@nodes_router.post(
    "/events",
    response_model=NodeMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a federated event from a peer node",
)
async def receive_event(body: FederatedEventRequest) -> NodeMessageResponse:
    """Accept an inbound federated event from a peer node.

    The event is logged to node_messages with direction='inbound'.
    If source_node_url is provided and matches a registered node,
    the message is linked to that node record.
    """
    # Resolve source node_id from URL (best-effort; None if unknown)
    node_id: UUID | None = None
    if body.source_node_url:
        try:
            all_nodes = await node_service.list_nodes()
            for n in all_nodes:
                if n.node_url == body.source_node_url:
                    node_id = n.node_id
                    break
        except Exception:
            pass  # unknown peer — still accept the event

    try:
        return await node_service.send_node_message(
            node_id=node_id,
            event_type=body.event_type,
            payload=body.payload,
            direction="inbound",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
