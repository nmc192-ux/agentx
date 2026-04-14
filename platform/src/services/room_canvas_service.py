"""
AgentX Platform — Room Canvas Service
═════════════════════════════════════
Phase 1 Collaboration Rooms: Canvas node management + activity log.

Public API
──────────
  Canvas nodes:
    create_node(room_id, agent_did, data)          → CanvasNodeResponse
    list_nodes(room_id)                            → list[CanvasNodeResponse]
    update_node(node_id, agent_did, patch)         → CanvasNodeResponse
    batch_move_nodes(room_id, agent_did, moves)    → list[CanvasNodeResponse]
    delete_node(node_id, agent_did)                → None

  Activity log:
    record_activity(room_id, agent_did, action, detail)  → RoomActivityResponse
    get_activity(room_id, limit, before)                 → list[RoomActivityResponse]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from ..database import get_db, transaction
from ..models.room import (
    CanvasNodeCreate,
    CanvasNodeResponse,
    CanvasNodeUpdate,
    RoomActivityResponse,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _node_from_row(row: dict) -> CanvasNodeResponse:
    style = row.get("style") or {}
    if isinstance(style, str):
        style = json.loads(style)
    return CanvasNodeResponse(
        node_id=row["node_id"],
        room_id=row["room_id"],
        artifact_id=row.get("artifact_id"),
        node_type=row["node_type"],
        label=row.get("label") or "",
        x=float(row["x"]),
        y=float(row["y"]),
        width=float(row.get("width") or 180),
        height=float(row.get("height") or 80),
        style=style,
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _activity_from_row(row: dict) -> RoomActivityResponse:
    detail = row.get("detail") or {}
    if isinstance(detail, str):
        detail = json.loads(detail)
    return RoomActivityResponse(
        activity_id=row["activity_id"],
        room_id=row["room_id"],
        agent_did=row["agent_did"],
        action=row["action"],
        detail=detail,
        created_at=row["created_at"],
    )


# ── Canvas CRUD ──────────────────────────────────────────────────────────────

async def create_node(
    room_id: UUID,
    agent_did: str,
    data: CanvasNodeCreate,
) -> CanvasNodeResponse:
    """Place a new node on the room canvas."""
    async with transaction() as conn:
        # Verify room exists and is active
        room = await conn.fetchrow(
            "SELECT room_id, status FROM rooms WHERE room_id = $1",
            room_id,
        )
        if room is None:
            raise ValueError("Room not found")
        if room["status"] in ("CLOSED", "ARCHIVED"):
            raise ValueError("Room is closed")

        # Verify participant
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if p is None:
            raise ValueError("Not a participant in this room")
        if p["role"] == "OBSERVER":
            raise ValueError("Observers cannot modify the canvas")

        row = await conn.fetchrow(
            """
            INSERT INTO canvas_nodes
                (room_id, artifact_id, node_type, label, x, y, width, height, style, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            RETURNING *
            """,
            room_id, data.artifact_id, data.node_type.value,
            data.label, data.x, data.y, data.width, data.height,
            json.dumps(data.style), agent_did,
        )

        # Record activity
        await conn.execute(
            """
            INSERT INTO room_activity (room_id, agent_did, action, detail)
            VALUES ($1, $2, 'node_created', $3::jsonb)
            """,
            room_id, agent_did,
            json.dumps({"node_id": str(row["node_id"]), "node_type": data.node_type.value}),
        )

        return _node_from_row(dict(row))


async def list_nodes(room_id: UUID) -> list[CanvasNodeResponse]:
    """Get all canvas nodes for a room."""
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM canvas_nodes WHERE room_id = $1 ORDER BY created_at ASC",
            room_id,
        )
    return [_node_from_row(dict(r)) for r in rows]


async def update_node(
    node_id: UUID,
    agent_did: str,
    patch: CanvasNodeUpdate,
) -> CanvasNodeResponse:
    """Update a canvas node position, size, or label."""
    async with transaction() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM canvas_nodes WHERE node_id = $1",
            node_id,
        )
        if existing is None:
            raise ValueError("Canvas node not found")

        room_id = existing["room_id"]

        # Verify participant
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if p is None:
            raise ValueError("Not a participant in this room")
        if p["role"] == "OBSERVER":
            raise ValueError("Observers cannot modify the canvas")

        # Build SET clause dynamically
        sets: list[str] = ["updated_at = now()"]
        params: list[Any] = []
        idx = 1

        for field in ("x", "y", "width", "height", "label"):
            val = getattr(patch, field)
            if val is not None:
                sets.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1

        if patch.style is not None:
            sets.append(f"style = ${idx}::jsonb")
            params.append(json.dumps(patch.style))
            idx += 1

        params.append(node_id)
        sql = f"UPDATE canvas_nodes SET {', '.join(sets)} WHERE node_id = ${idx} RETURNING *"

        row = await conn.fetchrow(sql, *params)
        return _node_from_row(dict(row))


async def batch_move_nodes(
    room_id: UUID,
    agent_did: str,
    moves: list[dict[str, Any]],
) -> list[CanvasNodeResponse]:
    """Batch-move multiple nodes. Each move: {node_id, x, y}."""
    results: list[CanvasNodeResponse] = []

    async with transaction() as conn:
        # Verify participant once
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if p is None:
            raise ValueError("Not a participant in this room")
        if p["role"] == "OBSERVER":
            raise ValueError("Observers cannot modify the canvas")

        for move in moves:
            nid = move.get("node_id")
            x = move.get("x")
            y = move.get("y")
            if nid is None or x is None or y is None:
                continue

            row = await conn.fetchrow(
                """
                UPDATE canvas_nodes SET x = $1, y = $2, updated_at = now()
                WHERE node_id = $3 AND room_id = $4
                RETURNING *
                """,
                float(x), float(y), UUID(str(nid)), room_id,
            )
            if row:
                results.append(_node_from_row(dict(row)))

    return results


async def delete_node(
    node_id: UUID,
    agent_did: str,
) -> None:
    """Remove a node from the canvas."""
    async with transaction() as conn:
        existing = await conn.fetchrow(
            "SELECT room_id, node_type FROM canvas_nodes WHERE node_id = $1",
            node_id,
        )
        if existing is None:
            raise ValueError("Canvas node not found")

        room_id = existing["room_id"]

        # Verify participant
        p = await conn.fetchrow(
            "SELECT role FROM room_participants WHERE room_id = $1 AND agent_did = $2",
            room_id, agent_did,
        )
        if p is None:
            raise ValueError("Not a participant in this room")
        if p["role"] == "OBSERVER":
            raise ValueError("Observers cannot modify the canvas")

        await conn.execute(
            "DELETE FROM canvas_nodes WHERE node_id = $1", node_id,
        )

        await conn.execute(
            """
            INSERT INTO room_activity (room_id, agent_did, action, detail)
            VALUES ($1, $2, 'node_deleted', $3::jsonb)
            """,
            room_id, agent_did,
            json.dumps({"node_id": str(node_id), "node_type": existing["node_type"]}),
        )


# ── Activity log ─────────────────────────────────────────────────────────────

async def record_activity(
    room_id: UUID,
    agent_did: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> RoomActivityResponse:
    """Write a single activity entry."""
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO room_activity (room_id, agent_did, action, detail)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING *
            """,
            room_id, agent_did, action, json.dumps(detail or {}),
        )
        return _activity_from_row(dict(row))


async def get_activity(
    room_id: UUID,
    limit: int = 50,
    before: datetime | None = None,
) -> list[RoomActivityResponse]:
    """Paginated activity feed for a room (newest first)."""
    async with get_db() as conn:
        if before:
            rows = await conn.fetch(
                """
                SELECT * FROM room_activity
                WHERE room_id = $1 AND created_at < $2
                ORDER BY created_at DESC LIMIT $3
                """,
                room_id, before, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM room_activity
                WHERE room_id = $1
                ORDER BY created_at DESC LIMIT $2
                """,
                room_id, limit,
            )
    return [_activity_from_row(dict(r)) for r in rows]
