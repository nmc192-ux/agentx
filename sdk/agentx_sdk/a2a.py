"""AgentX SDK — A2A (Agent2Agent) protocol namespace.

Provides ``client.a2a`` for interoperating with A2A-compatible agents,
both on the AgentX platform and on external networks (LangGraph, CrewAI, etc.).

Usage::

    from agentx_sdk import AgentXClient

    client = AgentXClient(api_key="…")

    # Discover an external agent
    card = client.a2a.discover_remote("https://other-agent.example.com")
    print(card["name"], card["skills"])

    # Send an A2A message to an external agent
    result = client.a2a.send_message(
        agent_url="https://other-agent.example.com",
        text="Please summarise the attached report",
        context_id="session-abc-123",
    )
    task = result.get("result", {})
    print(task["status"]["state"])

    # Fetch this agent's own Agent Card from the platform
    my_card = client.a2a.get_my_card()
    print(my_card["skills"])

Reference: https://google.github.io/A2A/specification/
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from .client import AgentXClient


class A2ANamespace:
    """A2A protocol namespace on ``AgentXClient``.

    Access via ``client.a2a`` after instantiation.

    Methods that target **external** agents (``discover_remote``,
    ``send_message``) use ``httpx`` directly since the URLs are not the
    configured platform base URL.

    Methods that target the **platform** (``get_my_card``) use the
    standard ``self._client._get()`` helper so authentication headers
    and retry logic are applied automatically.
    """

    def __init__(self, client: "AgentXClient") -> None:
        self._client = client

    # ── External agent discovery ───────────────────────────────────────────────

    def discover_remote(self, url: str) -> dict:
        """Fetch an external A2A agent's Agent Card.

        Retrieves the Agent Card JSON document from
        ``{url}/.well-known/agent.json`` — the standard A2A discovery URL.

        Args:
            url: Base URL of the external A2A agent/server (no trailing slash).
                 E.g. ``"https://langgraph-agent.example.com"``.

        Returns:
            Parsed Agent Card dict containing name, description, skills,
            capabilities, authentication, etc.

        Raises:
            httpx.HTTPError:    If the request fails or the server is unreachable.
            httpx.HTTPStatusError: If the server returns a non-2xx status.
        """
        base = url.rstrip("/")
        resp = httpx.get(f"{base}/.well-known/agent.json", timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── External agent messaging ───────────────────────────────────────────────

    def send_message(
        self,
        agent_url: str,
        text: str,
        context_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Send an A2A ``message/send`` JSON-RPC request to an external agent.

        Builds a compliant A2A message envelope and POSTs it to
        ``{agent_url}/a2a``.  The caller's DID (if a registered identity
        exists) is included in the message metadata so the remote agent
        can route replies.

        Args:
            agent_url:  Base URL of the target A2A agent (no trailing slash).
            text:       Plain-text content to send.
            context_id: Optional conversation context / thread ID.  Pass the
                        same value across turns to maintain a conversation.
            metadata:   Arbitrary key/value annotations attached to the
                        message/send params (optional).

        Returns:
            Full JSON-RPC 2.0 response dict.  On success, ``result`` contains
            an ``A2ATask`` with ``status.state`` and ``id``.  On error,
            ``error`` contains ``code``, ``message``, and optional ``data``.

        Raises:
            httpx.HTTPError:       If the network request fails.
            httpx.HTTPStatusError: If the server returns a non-2xx HTTP status.
        """
        message_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # Include caller DID in metadata so the remote agent can reply
        caller_did = (
            self._client.identity.agent_did if self._client.identity else None
        )
        combined_metadata: dict = {**(metadata or {})}
        if caller_did:
            combined_metadata["caller_did"] = caller_did

        message: dict = {
            "role":      "user",
            "parts":     [{"kind": "text", "text": text}],
            "messageId": message_id,
        }
        if context_id:
            message["contextId"] = context_id

        payload = {
            "jsonrpc": "2.0",
            "id":      request_id,
            "method":  "message/send",
            "params":  {
                "message":  message,
                "metadata": combined_metadata,
            },
        }

        base = agent_url.rstrip("/")
        resp = httpx.post(f"{base}/a2a", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── Platform-side A2A ──────────────────────────────────────────────────────

    def get_my_card(self) -> dict:
        """Fetch this agent's own Agent Card from the AgentX platform.

        Retrieves the Agent Card at
        ``GET /agents/{agent_did}/.well-known/agent.json``.

        Returns:
            Agent Card dict for the currently registered identity.

        Raises:
            RuntimeError:  If the client has no registered identity.
            NotFoundError: If the platform does not have a card for this DID.
        """
        if not self._client.identity:
            raise RuntimeError(
                "client.a2a.get_my_card() requires a registered identity. "
                "Call client.register_agent() first."
            )
        did = self._client.identity.agent_did
        return self._client._get(f"/agents/{did}/.well-known/agent.json")
