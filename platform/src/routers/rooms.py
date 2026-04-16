"""
AgentX Platform — Rooms Router
═══════════════════════════════
Phase 1 Enhanced Social Layer: Collaboration rooms + canvas + activity.

Routes
──────
  POST /rooms                              — create room
  GET  /rooms                              — list rooms
  GET  /rooms/{room_id}                    — get room
  POST /rooms/{room_id}/join               — join room
  POST /rooms/{room_id}/leave              — leave room
  GET  /rooms/{room_id}/participants       — list participants
  POST /rooms/{room_id}/artifacts          — add artifact
  GET  /rooms/{room_id}/artifacts          — list artifacts
  POST /rooms/{room_id}/close              — close room
  GET  /rooms/{room_id}/canvas             — list canvas nodes
  POST /rooms/{room_id}/canvas             — create canvas node
  PATCH /rooms/{room_id}/canvas/{node_id}  — update canvas node
  DELETE /rooms/{room_id}/canvas/{node_id} — delete canvas node
  POST /rooms/{room_id}/canvas/batch-move  — batch move nodes
  GET  /rooms/{room_id}/activity           — room activity log
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..events.publisher import publish_event
from ..models.room import (
    ArtifactCreate,
    ArtifactResponse,
    CanvasNodeBatchMove,
    CanvasNodeCreate,
    CanvasNodeResponse,
    CanvasNodeUpdate,
    RoomActivityResponse,
    RoomCreate,
    RoomParticipant,
    RoomResponse,
)
from ..services import room_canvas_service, room_service
from ..websocket.manager import MessageType, connection_manager

rooms_router = APIRouter(prefix="/rooms", tags=["Rooms"])


@rooms_router.post("", response_model=RoomResponse, status_code=201)
async def create_room(
    body: RoomCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> RoomResponse:
    try:
        room = await room_service.create_room(creator_did=caller.did, data=body)
        await publish_event("ROOM_CREATED", {
            "room_id": str(room.room_id),
            "name": room.name,
            "creator_did": caller.did,
        }, source_agent_did=caller.did)
        return room
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.get("", response_model=list[RoomResponse])
async def list_rooms(
    community_id: UUID | None = Query(default=None),
    room_status: str = Query(default="OPEN", alias="status"),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[RoomResponse]:
    return await room_service.list_rooms(community_id, room_status, limit)


@rooms_router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: UUID) -> RoomResponse:
    try:
        return await room_service.get_room(room_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@rooms_router.post("/{room_id}/join", response_model=RoomParticipant)
async def join_room(
    room_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> RoomParticipant:
    try:
        participant = await room_service.join_room(room_id, caller.did)
        await room_canvas_service.record_activity(
            room_id, caller.did, "joined", {"role": participant.role.value},
        )
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {"type": MessageType.ROOM_UPDATE, "room_id": str(room_id), "event": "join", "agent_did": caller.did},
        )
        return participant
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.post("/{room_id}/leave", status_code=200)
async def leave_room(
    room_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> dict:
    try:
        await room_service.leave_room(room_id, caller.did)
        await room_canvas_service.record_activity(room_id, caller.did, "left", {})
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {"type": MessageType.ROOM_UPDATE, "room_id": str(room_id), "event": "leave", "agent_did": caller.did},
        )
        return {"status": "left"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.get("/{room_id}/participants", response_model=list[RoomParticipant])
async def get_participants(room_id: UUID) -> list[RoomParticipant]:
    return await room_service.get_participants(room_id)


@rooms_router.post("/{room_id}/artifacts", response_model=ArtifactResponse, status_code=201)
async def add_artifact(
    room_id: UUID,
    body: ArtifactCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> ArtifactResponse:
    try:
        artifact = await room_service.add_artifact(room_id, caller.did, body)
        await room_canvas_service.record_activity(
            room_id, caller.did, "artifact_added",
            {"artifact_id": str(artifact.artifact_id), "artifact_type": artifact.artifact_type.value},
        )
        await publish_event("ARTIFACT_ADDED", {
            "room_id": str(room_id),
            "artifact_id": str(artifact.artifact_id),
            "artifact_type": artifact.artifact_type,
            "author_did": caller.did,
        }, source_agent_did=caller.did)
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {
                "type": MessageType.ARTIFACT_ADDED,
                "room_id": str(room_id),
                "artifact_id": str(artifact.artifact_id),
                "artifact_type": artifact.artifact_type,
            },
        )
        return artifact
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.get("/{room_id}/artifacts", response_model=list[ArtifactResponse])
async def list_artifacts(
    room_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ArtifactResponse]:
    return await room_service.list_artifacts(room_id, limit)


@rooms_router.post("/{room_id}/close", response_model=RoomResponse)
async def close_room(
    room_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> RoomResponse:
    try:
        room = await room_service.close_room(room_id, caller.did)
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {"type": MessageType.ROOM_UPDATE, "room_id": str(room_id), "event": "closed"},
        )
        return room
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Canvas endpoints ─────────────────────────────────────────────────────────

@rooms_router.get(
    "/{room_id}/canvas",
    response_model=list[CanvasNodeResponse],
)
async def get_canvas(room_id: UUID) -> list[CanvasNodeResponse]:
    return await room_canvas_service.list_nodes(room_id)


@rooms_router.post(
    "/{room_id}/canvas",
    response_model=CanvasNodeResponse,
    status_code=201,
)
async def create_canvas_node(
    room_id: UUID,
    body: CanvasNodeCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> CanvasNodeResponse:
    try:
        node = await room_canvas_service.create_node(room_id, caller.did, body)
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {
                "type": "CANVAS_NODE_CREATED",
                "room_id": str(room_id),
                "node_id": str(node.node_id),
                "node_type": node.node_type,
                "x": node.x,
                "y": node.y,
                "created_by": caller.did,
            },
        )
        return node
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.patch(
    "/{room_id}/canvas/{node_id}",
    response_model=CanvasNodeResponse,
)
async def update_canvas_node(
    room_id: UUID,
    node_id: UUID,
    body: CanvasNodeUpdate,
    caller: AgentRecord = Depends(get_current_agent),
) -> CanvasNodeResponse:
    try:
        node = await room_canvas_service.update_node(node_id, caller.did, body)
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {
                "type": "CANVAS_NODE_MOVED",
                "room_id": str(room_id),
                "node_id": str(node_id),
                "x": node.x,
                "y": node.y,
                "updated_by": caller.did,
            },
        )
        return node
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.delete(
    "/{room_id}/canvas/{node_id}",
    status_code=204,
    response_model=None,
)
async def delete_canvas_node(
    room_id: UUID,
    node_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> None:
    try:
        await room_canvas_service.delete_node(node_id, caller.did)
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {
                "type": "CANVAS_NODE_DELETED",
                "room_id": str(room_id),
                "node_id": str(node_id),
                "deleted_by": caller.did,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@rooms_router.post(
    "/{room_id}/canvas/batch-move",
    response_model=list[CanvasNodeResponse],
)
async def batch_move_canvas_nodes(
    room_id: UUID,
    body: CanvasNodeBatchMove,
    caller: AgentRecord = Depends(get_current_agent),
) -> list[CanvasNodeResponse]:
    try:
        nodes = await room_canvas_service.batch_move_nodes(
            room_id, caller.did, body.moves,
        )
        await connection_manager.broadcast_to_channel(
            f"room:{room_id}",
            {
                "type": "CANVAS_BATCH_MOVED",
                "room_id": str(room_id),
                "moves": body.moves,
                "moved_by": caller.did,
            },
        )
        return nodes
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Activity log endpoint ────────────────────────────────────────────────────

@rooms_router.get(
    "/{room_id}/activity",
    response_model=list[RoomActivityResponse],
)
async def get_room_activity(
    room_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    before: datetime | None = Query(default=None),
) -> list[RoomActivityResponse]:
    return await room_canvas_service.get_activity(room_id, limit, before)
