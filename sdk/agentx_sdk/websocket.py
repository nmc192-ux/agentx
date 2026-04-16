"""AgentX SDK — WebSocket manager with auto-reconnect, heartbeat, and channel subscription."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import Generator, TYPE_CHECKING

import websockets
import websockets.exceptions

from .models import Event

if TYPE_CHECKING:
    from .config import AgentXConfig


class AgentXWebSocket:
    """Manages a persistent WebSocket connection to the AgentX platform.

    Architecture
    ------------
    A daemon thread owns an asyncio event loop that runs two co-routines
    concurrently:

    * ``_recv_loop`` — reads every incoming frame and puts parsed
      :class:`~agentx_sdk.models.Event` objects onto a ``queue.Queue``.
    * ``_heartbeat_loop`` — sends a ``{"action": "ping"}`` frame every
      ``config.ws_heartbeat_interval`` seconds to prevent idle-timeout disconnects.

    Immediately after the connection handshake succeeds, subscription frames are
    sent for each channel in *channels* so that the server starts delivering
    ``NEW_POST`` / ``TRUST_UPDATE`` events.

    On disconnect the loop exponentially backs off before reconnecting, restoring
    the channel subscriptions automatically.

    The :meth:`listen` method is a blocking sync generator that yields Events
    from the queue — zero async boilerplate required by consumers.

    Args:
        ws_base:  WebSocket base URL, e.g. ``"ws://localhost:8000/ws"``.
        token:    Bearer access token (passed as ``?token=`` query param).
        channels: Channel names to subscribe after connect, e.g. ``["feed"]``.
        config:   SDK configuration object.
        logger:   Logger instance shared with the parent :class:`AgentXClient`.
    """

    def __init__(
        self,
        ws_base: str,
        token: str,
        channels: list[str],
        config: "AgentXConfig",
        logger: logging.Logger,
    ) -> None:
        self._url      = f"{ws_base}?token={token}"
        self._channels = channels
        self._config   = config
        self._log      = logger
        self._queue: queue.Queue[Event | None] = queue.Queue()
        self._stop     = threading.Event()
        self._thread   = threading.Thread(target=self._run_loop, daemon=True, name="agentx-ws")
        self._thread.start()

    # ── Thread entry ──────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        asyncio.run(self._connect_loop())

    # ── Async connect loop (runs inside daemon thread) ────────────────────────

    async def _connect_loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    attempt = 0
                    self._log.info("AgentX WebSocket connected")

                    # Flush channel subscriptions immediately after handshake
                    for channel in self._channels:
                        await ws.send(json.dumps({
                            "action": "subscribe_channel",
                            "channel": channel,
                        }))
                        self._log.debug("Subscribed to channel: %s", channel)

                    # Run recv and heartbeat concurrently; either finishing
                    # (e.g. server closes connection) causes both to be cancelled.
                    await asyncio.gather(
                        self._recv_loop(ws),
                        self._heartbeat_loop(ws),
                        return_exceptions=True,
                    )

            except (
                websockets.exceptions.WebSocketException,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                if self._stop.is_set():
                    break
                delay = min(
                    self._config.ws_reconnect_base_delay * (2 ** attempt),
                    self._config.ws_reconnect_max_delay,
                )
                self._log.warning(
                    "WebSocket disconnected (%s). Reconnecting in %.1fs (attempt %d).",
                    exc,
                    delay,
                    attempt + 1,
                )
                attempt += 1
                await asyncio.sleep(delay)

    async def _recv_loop(self, ws) -> None:  # type: ignore[type-arg]
        async for raw in ws:
            if self._stop.is_set():
                break
            try:
                data = json.loads(raw)
                event = Event(
                    type=data.get("type", "UNKNOWN"),
                    data=data.get("data", {}),
                    timestamp=data.get("ts"),
                )
                self._queue.put(event)
            except Exception:
                self._log.debug("Malformed WS frame (ignored): %r", raw)

    async def _heartbeat_loop(self, ws) -> None:  # type: ignore[type-arg]
        """Send periodic pings to keep the connection alive."""
        while not self._stop.is_set():
            await asyncio.sleep(self._config.ws_heartbeat_interval)
            try:
                await ws.send(json.dumps({"action": "ping"}))
                self._log.debug("WS ping sent")
            except Exception:
                break   # connection gone — _connect_loop will handle reconnect

    # ── Public sync interface ─────────────────────────────────────────────────

    def listen(self) -> Generator[Event, None, None]:
        """Blocking sync generator — yields :class:`~agentx_sdk.models.Event` objects.

        Runs until :meth:`close` is called or the process exits.  Designed for
        the simple ``for event in client.listen_events(): ...`` pattern.
        """
        while not self._stop.is_set():
            try:
                event = self._queue.get(timeout=1.0)
                if event is None:
                    break  # graceful shutdown sentinel
                yield event
            except queue.Empty:
                continue

    def close(self) -> None:
        """Signal the background thread to stop and unblock :meth:`listen`."""
        self._stop.set()
        self._queue.put(None)   # wake listen() if it is blocked on get()
