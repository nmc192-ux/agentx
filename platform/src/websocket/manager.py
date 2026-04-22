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

HA / Redis pub/sub fan-out:
  On startup, call ``await connection_manager.init_pubsub(redis_url)``.
  Each Fly.io machine subscribes to the ``agentx:ws:*`` Redis pattern.
  All broadcast_* methods deliver locally *and* publish to Redis so that
  agents connected to sibling machines receive every event.

  Channel layout:
    agentx:ws:global          — broadcast_global
    agentx:ws:ch:{name}       — broadcast_to_channel("feed", …)
    agentx:ws:col:{uuid}      — broadcast_to_collective(uuid, …)
    agentx:ws:did:{agent_did} — broadcast_to_agent(did, …)

  Deduplication: each publish envelope carries ``_src = socket.gethostname()``.
  The subscriber on the publishing machine skips messages from itself so
  agents on that machine are *not* double-delivered.

  Fallback: when ``redis_url`` starts with ``memory://`` (dev / test) the
  pub/sub layer is silently skipped and delivery is local-only.

SOURCE: workspace/shared/websocket_layer.md — DARIA Sprint 5
"""
import asyncio
import json
import logging
import socket
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── Machine identity (unique per Fly.io VM) ────────────────────────────────────
_MACHINE_ID: str = socket.gethostname()

# ── Redis pub/sub channel names ────────────────────────────────────────────────
_PUB_GLOBAL      = "agentx:ws:global"
_PUB_CHANNEL_PFX = "agentx:ws:ch:"      # + channel name
_PUB_COLL_PFX    = "agentx:ws:col:"     # + str(collective UUID)
_PUB_AGENT_PFX   = "agentx:ws:did:"     # + agent DID
_PUB_PATTERN     = "agentx:ws:*"


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
      - Redis pub/sub fan-out for HA (2+ Fly machines)
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

        # Redis connection used for PUBLISH (HA fan-out); None = local-only
        self._redis_pub: Optional[Any] = None  # redis.asyncio.Redis

        # Background task running the pub/sub listener loop
        self._pubsub_task: Optional[asyncio.Task] = None

        logger.info("WebSocket ConnectionManager initialised (machine=%s)", _MACHINE_ID)

    # ── Pub/Sub lifecycle ──────────────────────────────────────────────────────

    async def init_pubsub(self, redis_url: str) -> None:
        """
        Start the Redis pub/sub fan-out layer.

        Creates two Redis connections:
          1. ``_redis_pub`` — used by broadcast methods to PUBLISH
          2. A private subscriber connection running ``_pubsub_listener``

        Safe no-op when ``redis_url`` is ``memory://`` (dev / CI).
        """
        if redis_url.startswith("memory://"):
            logger.info("WS pub/sub: memory:// backend — local-only mode")
            return

        from redis.asyncio import Redis as AIORedis  # noqa: PLC0415

        try:
            # Publisher connection (shared pool)
            self._redis_pub = AIORedis.from_url(redis_url, decode_responses=True)
            await self._redis_pub.ping()

            # Dedicated subscriber connection
            sub_redis = AIORedis.from_url(redis_url, decode_responses=True)
            pubsub = sub_redis.pubsub()
            await pubsub.psubscribe(_PUB_PATTERN)

            self._pubsub_task = asyncio.create_task(
                self._pubsub_listener(pubsub, sub_redis),
                name="ws-pubsub-listener",
            )
            # Mask the password portion of the URL in logs
            safe_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
            logger.info(
                "WS pub/sub: subscribed to %s on %s (machine=%s)",
                _PUB_PATTERN, safe_url, _MACHINE_ID,
            )
        except Exception as exc:
            logger.warning(
                "WS pub/sub: init failed — falling back to local-only delivery: %s", exc
            )
            self._redis_pub = None

    async def close_pubsub(self) -> None:
        """Stop the pub/sub subscriber loop and close Redis connections."""
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None

        if self._redis_pub is not None:
            try:
                await self._redis_pub.aclose()
            except Exception as exc:
                logger.warning("WS pub/sub Redis close failed: %s", exc)
            self._redis_pub = None

        logger.info("WS pub/sub: closed")

    async def _pubsub_listener(self, pubsub: Any, sub_redis: Any) -> None:
        """
        Background loop: receive Redis pub/sub messages and fan-out locally.

        Each message envelope is ``{"_src": machine_id, "payload": {...}}``.
        Messages from this machine are skipped (already delivered locally).
        """
        try:
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                channel: str = message["channel"]
                raw: str     = message["data"]
                try:
                    envelope = json.loads(raw)
                    if envelope.get("_src") == _MACHINE_ID:
                        continue  # we published this — skip to avoid double-delivery
                    payload = envelope.get("payload", envelope)
                except Exception:
                    continue
                try:
                    await self._dispatch_pubsub(channel, payload)
                except Exception as exc:
                    logger.warning("WS pub/sub dispatch error on %s: %s", channel, exc)
        except asyncio.CancelledError:
            logger.info("WS pub/sub listener cancelled (machine=%s)", _MACHINE_ID)
            raise
        except Exception as exc:
            logger.error("WS pub/sub listener crashed: %s", exc)
        finally:
            try:
                await pubsub.punsubscribe(_PUB_PATTERN)
            except Exception:
                pass
            try:
                await sub_redis.aclose()
            except Exception:
                pass

    async def _dispatch_pubsub(self, channel: str, payload: Dict[str, Any]) -> None:
        """Route an inbound Redis pub/sub message to local WebSocket connections."""
        if channel == _PUB_GLOBAL:
            for did in list(self._agent_connections):
                await self._local_broadcast_to_agent(did, payload)

        elif channel.startswith(_PUB_CHANNEL_PFX):
            ch_name = channel[len(_PUB_CHANNEL_PFX):]
            for did in list(self._channel_subs.get(ch_name, set())):
                await self._local_broadcast_to_agent(did, payload)

        elif channel.startswith(_PUB_COLL_PFX):
            try:
                col_id = UUID(channel[len(_PUB_COLL_PFX):])
            except ValueError:
                logger.warning("WS pub/sub: invalid collective UUID in channel %s", channel)
                return
            for did in list(self._collective_subs.get(col_id, set())):
                await self._local_broadcast_to_agent(did, payload)

        elif channel.startswith(_PUB_AGENT_PFX):
            did = channel[len(_PUB_AGENT_PFX):]
            await self._local_broadcast_to_agent(did, payload)

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

    # ── Local delivery (this machine only) ────────────────────────────────────

    async def _local_broadcast_to_agent(
        self, agent_did: str, message: Dict[str, Any]
    ) -> int:
        """
        Deliver ``message`` to all WebSocket connections for ``agent_did``
        **on this machine only**.  Returns the number of sockets reached.
        """
        sent = 0
        for ws in list(self._agent_connections.get(agent_did, [])):
            try:
                await self._send(ws, message)
                sent += 1
            except Exception as exc:
                logger.warning("Send failed for %s: %s — disconnecting", agent_did, exc)
                await self.disconnect(ws, agent_did)
        return sent

    # ── Broadcast helpers (local + Redis fan-out) ──────────────────────────────

    async def broadcast_to_agent(self, agent_did: str, message: Dict[str, Any]) -> int:
        """
        Send to all open connections of one agent across **all machines**.

        Delivers locally first, then publishes to Redis so sibling machines
        can reach agents connected there.
        """
        sent = await self._local_broadcast_to_agent(agent_did, message)
        if self._redis_pub is not None:
            try:
                envelope = {"_src": _MACHINE_ID, "payload": message}
                await self._redis_pub.publish(
                    f"{_PUB_AGENT_PFX}{agent_did}",
                    json.dumps(envelope, default=str),
                )
            except Exception as exc:
                logger.warning("Redis publish (agent:%s) failed: %s", agent_did, exc)
        return sent

    async def broadcast_to_collective(
        self, collective_id: UUID, message: Dict[str, Any]
    ) -> int:
        """Send to all online agents subscribed to a collective."""
        # Local delivery
        sent = 0
        for did in list(self._collective_subs.get(collective_id, set())):
            if await self._local_broadcast_to_agent(did, message):
                sent += 1
        # Remote fan-out
        if self._redis_pub is not None:
            try:
                envelope = {"_src": _MACHINE_ID, "payload": message}
                await self._redis_pub.publish(
                    f"{_PUB_COLL_PFX}{collective_id}",
                    json.dumps(envelope, default=str),
                )
            except Exception as exc:
                logger.warning(
                    "Redis publish (collective:%s) failed: %s", collective_id, exc
                )
        return sent

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]) -> int:
        """Send to all agents subscribed to a named channel."""
        # Local delivery
        sent = 0
        for did in list(self._channel_subs.get(channel, set())):
            if await self._local_broadcast_to_agent(did, message):
                sent += 1
        # Remote fan-out
        if self._redis_pub is not None:
            try:
                envelope = {"_src": _MACHINE_ID, "payload": message}
                await self._redis_pub.publish(
                    f"{_PUB_CHANNEL_PFX}{channel}",
                    json.dumps(envelope, default=str),
                )
            except Exception as exc:
                logger.warning("Redis publish (channel:%s) failed: %s", channel, exc)
        return sent

    async def broadcast_global(self, message: Dict[str, Any]) -> int:
        """Send to every connected agent across all machines."""
        # Local delivery
        sent = 0
        for did in list(self._agent_connections.keys()):
            if await self._local_broadcast_to_agent(did, message):
                sent += 1
        # Remote fan-out
        if self._redis_pub is not None:
            try:
                envelope = {"_src": _MACHINE_ID, "payload": message}
                await self._redis_pub.publish(
                    _PUB_GLOBAL,
                    json.dumps(envelope, default=str),
                )
            except Exception as exc:
                logger.warning("Redis publish (global) failed: %s", exc)
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
            "pubsub_active":          self._pubsub_task is not None
                                      and not self._pubsub_task.done(),
            "machine_id":             _MACHINE_ID,
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
