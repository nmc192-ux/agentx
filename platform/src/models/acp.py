"""AgentX Platform — ACP (Agent Communication Protocol) Pydantic models.

ACP-1.0 message envelope enforced here.  All fields are required;
validators reject any message that does not conform to the spec in
~/AgentX/AGENT_PROTOCOL.md.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Constants ──────────────────────────────────────────────────────────────────

ACP_VERSION: Literal["ACP-1.0"] = "ACP-1.0"

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

# did:method:specific-id  — very permissive but catches obvious garbage
_DID_RE = re.compile(r"^did:[a-z][a-z0-9._-]*:[A-Za-z0-9._:-]+$")


# ── ACP Envelope ──────────────────────────────────────────────────────────────


class ACPMessage(BaseModel):
    """Full ACP-1.0 message envelope.

    Every field is **required** by the protocol spec.  Pydantic validators
    enforce protocol_version, type, agent_id (DID format), and message_id
    (UUID) constraints.

    Attributes:
        protocol_version: Must be exactly ``"ACP-1.0"``.
        message_id:       UUID v4 uniquely identifying this message.
        timestamp:        ISO-8601 datetime when the message was created.
        agent_id:         DID of the sending agent (``did:method:id`` format).
        type:             One of the seven allowed ACP message types.
        human_summary:    Short natural-language description for humans.
        machine_payload:  Structured JSON payload for machine consumption.
        metadata:         Arbitrary key/value annotations (routing, tracing, …).
        receiver_did:     Optional DID of the intended recipient (None = broadcast).
        channel:          Optional logical channel name (default ``"default"``).
    """

    protocol_version: str = Field(
        default=ACP_VERSION,
        description="Must be 'ACP-1.0'",
    )
    message_id: UUID = Field(
        description="UUID uniquely identifying this message",
    )
    timestamp: datetime = Field(
        description="ISO-8601 datetime when the message was created",
    )
    agent_id: str = Field(
        description="DID of the sending agent (did:method:id format)",
    )
    type: str = Field(
        description="ACP message type (see ALLOWED_TYPES)",
    )
    human_summary: str = Field(
        min_length=1,
        max_length=500,
        description="Short natural-language summary for humans",
    )
    machine_payload: dict[str, Any] = Field(
        description="Structured payload for machine consumption",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary annotations (routing, tracing, etc.)",
    )
    receiver_did: Optional[str] = Field(
        default=None,
        description="DID of the intended recipient; None = broadcast",
    )
    channel: str = Field(
        default="default",
        description="Logical channel name",
    )

    # ── Validators ─────────────────────────────────────────────────────────────

    @field_validator("protocol_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != ACP_VERSION:
            raise ValueError(
                f"protocol_version must be '{ACP_VERSION}', got '{v}'"
            )
        return v

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            allowed = ", ".join(sorted(ALLOWED_TYPES))
            raise ValueError(
                f"type '{v}' is not allowed. Must be one of: {allowed}"
            )
        return v

    @field_validator("agent_id")
    @classmethod
    def _check_agent_did(cls, v: str) -> str:
        if not _DID_RE.match(v):
            raise ValueError(
                f"agent_id must be a valid DID (did:method:id), got '{v}'"
            )
        return v

    @field_validator("receiver_did")
    @classmethod
    def _check_receiver_did(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DID_RE.match(v):
            raise ValueError(
                f"receiver_did must be a valid DID (did:method:id), got '{v}'"
            )
        return v

    model_config = {"from_attributes": True}


# ── Thin create / response wrappers ───────────────────────────────────────────


class ACPMessageCreate(ACPMessage):
    """Request body for POST /agentbus/send.

    Identical to ACPMessage but message_id and timestamp are optional —
    the service layer will fill them in if omitted.
    """

    message_id: Optional[UUID] = Field(  # type: ignore[assignment]
        default=None,
        description="Omit to let the server generate a UUID",
    )
    timestamp: Optional[datetime] = Field(  # type: ignore[assignment]
        default=None,
        description="Omit to let the server use the current UTC time",
    )


class ACPMessageResponse(ACPMessage):
    """Response body — identical to ACPMessage (all fields populated)."""

    model_config = {"from_attributes": True}
