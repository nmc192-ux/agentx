"""
AgentX Event Bus — WebSocket Event Handler
═══════════════════════════════════════════
Step 5.1: Expand WebSocket Event Forwarding

Forwards economic, contract, governance, verification, and bounty events to
the relevant connected WebSocket clients via the ConnectionManager singleton.

Design
──────
• Uses ``connection_manager.broadcast_to_agent(did, msg)`` for targeted
  delivery (one or more specific agent DIDs per event type).
• Uses ``connection_manager.broadcast_global(msg)`` for governance events
  that every connected agent should receive.
• Does NOT write to the ``events`` DB table (that is handled by
  ``services/events.py`` via other handlers or direct service calls).
• Does NOT interfere with the Phase-7 handlers (feed, notification,
  reputation) — those continue to operate independently.

Target DID resolution
─────────────────────
Each event type maps to a set of agent DIDs that should receive it:

  Contract   → creator_did  + assigned_did
  Token      → from_did     + to_did
  Task econ  → requester_agent_did + executor_agent_did
  Governance → broadcast_global (all connected agents)
  Verification → requester_did + verifier_did + (contract parties)
  Bounty     → creator_did  + submitter_did
  Stake      → agent_did

Payload field names are extracted defensively with multiple fallbacks so
the handler does not break if a service uses a slightly different key name.
"""
from __future__ import annotations

import logging
from typing import Any

from ..types import AgentXEvent, EventType

logger = logging.getLogger(__name__)

# ── Governance event types (always broadcast to all connected agents) ──────────

_GOVERNANCE_EVENTS: frozenset[EventType] = frozenset({
    EventType.PROPOSAL_CREATED,
    EventType.VOTE_CAST,
    EventType.PROPOSAL_EXECUTED,
})

# ── All event types handled by this handler ───────────────────────────────────

HANDLED_EVENT_TYPES: frozenset[EventType] = frozenset({
    # Contract lifecycle
    EventType.CONTRACT_CREATED,
    EventType.CONTRACT_BID_SUBMITTED,
    EventType.CONTRACT_ASSIGNED,
    EventType.CONTRACT_RESULT_SUBMITTED,
    EventType.CONTRACT_COMPLETED,
    EventType.CONTRACT_DISPUTED,
    # Token economy
    EventType.TOKEN_TRANSFER,
    EventType.TASK_ESCROWED,
    EventType.TASK_REWARD_RELEASED,
    # Governance (global broadcast)
    EventType.PROPOSAL_CREATED,
    EventType.VOTE_CAST,
    EventType.PROPOSAL_EXECUTED,
    # Verification engine
    EventType.CONTRACT_VERIFICATION_REQUESTED,
    EventType.VERIFICATION_SUBMITTED,
    EventType.CONTRACT_VERIFIED,
    # Bounty markets
    EventType.BOUNTY_CREATED,
    EventType.BOUNTY_SUBMISSION,
    EventType.BOUNTY_EVALUATED,
    EventType.BOUNTY_REWARD_DISTRIBUTED,
    # Staking
    EventType.STAKE_SLASHED,
})


# ── Target DID extraction ──────────────────────────────────────────────────────

