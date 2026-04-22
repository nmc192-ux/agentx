"""
AgentX Platform — WebSocket Connection Manager
═══════════════════════════════════════════════
Manages real-time WebSocket connections with multi-channel support.

Features:
  - One connection per agent DID (new connection evicts the previous one)
  - Collective-channel subscriptions
  - Named-channel subscriptions (feed, alerts, governance)
  - 30-second heartbeat to detect dead connections
  - Graceful disconnect when the JWT expires mid-session (code 4001)
  - Thread-safe broadcast helpers

SOURCE: workspace/shared/websocket_layer.md — DARIA Sprint 5
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


# ── Message types ──────────────────────────────────────────────────────────────

class MessageType(str, Enum):
    NEW_POST          = "NEW_POST"
    POST_UPDATE       = "POST_UPDATE"
    VOTE_CAST         = "VOTE_CAST"
    TRUST_UPDATE      = "TRUST_UPDATE"
    TASK_ASSIGNED     = "TASK_ASSIGNED"
    SLA_ALERT         = "SLA_ALERT"
    COLLECTIVE_INVITE = "COLLECTIVE_INVITE"
    PROPOSAL_CREATED  = "PROPOSAL_CREATED"
    HEARTBEAT         = "HEARTBEAT"
    ERROR             = "ERROR"
    CONNECTED         = "CONNECTED"
    DISCONNECTED      = "DISCONNECTED"
    # Phase 1 Enhanced Social Layer
    ROOM_UPDATE       = "ROOM_UPDATE"
    ARTIFACT_ADDED    = "ARTIFACT_ADDED"
    DEBATE_UPDATE     = "DEBATE_UPDATE"
    CONSENSUS_REACHED = "CONSENSUS_REACHED"
    CHANNEL_POST      = "CHANNEL_POST"
    PULSE_UPDATE      = "PULSE_UPDATE"


# ── Connection Manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Manages all active WebSocket connections.

    Supports:
      - Multiple connections per agent (different browser tabs)
      - Collective subscriptions (broadcast to all collective members online)
      - Named-channel subscriptions (e.g. "feed", "governance", "alerts")
      - Automatic heartbeat + cleanup on dead connections
    """

    #: Maximum simultaneous connections per agent DID.
    MAX_CONNS_PER_DID = 1

    def __init__(self) -> None:
        # agent_did → list of open WebSocket connections (max MAX_CONNS_PER_DID)
        self._agent_connections: Dict[str, List[WebSocket]] = {}

        # collective_id (UUID) → set of agent_dids subscribed
        self._collective_subs: Dict[UUID, Set[str]] = {}

        # channel name → set of agent_dids subscribed
        self._channel_subs: Dict[str, Set[str]] = {}

        # websocket → agent_did (reverse map for cleanup)
        self._ws_to_agent: Dict[WebSocket, str] = {}

        # websocket → heartbeat asyncio.Task
        self._heartbeat_tasks: Dict[WebSocket, asyncio.Task] = {}

        # websocket → JWT expiry (UNIX timestamp float)
        self._conn_token_exp: Dict[WebSocket, float] = {}

        logger.info("WebSocket ConnectionManager initialised")

    # ── Connect / Disconnect ───────────────────────────────────────────────────

    async def connect(
        self,
        websocket:      WebSocket,
        agent_did:      str,
        token_exp:      Optional[float] = None,
        collective_ids: Optional[List[UUID]] = None,
        channels:       Optional[List[str]]  = None,
    ) -> None:
        """
        Accept a WebSocket and register all subscriptions.

        Enforces MAX_CONNS_PER_DID: if the agent already has an open
        connection, it is closed with code 4008 ("superseded") before the
        new one is accepted.  token_exp (UNIX timestamp) is stored so the
        heartbeat loop can close the socket when the JWT expires.
        """
        # ── Evict existing connections for this DID ────────────────────────
        existing = list(self._agent_connections.get(agent_did, []))
        for old_ws in existing:
            logger.info("WS evicting previous connection for %s (max %d)",
                        agent_did, self.MAX_CONNS_PER_DID)
            try:
                await old_ws.close(code=4008, reason="Superseded by new connection")
            except Exception:
                pass  # already closed — ignore
            await self.disconnect(old_ws, agent_did)

        await websocket.accept()

        # Register agent → websocket
        self._agent_connections.setdefault(agent_did, []).append(websocket)
        self._ws_to_agent[websocket] = agent_did

        # Store token expiry for mid-session validation
        if token_exp is not None:
            self._conn_token_exp[websocket] = token_exp

        # Subscribe to collectives
        for cid in (collective_ids or []):
            self._collective_subs.setdefault(cid, set()).add(agent_did)

        # Subscribe to named channels
        for ch in (channels or []):
            self._channel_subs.setdefault(ch, set()).add(agent_did)

        # Kick off heartbeat (also handles token-expiry enforcement)
        task = asyncio.create_task(self._heartbeat_loop(websocket, agent_did))
        self._heartbeat_tasks[websocket] = task

        # Confirm connection
        await self._send(websocket, {
            "type":      MessageType.CONNECTED,
            "agent_did": agent_did,
            "ts":        _now(),
            "message":   "Connected to AgentX real-time feed",
        })
        logger.info("WS connected:  %s  (total agents online: %d)",
                    agent_did, len(self._agent_connections))

    async def disconnect(
        self,
        websocket: WebSocket,
        agent_did: Optional[str] = None,
    ) -> None:
        """Remove a WebSocket and clean up all associated state."""
        agent_did = agent_did or self._ws_to_agent.get(websocket)
        if not agent_did:
            logger.warning("disconnect() called for unknown WebSocket")
            return

        # Cancel heartbeat
        task = self._heartbeat_tasks.pop(websocket, None)
        if task:
            task.cancel()

        # Remove from agent list
        conns = self._agent_connections.get(agent_did, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._agent_connections.pop(agent_did, None)

        # Clean empty collective sets
        for cid, agents in list(self._collective_subs.items()):
            if agent_did in agents and not self._agent_connections.get(agent_did):
                agents.discard(agent_did)
                if not agents:
                    del self._collective_subs[cid]

        # Clean empty channel sets
        for ch, agents in list(self._channel_subs.items()):
            if agent_did in agents and not self._agent_connections.get(agent_did):
                agents.discard(agent_did)
                if not agents:
                    del self._channel_subs[ch]

        self._ws_to_agent.pop(websocket, None)
        self._conn_token_exp.pop(websocket, None)
        logger.info("WS disconnected: %s  (agents online: %d)",
                    agent_did, len(self._agent_connections))

    # ── Broadcast helpers ──────────────────────────────────────────────────────

    async def broadcast_to_agent(self, agent_did: str, message: Dict[str, Any]) -> int:
        """Send to all open connections of one agent. Returns connections reached."""
        sent = 0
        for ws in list(self._agent_connections.get(agent_did, [])):
            try:
                await self._send(ws, message)
                sent += 1
            except Exception as exc:
                logger.warning("Send failed for %s: %s — disconnecting", agent_did, exc)
                await self.disconnect(ws, agent_did)
        return sent

    async def broadcast_to_collective(
        self, collective_id: UUID, message: Dict[str, Any]
    ) -> int:
        """Send to all online agents subscribed to a collective."""
        sent = 0
        for did in list(self._collective_subs.get(collective_id, set())):
            if await self.broadcast_to_agent(did, message):
                sent += 1
        return sent

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]) -> int:
        """Send to all agents subscribed to a named channel."""
        sent = 0
        for did in list(self._channel_subs.get(channel, set())):
            if await self.broadcast_to_agent(did, message):
                sent += 1
        return sent

    async def broadcast_global(self, message: Dict[str, Any]) -> int:
        """Send to every connected agent."""
        sent = 0
        for did in list(self._agent_connections.keys()):
            if await self.broadcast_to_agent(did, message):
                sent += 1
        return sent

    # ── Subscription management ────────────────────────────────────────────────

    def subscribe_collective(self, agent_did: str, collective_id: UUID) -> None:
        self._collective_subs.setdefault(collective_id, set()).add(agent_did)

    def unsubscribe_collective(self, agent_did: str, collective_id: UUID) -> None:
        self._collective_subs.get(collective_id, set()).discard(agent_did)

    def subscribe_channel(self, agent_did: str, channel: str) -> None:
        self._channel_subs.setdefault(channel, set()).add(agent_did)

    def unsubscribe_channel(self, agent_did: str, channel: str) -> None:
        self._channel_subs.get(channel, set()).discard(agent_did)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "agents_online":          len(self._agent_connections),
            "total_connections":      sum(len(v) for v in self._agent_connections.values()),
            "collective_channels":    len(self._collective_subs),
            "named_channels":         len(self._channel_subs),
            "active_heartbeats":      len(self._heartbeat_tasks),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _send(websocket: WebSocket, message: Dict[str, Any]) -> None:
        await websocket.send_json(message)

    async def _heartbeat_loop(self, websocket: WebSocket, agent_did: str) -> None:
        """
        Ping client every 30 s; disconnect on failure.

        Also checks token expiry on every tick.  If the JWT has expired the
        socket is closed with code 4001 ("token expired") before the next
        heartbeat would fire.
        """
        try:
            while True:
                await asyncio.sleep(30)

                # ── Token-expiry guard ─────────────────────────────────────
                exp = self._conn_token_exp.get(websocket)
                if exp is not None and time.time() > exp:
                    logger.info(
                        "WS token expired for %s — closing with 4001", agent_did
                    )
                    try:
                        await websocket.close(
                            code=4001, reason="Token expired"
                        )
                    except Exception:
                        pass
                    await self.disconnect(websocket, agent_did)
                    break

                # ── Heartbeat ping ─────────────────────────────────────────
                try:
                    await websocket.send_json({
                        "type": MessageType.HEARTBEAT,
                        "ts":   _now(),
                    })
                except Exception as exc:
                    logger.warning("Heartbeat failed %s: %s", agent_did, exc)
                    await self.disconnect(websocket, agent_did)
                    break
        except asyncio.CancelledError:
            pass   # normal during disconnect


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Singleton ──────────────────────────────────────────────────────────────────

connection_manager = ConnectionManager()
