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
    # ── Task lifecycle ─────────────────────────────────────────────────────────
    TASK_CREATED          = "TASK_CREATED"
    TASK_ASSIGNED         = "TASK_ASSIGNED"
    TASK_COMPLETED        = "TASK_COMPLETED"
    TASK_FAILED           = "TASK_FAILED"
    # ── Social ─────────────────────────────────────────────────────────────────
    POST_CREATED          = "POST_CREATED"
    AGENT_REGISTERED      = "AGENT_REGISTERED"
    TRUST_UPDATED         = "TRUST_UPDATED"
    COLLECTIVE_CREATED    = "COLLECTIVE_CREATED"
    COLLECTIVE_JOINED     = "COLLECTIVE_JOINED"
    # ── Phase 8.5: Economic Engine ─────────────────────────────────────────────
    TOKEN_TRANSFER        = "TOKEN_TRANSFER"
    TASK_ESCROWED         = "TASK_ESCROWED"
    TASK_REWARD_RELEASED  = "TASK_REWARD_RELEASED"
    STAKE_SLASHED         = "STAKE_SLASHED"
    TREASURY_REWARD       = "TREASURY_REWARD"
    TASK_VALUE_GENERATED  = "TASK_VALUE_GENERATED"
    # ── Phase 9: Governance Layer ──────────────────────────────────────────────
    PROPOSAL_CREATED      = "PROPOSAL_CREATED"
    VOTE_CAST             = "VOTE_CAST"
    PROPOSAL_EXECUTED     = "PROPOSAL_EXECUTED"
    # ── Phase 10: Contract Engine ──────────────────────────────────────────────
    CONTRACT_CREATED          = "CONTRACT_CREATED"
    CONTRACT_BID_SUBMITTED    = "CONTRACT_BID_SUBMITTED"
    CONTRACT_ASSIGNED         = "CONTRACT_ASSIGNED"
    CONTRACT_RESULT_SUBMITTED = "CONTRACT_RESULT_SUBMITTED"
    CONTRACT_COMPLETED        = "CONTRACT_COMPLETED"
    CONTRACT_DISPUTED         = "CONTRACT_DISPUTED"
    # ── Phase 11: Agent Bus ────────────────────────────────────────────────────
    AGENT_MESSAGE_SENT                  = "AGENT_MESSAGE_SENT"
    AGENT_MESSAGE_RECEIVED              = "AGENT_MESSAGE_RECEIVED"
    # ── Phase 12: Result Verification Engine ───────────────────────────────────
    CONTRACT_VERIFICATION_REQUESTED     = "CONTRACT_VERIFICATION_REQUESTED"
    VERIFICATION_SUBMITTED              = "VERIFICATION_SUBMITTED"
    CONTRACT_VERIFIED                   = "CONTRACT_VERIFIED"
    VERIFICATION_FAILED                 = "VERIFICATION_FAILED"
    # ── Phase 15: Autonomous Agent Markets ─────────────────────────────────────
    BOUNTY_CREATED                      = "BOUNTY_CREATED"
    BOUNTY_SUBMISSION                   = "BOUNTY_SUBMISSION"
    BOUNTY_EVALUATED                    = "BOUNTY_EVALUATED"
    BOUNTY_REWARD_DISTRIBUTED           = "BOUNTY_REWARD_DISTRIBUTED"


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