def _extract_targets(event: AgentXEvent) -> list[str]:
    """
    Determine which agent DIDs should receive this event's WS notification.

    Returns an empty list for governance events (caller uses broadcast_global
    instead).  Returns a deduplicated list of DIDs for targeted events.
    """
    if event.event_type in _GOVERNANCE_EVENTS:
        return []   # handled by broadcast_global in handle()

    p = event.payload
    dids: set[str] = set()

    # Always include the source agent if we have one
    if event.source_agent_did:
        dids.add(event.source_agent_did)

    etype = event.event_type

    # ── Contract events ──────────────────────────────────────────────────────
    if etype in {
        EventType.CONTRACT_CREATED,
        EventType.CONTRACT_BID_SUBMITTED,
        EventType.CONTRACT_ASSIGNED,
        EventType.CONTRACT_RESULT_SUBMITTED,
        EventType.CONTRACT_COMPLETED,
        EventType.CONTRACT_DISPUTED,
    }:
        _add(dids, p, "creator_did", "requester_did", "requester_agent_did")
        _add(dids, p, "assigned_did", "executor_did", "executor_agent_did", "bidder_did")

    # ── Token / escrow events ─────────────────────────────────────────────────
    elif etype == EventType.TOKEN_TRANSFER:
        _add(dids, p, "from_did", "sender_did", "from_agent_did")
        _add(dids, p, "to_did", "receiver_did", "to_agent_did")

    elif etype in {EventType.TASK_ESCROWED, EventType.TASK_REWARD_RELEASED}:
        _add(dids, p,
             "requester_agent_did", "requester_did",
             "executor_agent_did",  "executor_did",
             "agent_did")

    # ── Verification events ───────────────────────────────────────────────────
    elif etype in {
        EventType.CONTRACT_VERIFICATION_REQUESTED,
        EventType.VERIFICATION_SUBMITTED,
        EventType.CONTRACT_VERIFIED,
    }:
        _add(dids, p,
             "requester_did", "creator_did", "requester_agent_did",
             "assigned_did",  "executor_did",
             "verifier_did",  "submitter_did")

    # ── Bounty events ─────────────────────────────────────────────────────────
    elif etype in {
        EventType.BOUNTY_CREATED,
        EventType.BOUNTY_SUBMISSION,
        EventType.BOUNTY_EVALUATED,
        EventType.BOUNTY_REWARD_DISTRIBUTED,
    }:
        _add(dids, p, "creator_did", "owner_did", "agent_did")
        _add(dids, p, "submitter_did", "winner_did")

    # ── Stake slashed ─────────────────────────────────────────────────────────
    elif etype == EventType.STAKE_SLASHED:
        _add(dids, p, "agent_did", "slashed_did")

    # Remove empty strings that snuck in from missing payload fields
    dids.discard("")
    return list(dids)


def _add(target: set[str], payload: dict[str, Any], *keys: str) -> None:
    """Add the first non-empty value found among *keys* to *target*."""
    for key in keys:
        val = payload.get(key)
        if val and isinstance(val, str):
            target.add(val)
            return   # only add one value per logical role


# ── WS message builder ────────────────────────────────────────────────────────

def _build_message(event: AgentXEvent) -> dict[str, Any]:
    """Build the JSON frame that will be sent to WebSocket clients."""
    return {
        "type":     event.event_type.value,
        "data":     event.payload,
        "ts":       event.timestamp,
        "event_id": event.event_id,
    }


# ── Public handler ────────────────────────────────────────────────────────────

async def handle(event: AgentXEvent) -> None:
    """
    Forward *event* to the relevant WebSocket clients.

    Governance events are broadcast globally (all connected agents).
    All other events are delivered only to the agent DIDs extracted from
    the event payload (creator, executor, sender, receiver, etc.).

    Args:
        event: Decoded AgentXEvent from the event bus.
    """
    # Lazy import — avoids circular imports at module load time
    from ...websocket.manager import connection_manager

    if event.event_type not in HANDLED_EVENT_TYPES:
        logger.warning(
            "websocket_handler received unexpected event_type=%s", event.event_type
        )
        return

    message = _build_message(event)

    # ── Governance: broadcast to all connected agents ─────────────────────────
    if event.event_type in _GOVERNANCE_EVENTS:
        reached = await connection_manager.broadcast_global(message)
        logger.debug(
            "websocket_handler: %s broadcast_global reached=%d",
            event.event_type.value, reached,
        )
        return

    # ── Targeted: send only to relevant parties ───────────────────────────────
    targets = _extract_targets(event)

    if not targets:
        logger.debug(
            "websocket_handler: %s — no target DIDs found in payload, skipping WS push",
            event.event_type.value,
        )
        return

    total_reached = 0
    for did in targets:
        reached = await connection_manager.broadcast_to_agent(did, message)
        total_reached += reached

    logger.debug(
        "websocket_handler: %s → %d target(s), %d connection(s) reached",
        event.event_type.value, len(targets), total_reached,
    )
