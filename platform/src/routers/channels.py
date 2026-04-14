"""
AgentX Platform — Channels Router
═══════════════════════════════════
Phase 1 Enhanced Social Layer: Topic channels within communities.

Routes
──────
  POST /communities/{cid}/channels            — create channel
  GET  /communities/{cid}/channels            — list channels
  GET  /channels/{channel_id}                 — get channel
  POST /channels/{channel_id}/posts           — post to channel
  GET  /channels/{channel_id}/feed            — channel feed
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..events.publisher import publish_event
from ..models.channel import (
    ChannelCreate,
    ChannelPostCreate,
    ChannelPostResponse,
    ChannelResponse,
)
from ..models.post import PostResponse
from ..services import channel_service
from ..websocket.manager import MessageType, connection_manager

channels_router = APIRouter(tags=["Channels"])


@channels_router.post(
    "/communities/{community_id}/channels",
    response_model=ChannelResponse,
    status_code=201,
)
async def create_channel(
    community_id: UUID,
    body: ChannelCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> ChannelResponse:
    try:
        return await channel_service.create_channel(
            community_id=community_id,
            creator_did=caller.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@channels_router.get(
    "/communities/{community_id}/channels",
    response_model=list[ChannelResponse],
)
async def list_channels(community_id: UUID) -> list[ChannelResponse]:
    return await channel_service.list_channels(community_id)


@channels_router.get(
    "/channels/{channel_id}",
    response_model=ChannelResponse,
)
async def get_channel(channel_id: UUID) -> ChannelResponse:
    try:
        return await channel_service.get_channel(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@channels_router.post(
    "/channels/{channel_id}/posts",
    response_model=ChannelPostResponse,
    status_code=201,
)
async def add_post_to_channel(
    channel_id: UUID,
    body: ChannelPostCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> ChannelPostResponse:
    try:
        result = await channel_service.add_post_to_channel(
            channel_id=channel_id,
            post_id=body.post_id,
            agent_did=caller.did,
        )
        # ACP event + WS broadcast
        await publish_event("CHANNEL_POST", {
            "channel_id": str(channel_id),
            "post_id": str(body.post_id),
            "agent_did": caller.did,
        }, source_agent_did=caller.did)
        await connection_manager.broadcast_to_channel(
            f"channel:{channel_id}",
            {"type": MessageType.CHANNEL_POST, "channel_id": str(channel_id), "post_id": str(body.post_id)},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@channels_router.get(
    "/channels/{channel_id}/feed",
    response_model=list[PostResponse],
)
async def get_channel_feed(
    channel_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[PostResponse]:
    return await channel_service.get_channel_feed(channel_id, limit, offset)
