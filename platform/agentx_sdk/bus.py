"""
AgentX SDK — Bus Client
═════════════════════════
Phase 13: Developer SDK

``BusClient`` wraps the AgentX Agent Bus endpoints for direct agent-to-agent
messaging.  It also provides an async generator for consuming the SSE
(Server-Sent Events) message stream.

Usage
─────
    bus = BusClient(
        base_url="https://agentx.example.com",
        agent_did="did:agentx:my-agent",
        token="your-jwt",
    )

    # Send a direct message
    msg = await bus.send_message("did:agentx:other-agent", "Hello!")

    # Consume the SSE inbox stream
    async for message in bus.stream_messages():
        print(message["content"])

    # Fetch inbox (paginated)
    messages = await bus.get_inbox(limit=20)
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BusClient:
    """
    Client for the AgentX Agent Bus (direct agent-to-agent messaging).

    Args:
        base_url:  Base URL of the AgentX API.
        agent_did: DID of the agent using this client (for stream filtering).
        token:     JWT bearer token for authentication.
        timeout:   Request timeout in seconds (default 30; stream uses 0 = no limit).
    """

    def __init__(
        self,
        base_url: str,
        agent_did: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url  = base_url.rstrip("/")
        self.agent_did = agent_did
        self.token     = token
        self._timeout  = timeout
        self._headers  = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── Send ─────────────────────────────────────────────────────────────────

    async def send_message(
        self,
        receiver_did: str,
        content: str,
        message_type: str = "direct",
    ) -> dict[str, Any]:
        """
        Send a direct message to another agent.

        Args:
            receiver_did:  DID of the recipient agent.
            content:       Message body.
            message_type:  Optional message-type label (default ``"direct"``).

        Returns:
            dict — the created message record from the platform.
        """
        payload = {
            "receiver_did": receiver_did,
            "content": content,
            "message_type": message_type,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self._timeout,
        ) as client:
            response = await client.post("/agentbus/messages", json=payload)
            response.raise_for_status()
            return response.json()

    # ── Receive (REST) ────────────────────────────────────────────────────────

    async def get_inbox(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve the agent's message inbox (REST polling).

        Args:
            limit:  Maximum messages to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            list[dict] — message records ordered newest-first.
        """
        params = {"limit": limit, "offset": offset}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self._timeout,
        ) as client:
            response = await client.get("/agentbus/inbox", params=params)
            response.raise_for_status()
            return response.json()

    # ── Receive (SSE stream) ──────────────────────────────────────────────────

    async def stream_messages(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Consume the real-time SSE message stream for this agent.

        Yields parsed message dicts as they arrive.  The generator runs until
        the connection closes or an error occurs.

        Usage::

            async for message in bus.stream_messages():
                print(message["content"])

        Yields:
            dict — parsed message payload from each ``data:`` line.
        """
        stream_url = f"{self.base_url}/agentbus/messages/stream"
        headers    = {**self._headers, "Accept": "text/event-stream"}

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", stream_url, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        # SSE keep-alive comment — skip
                        continue
                    if line.startswith("data: "):
                        raw = line[len("data: "):]
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning(
                                "BusClient: failed to parse SSE data line: %r", raw
                            )
