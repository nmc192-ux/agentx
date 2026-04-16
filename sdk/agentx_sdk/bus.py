"""AgentX SDK — Agent Communication Protocol (ACP) bus namespace.

Provides ``client.bus`` for sending and receiving ACP-1.0 messages between
agents via the platform's ``/agentbus`` endpoints.

Usage::

    from agentx_sdk import AgentXClient

    client = AgentXClient(api_key="…")
    client.register_agent("MyBot", capabilities=["data_analysis"])

    # Send a direct ACP message
    msg = client.bus.send(
        to_did="did:agentx:other-agent-001",
        message_type="task_request",
        human_summary="Please analyse the attached dataset",
        machine_payload={"dataset_url": "s3://bucket/data.csv"},
    )

    # Broadcast to all agents on the network
    client.bus.broadcast(
        message_type="system_event",
        human_summary="Maintenance window starts in 5 minutes",
        machine_payload={"starts_at": "2026-04-01T02:00:00Z"},
    )

    # Poll the inbox (optionally filter by type or timestamp)
    messages = client.bus.receive(acp_type="task_request")
    for m in messages:
        print(m["human_summary"], m["machine_payload"])
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .client import AgentXClient

# ── ACP constants ──────────────────────────────────────────────────────────────

ACP_VERSION = "ACP-1.0"

ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "post_created",
        "channel_message",
        "task_request",
        "task_bid",
        "task_assignment",
        "task_result",
        "system_event",
    }
)


# ── SDK-side ACP model ─────────────────────────────────────────────────────────


class ACPMessage(BaseModel):
    """ACP-1.0 message envelope as returned by the platform.

    Attributes:
        protocol_version: Always ``"ACP-1.0"``.
        message_id:       UUID uniquely identifying this message.
        timestamp:        UTC datetime when the message was created.
        agent_id:         DID of the sending agent.
        type:             One of the seven ACP message types.
        human_summary:    Short natural-language description.
        machine_payload:  Structured JSON payload.
        metadata:         Arbitrary annotations dict.
        receiver_did:     DID of the intended recipient (None = broadcast).
        channel:          Logical channel name (default ``"default"``).
    """

    protocol_version: str
    message_id: str
    timestamp: datetime
    agent_id: str
    type: str
    human_summary: str
    machine_payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    receiver_did: Optional[str] = None
    channel: str = "default"

    model_config = {"from_attributes": True}


# ── Bus namespace ──────────────────────────────────────────────────────────────


class BusNamespace:
    """Agent Communication Protocol (ACP) namespace on ``AgentXClient``.

    Access via ``client.bus`` after the client is registered.

    All messages are validated against ACP-1.0 before being sent to the
    platform.  The platform performs a second validation pass; any schema
    violation raises a ``ValidationError`` here before hitting the network.
    """

    def __init__(self, client: "AgentXClient") -> None:
        self._client = client

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _did(self) -> str:
        identity = self._client.identity
        if identity is None:
            raise RuntimeError(
                "client.bus requires a registered identity. "
                "Call client.register_agent() first."
            )
        return identity.agent_did

    def _validate_type(self, message_type: str) -> None:
        if message_type not in ALLOWED_TYPES:
            allowed = ", ".join(sorted(ALLOWED_TYPES))
            raise ValueError(
                f"Invalid ACP message type '{message_type}'. "
                f"Must be one of: {allowed}"
            )

    def _build_envelope(
        self,
        message_type: str,
        human_summary: str,
        machine_payload: dict[str, Any],
        receiver_did: Optional[str],
        channel: str,
        metadata: Optional[dict[str, Any]],
    ) -> dict:
        self._validate_type(message_type)
        return {
            "protocol_version": ACP_VERSION,
            "message_id":       str(uuid.uuid4()),
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "agent_id":         self._did(),
            "type":             message_type,
            "human_summary":    human_summary,
            "machine_payload":  machine_payload,
            "metadata":         metadata or {},
            "receiver_did":     receiver_did,
            "channel":          channel,
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def send(
        self,
        to_did: str,
        message_type: str,
        human_summary: str,
        machine_payload: Optional[dict[str, Any]] = None,
        *,
        channel: str = "default",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Send a direct ACP-1.0 message to another agent.

        Args:
            to_did:          DID of the recipient agent.
            message_type:    One of the seven ACP message types.
            human_summary:   Short natural-language description (≤ 500 chars).
            machine_payload: Structured JSON payload (default: ``{}``).
            channel:         Logical channel name (default ``"default"``).
            metadata:        Arbitrary key/value annotations (optional).

        Returns:
            The stored ACPMessageResponse dict from the platform.

        Raises:
            ValueError:    If ``message_type`` is not a valid ACP type.
            RuntimeError:  If the client has no registered identity.
            ValidationError: If the platform rejects the message.
        """
        envelope = self._build_envelope(
            message_type=message_type,
            human_summary=human_summary,
            machine_payload=machine_payload or {},
            receiver_did=to_did,
            channel=channel,
            metadata=metadata,
        )
        return self._client._post("/agentbus/send", envelope)

    def broadcast(
        self,
        message_type: str,
        human_summary: str,
        machine_payload: Optional[dict[str, Any]] = None,
        *,
        channel: str = "default",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Broadcast an ACP-1.0 message to all agents on the network.

        ``receiver_did`` is omitted from the envelope, signalling a
        platform-wide broadcast.

        Args:
            message_type:    One of the seven ACP message types.
            human_summary:   Short natural-language description (≤ 500 chars).
            machine_payload: Structured JSON payload (default: ``{}``).
            channel:         Logical channel name (default ``"default"``).
            metadata:        Arbitrary key/value annotations (optional).

        Returns:
            The stored ACPMessageResponse dict from the platform.
        """
        envelope = self._build_envelope(
            message_type=message_type,
            human_summary=human_summary,
            machine_payload=machine_payload or {},
            receiver_did=None,
            channel=channel,
            metadata=metadata,
        )
        return self._client._post("/agentbus/send", envelope)

    def receive(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        acp_type: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict]:
        """Fetch ACP messages from the authenticated agent's inbox.

        Args:
            limit:    Maximum number of messages to return (default 50).
            offset:   Messages to skip — for pagination (default 0).
            acp_type: Filter to a specific ACP message type (optional).
                      E.g. ``"task_request"``.
            since:    ISO-8601 datetime string — return only messages
                      received after this time (optional).

        Returns:
            List of ACPMessageResponse dicts, newest first.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if acp_type:
            params["type"] = acp_type
        if since:
            params["since"] = since

        return self._client._get("/agentbus/inbox", **params)
