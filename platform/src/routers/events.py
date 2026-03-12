import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import get_db
from ..services.events import register_connection, unregister_connection

router = APIRouter(prefix="/events", tags=["Events"])


@router.websocket("/stream")
async def stream_events(websocket: WebSocket):
    await register_connection(websocket)
    last_seen = datetime.now(timezone.utc)
    try:
        while True:
            async with get_db() as conn:
                rows = await conn.fetch(
                    """
                    SELECT event_id, event_type, agent_did, payload, created_at
                    FROM events
                    WHERE created_at > $1
                    ORDER BY created_at ASC
                    LIMIT 50
                    """,
                    last_seen,
                )

            for row in rows:
                payload = row["payload"] or {}
                if isinstance(payload, str):
                    payload = json.loads(payload)
                await websocket.send_json(
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "agent_did": row["agent_did"],
                        "timestamp": row["created_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "payload": payload,
                    }
                )
                last_seen = max(last_seen, row["created_at"])

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        await unregister_connection(websocket)
