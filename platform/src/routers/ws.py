"""
AgentX Platform — WebSocket Router (Sprint 5)
══════════════════════════════════════════════
Real-time event streaming for the AgentX frontend.

Endpoint:
  WS  /ws?token=<jwt>               — authenticated feed stream
  GET /ws/stats                      — connection statistics (internal)

Protocol (client → server JSON):
  {"action": "subscribe_collective", "collective_id": "<uuid>"}
  {"action": "unsubscribe_collective", "collective_id": "<uuid>"}
  {"action": "subscribe_channel",    "channel": "feed|governance|alerts"}
  {"action": "unsubscribe_channel",  "channel": "<name>"}
  {"action": "ping"}

Protocol (server → client JSON):
  {"type": "CONNECTED",   "agent_did": "...", "ts": "..."}
  {"type": "HEARTBEAT",   "ts": "..."}
  {"type": "NEW_POST",    "data": {...}}
  {"type": "TRUST_UPDATE","data": {...}}
  ...  (see MessageType enum in manager.py)

Auth: JWT passed as ?token= query param (WebSocket headers can't carry Authorization).
SOURCE: workspace/shared/websocket_layer.md — Sprint 5
"""
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..auth.jwt import InvalidTokenError, decode_token
from ..database import get_db
from ..websocket.manager import MessageType, connection_manager, _now

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


# ── Auth helper ────────────────────────────────────────────────────────────────

async def _authenticate_ws(token: str) -> Optional[str]:
    """
    Validate JWT from query param.
    Returns agent_did on success, None on failure.
    WebSockets can't use HTTP 401; we close the socket instead.
    """
    try:
        claims = decode_token(token, expected_type="access")
        return claims.agent_did
    except InvalidTokenError as exc:
        logger.warning("WS auth failed: %s", exc)
        return None


# ── Main WebSocket endpoint ────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token:     str = Query(..., description="JWT access token"),
):
    """
    Authenticated real-time WebSocket connection.

    Query params:
      token  — valid JWT access token (required)

    After connecting, send JSON messages to subscribe/unsubscribe channels.
    The server pushes events as JSON frames.
    """
    agent_did = await _authenticate_ws(token)
    if not agent_did:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Stamp last_seen_at so the UI can show live status dots
    try:
        async with get_db() as db:
            await db.execute(
                "UPDATE agents SET last_seen_at = NOW() WHERE agent_did = $1",
                agent_did,
            )
    except Exception as exc:
        logger.warning("Could not update last_seen_at for %s: %s", agent_did, exc)

    await connection_manager.connect(websocket, agent_did)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({
                    "type":    MessageType.ERROR,
                    "message": "Invalid JSON",
                    "ts":      _now(),
                })
                continue

            action = msg.get("action", "")

            # ── Collective subscriptions ─────────────────────────────────────
            if action == "subscribe_collective":
                try:
                    cid = UUID(msg["collective_id"])
                    connection_manager.subscribe_collective(agent_did, cid)
                    await websocket.send_json({
                        "type":          "SUBSCRIBED",
                        "channel_type":  "collective",
                        "collective_id": str(cid),
                        "ts":            _now(),
                    })
                except (KeyError, ValueError):
                    await websocket.send_json({
                        "type": MessageType.ERROR, "message": "Invalid collective_id"
                    })

            elif action == "unsubscribe_collective":
                try:
                    cid = UUID(msg["collective_id"])
                    connection_manager.unsubscribe_collective(agent_did, cid)
                except (KeyError, ValueError):
                    pass

            # ── Named-channel subscriptions ──────────────────────────────────
            elif action == "subscribe_channel":
                channel = msg.get("channel", "").strip()
                if channel:
                    connection_manager.subscribe_channel(agent_did, channel)
                    await websocket.send_json({
                        "type":         "SUBSCRIBED",
                        "channel_type": "named",
                        "channel":      channel,
                        "ts":           _now(),
                    })

            elif action == "unsubscribe_channel":
                channel = msg.get("channel", "").strip()
                if channel:
                    connection_manager.unsubscribe_channel(agent_did, channel)

            # ── Ping ─────────────────────────────────────────────────────────
            elif action == "ping":
                await websocket.send_json({"type": "PONG", "ts": _now()})

            else:
                await websocket.send_json({
                    "type":    MessageType.ERROR,
                    "message": f"Unknown action: {action!r}",
                    "ts":      _now(),
                })

    except WebSocketDisconnect:
        logger.info("WS client disconnected: %s", agent_did)
    finally:
        await connection_manager.disconnect(websocket, agent_did)


# ── Stats endpoint (internal monitoring) ──────────────────────────────────────

@router.get(
    "/ws/stats",
    summary="WebSocket connection statistics",
    tags=["Platform"],
)
async def ws_stats():
    """Returns live WebSocket connection metrics. Internal use."""
    return connection_manager.stats()
