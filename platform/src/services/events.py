import logging
import json
from datetime import timezone
from typing import Any

from fastapi import WebSocket

from ..database import transaction

logger = logging.getLogger(__name__)

_connections: set[WebSocket] = set()

# Event types that never go to the public readers of the events table
# (WS /events/stream, GET /dashboard/activity): neither takes a login.
# S9-6d: a direct message, with its text, used to be readable on both.
PRIVATE_EVENT_TYPES = frozenset({"MESSAGE_SENT"})

# S9-8c: SQL condition for the same two readers. An event about a post
# (POST_CREATED carries its title and text) is skipped while that post is
# hidden. Only hidden posts are looked at (partial index idx_posts_hidden).
EVENT_NOT_ABOUT_HIDDEN_POST = """
    NOT EXISTS (
        SELECT 1 FROM posts hp
        WHERE hp.hidden_at IS NOT NULL
          AND hp.post_id::text = events.payload->>'post_id'
    )
"""


# S9-6e: WS /events/stream takes no login (the UI's public activity feed uses
# it) and each open socket runs one database query per second, so the number
# of sockets is capped per process. Over the cap the socket is refused with
# 1013 ("try again later") before it is accepted.
MAX_STREAM_CONNECTIONS = 200


async def register_connection(websocket: WebSocket) -> bool:
    if len(_connections) >= MAX_STREAM_CONNECTIONS:
        await websocket.close(code=1013)
        return False
    await websocket.accept()
    _connections.add(websocket)
    return True


async def unregister_connection(websocket: WebSocket) -> None:
    _connections.discard(websocket)


async def _broadcast(event: dict[str, Any]) -> None:
    if event["event_type"] in PRIVATE_EVENT_TYPES:
        return

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
