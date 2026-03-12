import logging
import json
from datetime import timezone
from typing import Any

from fastapi import WebSocket

from ..database import transaction

logger = logging.getLogger(__name__)

_connections: set[WebSocket] = set()


async def register_connection(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.add(websocket)


async def unregister_connection(websocket: WebSocket) -> None:
    _connections.discard(websocket)


async def _broadcast(event: dict[str, Any]) -> None:
    stale: list[WebSocket] = []
    for websocket in list(_connections):
        try:
            await websocket.send_json(event)
        except Exception as exc:
            logger.warning("Event websocket send failed: %s", exc)
            stale.append(websocket)

    for websocket in stale:
        _connections.discard(websocket)


async def emit_event(
    event_type: str,
    agent_did: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events (
                event_id,
                event_type,
                agent_did,
                payload,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3::jsonb,
                CURRENT_TIMESTAMP
            )
            RETURNING event_id, event_type, agent_did, payload, created_at
            """,
            event_type,
            agent_did,
            json.dumps(payload or {}),
        )

    timestamp = row["created_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    payload_value = row["payload"] or {}
    if isinstance(payload_value, str):
        payload_value = json.loads(payload_value)
    event = {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "agent_did": row["agent_did"],
        "timestamp": timestamp,
        "payload": payload_value,
    }
    await _broadcast(event)
    return event
