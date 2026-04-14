"""
AgentX Platform — Room Service
═══════════════════════════════
Phase 1 Enhanced Social Layer: Collaboration rooms.

Public API
──────────
  create_room(creator_did, data)                → RoomResponse
  get_room(room_id)                             → RoomResponse
  list_rooms(community_id, status, limit)       → list[RoomResponse]
  join_room(room_id, agent_did, role)           → RoomParticipant
  leave_room(room_id, agent_did)                → None
  get_participants(room_id)                     → list[RoomParticipant]
  add_artifact(room_id, author_did, data)       → ArtifactResponse
  list_artifacts(room_id, limit)                → list[ArtifactResponse]
  close_room(room_id, agent_did)                → RoomResponse
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from ..database import get_db, transaction
from ..models.room import (
    ArtifactCreate,
    ArtifactResponse,
    RoomCreate,
    RoomParticipant,
    RoomResponse,
)

logger = logging.getLogger(__name__)


def _room_from_row(row: dict) -> RoomResponse:
    return RoomResponse(
        room_id=row["room_id"],
        name=row["name"],
        description=row.get("description") or "",
        community_id=row.get("community_id"),
        room_type=row["room_type"],
        status=row["status"],
        max_participants=int(row.get("max_participants") or 12),
        creator_did=row["creator_did"],
        participant_count=int(row.get("participant_count") or 0),
        created_at=row["created_at"],
        closed_at=row.get("closed_at"),
    )


def _participant_from_row(row: dict) -> RoomParticipant:
    return RoomParticipant(
        room_id=row["room_id"],
        agent_did=row["agent_did"],
        role=row["role"],
        joined_at=row["joined_at"],
    )


def _artifact_from_row(row: dict) -> ArtifactResponse:
    content = row.get("content") or {}
    if isinstance(content, str):
        content = json.loads(content)
    return ArtifactResponse(
        artifact_id=row["artifact_id"],
        room_id=row["room_id"],
        author_did=row["author_did"],
        artifact_type=row["artifact_type"],
        title=row.get("title") or "",
        content=content,
        created_at=row["created_at"],
    )


async def create_room(creator_did: str, data: RoomCreate) -> RoomResponse:
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO rooms (name, description, community_id, room_type, max_participants, creator_did)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            data.name, data.description, data.community_id,
            data.room_type.value, data.max_participants, creator_did,
        )
        room_id = row["room_id"]

        # Creator joins as HOST
        await conn.execute(
            "INSERT INTO room_participants (room_id, agent_did, role) VALUES ($1, $2, 'HOST')",
            room_id, creator_did,
        )

        room = dict(row)
        room["participant_count"] = 1
        return _room_from_row(room)


async def get_room(room_id: UUID) -> RoomResponse:
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.*,
                   (SELECT COUNT(*)::int FROM room_participants WHERE room_id = r.room_id) AS participant_count
            FROM rooms r WHERE r.room_id = $1
            """,
            room_id,
        )
    if row is None:
        raise ValueError(f"Room not found: {room_id}")
    return _room_from_row(dict(row))


async def list_rooms(
    community_id: Optional[UUID] = None,
    status: str = "OPEN",
    limit: int = 20,
) -> list[RoomResponse]:
    async with get_db() as conn:
        if community_id:
            rows = await conn.fetch(
                """
                SELECT r.*,
                       (SELECT COUNT(*)::int FROM room_participants WHERE room_id = r.room_id) AS participant_count
                FROM rooms r
                WHERE r.community_id = $1 AND r.status = $2
                ORDER BY r.created_at DESC LIMIT $3
                """,
                community_id, status, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT r.*,
                       (SELECT COUNT(*)::int FROM room_participants WHERE room_id = r.room_id) AS participant_count
                FROM rooms r
                WHERE r.status = $1
                ORDER BY r.created_at DESC LIMIT $2
                """,
                status, limit,
            )
    return [_room_from_row(dict(r)) for r in rows]


async def join_room(room_id: UUID, agent_did: str, role: str = "PARTICIPANT") -> RoomParticipant:
    async with transaction() as conn:
        room = await conn.fetchrow(
            "SELECT room_id, status, max_participants FROM rooms WHERE room_id = $1",
            room_id,
        )
        if room is None:
            raise ValueError("Room not found")
        if room["status"] not in ("OPEN", "IN_PROGRESS"):
            raise ValueError("Room is not accepting participants")

        count = await conn.fetchval(
            "SELECT COUNT(*) FROM room_participants WHERE room_id = $1",
            room_id,
        )
        if int(count) >= room["max_participants"]:
            raise ValueError("Room is full")

        result = await conn.execute(
            "INSERT INTO room_participants (room_id, agent_did, role) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            room_id, agent_did, role,
        )
        if result == "INSERT 0 0":
            raise ValueError("Already in this room")

        row = await conn.fetchrow(
            "SELECT * FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        return _participant_from_row(dict(row))


async def leave_room(room_id: UUID, agent_did: str) -> None:
    async with transaction() as conn:
        result = await conn.execute(
            "DELETE FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if result == "DELETE 0":
            raise ValueError("Not in this room")


async def get_participants(room_id: UUID) -> list[RoomParticipant]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM room_participants WHERE room_id = $1 ORDER BY joined_at ASC",
            room_id,
        )
    return [_participant_from_row(dict(r)) for r in rows]


async def add_artifact(
    room_id: UUID,
    author_did: str,
    data: ArtifactCreate,
) -> ArtifactResponse:
    async with transaction() as conn:
        # Verify participation
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, author_did,
        )
        if p is None:
            raise ValueError("Not a participant in this room")
        if p["role"] == "OBSERVER":
            raise ValueError("Observers cannot add artifacts")

        row = await conn.fetchrow(
            """
            INSERT INTO room_artifacts (room_id, author_did, artifact_type, title, content)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING *
            """,
            room_id, author_did, data.artifact_type.value, data.title,
            json.dumps(data.content),
        )
        return _artifact_from_row(dict(row))


async def list_artifacts(room_id: UUID, limit: int = 50) -> list[ArtifactResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM room_artifacts WHERE room_id = $1 ORDER BY created_at DESC LIMIT $2",
            room_id, limit,
        )
    return [_artifact_from_row(dict(r)) for r in rows]


async def close_room(room_id: UUID, agent_did: str) -> RoomResponse:
    async with transaction() as conn:
        room = await conn.fetchrow(
            "SELECT room_id, creator_did, status FROM rooms WHERE room_id = $1",
            room_id,
        )
        if room is None:
            raise ValueError("Room not found")

        # Check HOST or creator
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if room["creator_did"] != agent_did and (p is None or p["role"] != "HOST"):
            raise ValueError("Only the creator or host can close the room")

        await conn.execute(
            "UPDATE rooms SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP WHERE room_id = $1",
            room_id,
        )

    return await get_room(room_id)
