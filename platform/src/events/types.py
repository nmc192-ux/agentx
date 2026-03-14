"""
AgentX Event Bus — Event Type Definitions
══════════════════════════════════════════
Phase 7: Event-Driven Architecture

All events flowing through the `agentx.events` Redis Stream are typed here.
`AgentXEvent` is the canonical envelope; handlers receive it after deserialization.

SOURCE: Phase 7 implementation plan — ATLAS Sprint 5
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


# ── Event types ───────────────────────────────────────────────────────────────

class EventType(str, Enum):
    """All event types flowing through the agentx.events Redis Stream."""
    TASK_CREATED       = "TASK_CREATED"
    TASK_ASSIGNED      = "TASK_ASSIGNED"
    TASK_COMPLETED     = "TASK_COMPLETED"
    TASK_FAILED        = "TASK_FAILED"
    POST_CREATED       = "POST_CREATED"
    AGENT_REGISTERED   = "AGENT_REGISTERED"
    TRUST_UPDATED      = "TRUST_UPDATED"
    COLLECTIVE_CREATED = "COLLECTIVE_CREATED"
    COLLECTIVE_JOINED  = "COLLECTIVE_JOINED"


# ── Event envelope ────────────────────────────────────────────────────────────

@dataclass
class AgentXEvent:
    """
    Canonical event envelope for the agentx.events Redis Stream.

    Redis Streams store flat string→string dictionaries; `to_stream_fields`
    serialises the envelope for XADD and `from_stream_fields` reconstructs
    it after XREADGROUP.
    """
    event_type:       EventType
    payload:          dict[str, Any]
    source_agent_did: str | None = None
    event_id:         str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:        str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def to_stream_fields(self) -> dict[str, str]:
        """Flatten to the flat string dict required by Redis XADD."""
        return {
            "event_id":         self.event_id,
            "event_type":       self.event_type.value,
            "source_agent_did": self.source_agent_did or "",
            "payload":          json.dumps(self.payload),
            "timestamp":        self.timestamp,
        }

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> "AgentXEvent":
        """Reconstruct an AgentXEvent from a Redis stream entry's field dict."""
        return cls(
            event_type=EventType(fields["event_type"]),
            payload=json.loads(fields.get("payload", "{}")),
            source_agent_did=fields.get("source_agent_did") or None,
            event_id=fields.get("event_id", str(uuid.uuid4())),
            timestamp=fields.get("timestamp", datetime.now(UTC).isoformat()),
        )
