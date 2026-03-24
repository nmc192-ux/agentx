"""
AgentX Platform — Agent Bus Service
═════════════════════════════════════
Phase 11 + ACP-1.0: Direct agent-to-agent messaging with ACP envelope
validation, inbox querying (with type/time filters), and real-time SSE
streaming via Redis pub/sub.

Public API
──────────
  send_acp_message(sender_did, data)                    → ACPMessageResponse
  get_acp_inbox(agent_did, limit, offset, acp_type,
                since)                                  → list[ACPMessageResponse]
  stream_messages(agent_did)                            → AsyncGenerator[str, None]

Design notes
────────────
• ACP envelope fields (protocol_version, acp_message_id, acp_timestamp,
  agent_id, acp_type, human_summary, machine_payload) are stored in the
  columns added by migration 034 alongside the legacy content / channel /
  metadata columns.
• message_id and timestamp are filled by the service if omitted by the caller.
• receiver_did is resolved to receiver_id for FK integrity.
• After DB insert the message is published to:
    1. Redis Stream (AGENT_MESSAGE_SENT event for the event bus)
    2. Redis pub/sub channel agentbus:{receiver_did} for live SSE delivery
• stream_messages() is an async generator for FastAPI StreamingResponse.
• Redis failures are logged but never propagated.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from ..cache import get_cache
from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.acp import ACPMessageCreate, ACPMessageResponse

logger = logging.getLogger(__name__)

_AGENTBUS_CHANNEL_PREFIX = "agentbus:"


def _agentbus_channel(agent_did: str) -> str:
    return f"{_AGENTBUS_CHANNEL_PREFIX}{agent_did}"


def _row_to_acp(row) -> ACPMessageResponse:
    """Convert a DB row to an ACPMessageResponse."""

    def _jsonb(col):
        val = row.get(col)
        if isinstance(val, str):
            return json.loads(val) if val else {}
        return dict(val) if val is not None else {}

    return ACPMessageResponse(
        protocol_version=row.get("protocol_version") or "ACP-1.0",
        message_id=row["acp_message_id"] or row["message_id"],
        timestamp=row.get("acp_timestamp") or row["created_at"],
        agent_id=row.get("agent_id") or row["sender_did"],
        type=row.get("acp_type") or "channel_message",
        human_summary=row.get("human_summary") or row.get("content", ""),
        machine_payload=_jsonb("machine_payload"),
        metadata=_jsonb("metadata"),
        receiver_did=row["receiver_did"],
        channel=row.get("channel") or "default",
    )


# ── Service functions ──────────────────────────────────────────────────────────

async def send_acp_message(
    sender_did: str,
    data: ACPMessageCreate,
) -> ACPMessageResponse:
    """
    Send an ACP-1.0 message from sender_did.

    Fills ``message_id`` and ``timestamp`` if the caller omitted them, then
    inserts the full ACP envelope into ``agent_messages``.  Publishes the
    message to the event bus and the recipient's SSE pub/sub channel.

    Args:
        sender_did: DID of the authenticated sender (from JWT).
        data:       Validated ACPMessageCreate payload.

    Returns:
        ACPMessageResponse with all fields populated.

    Raises:
        ValueError: If receiver_did is provided but not a registered agent.
    """
    # Fill optional fields
    msg_id    = data.message_id    or uuid.uuid4()
    timestamp = data.timestamp     or datetime.now(timezone.utc)
    receiver  = data.receiver_did

    async with transaction() as conn:
        # Resolve sender DID → UUID (NULL-safe)
        sender_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1", sender_did
        )
        sender_id = sender_row["agent_id"] if sender_row else None

        # Resolve receiver DID → UUID (required if provided)
        receiver_id = None
        if receiver:
            receiver_row = await conn.fetchrow(
                "SELECT agent_id FROM agents WHERE agent_did = $1", receiver
            )
            if receiver_row is None:
                raise ValueError(f"Receiver agent not found: {receiver}")
            receiver_id = receiver_row["agent_id"]

        row = await conn.fetchrow(
            """
            INSERT INTO agent_messages (
                sender_did,      sender_id,
                receiver_did,    receiver_id,
                content,         channel,
                metadata,
                protocol_version, acp_message_id,  acp_timestamp,
                agent_id,         acp_type,
                human_summary,    machine_payload
            )
            VALUES (
                $1,  $2,
                $3,  $4,
                $5,  $6,
                $7::jsonb,
                $8,  $9,  $10,
                $11, $12,
                $13, $14::jsonb
            )
            RETURNING
                message_id,      sender_did,       receiver_did,
                content,         channel,          status,
                metadata,        created_at,
                protocol_version, acp_message_id,  acp_timestamp,
                agent_id,         acp_type,
                human_summary,    machine_payload
            """,
            sender_did,
            sender_id,
            receiver or sender_did,   # broadcast: sender = receiver sentinel
            receiver_id,
            data.human_summary,       # legacy content column
            data.channel,
            json.dumps(data.metadata) if data.metadata else None,
            data.protocol_version,
            msg_id,
            timestamp,
            data.agent_id,
            data.type,
            data.human_summary,
            json.dumps(data.machine_payload),
        )

    message = _row_to_acp(row)

    # ── Event bus (fire-and-forget) ──────────────────────────────────────────
    try:
        await publish_event(
            EventType.AGENT_MESSAGE_SENT,
            {
                "message_id":    str(message.message_id),
                "sender_did":    sender_did,
                "receiver_did":  receiver,
                "acp_type":      data.type,
                "channel":       data.channel,
            },
            source_agent_did=sender_did,
        )
    except Exception:
        logger.warning(
            "agentbus_service: failed to publish AGENT_MESSAGE_SENT", exc_info=True
        )

    # ── Redis pub/sub for SSE (fire-and-forget) ───────────────────────────────
    try:
        redis = get_cache()
        if redis is not None and receiver:
            await redis.publish(
                _agentbus_channel(receiver),
                json.dumps(message.model_dump(mode="json")),
            )
    except Exception:
        logger.warning(
            "agentbus_service: Redis publish failed for message %s",
            message.message_id, exc_info=True,
        )

    logger.info(
        "agentbus_service: ACP message %s (%s) from %s to %s",
        message.message_id, data.type, sender_did, receiver or "BROADCAST",
    )
    return message


async def get_acp_inbox(
    agent_did: str,
    limit: int = 50,
    offset: int = 0,
    acp_type: Optional[str] = None,
    since: Optional[str] = None,
) -> list[ACPMessageResponse]:
    """
    Return ACP messages addressed to agent_did, newest first.

    Args:
        agent_did: DID of the inbox owner.
        limit:     Max messages to return (default 50).
        offset:    Messages to skip — for pagination.
        acp_type:  Filter to a specific ACP message type (optional).
        since:     ISO-8601 datetime string — return only messages after this
                   timestamp (optional).

    Returns:
        List of ACPMessageResponse objects.
    """
    clauses = ["receiver_did = $1"]
    params: list = [agent_did]
    idx = 2

    if acp_type:
        clauses.append(f"acp_type = ${idx}")
        params.append(acp_type)
        idx += 1

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            clauses.append(f"created_at > ${idx}")
            params.append(since_dt)
            idx += 1
        except ValueError:
            pass   # ignore unparseable since — return all

    where = " AND ".join(clauses)
    params.extend([limit, offset])

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                message_id,      sender_did,       receiver_did,
                content,         channel,          status,
                metadata,        created_at,
                protocol_version, acp_message_id,  acp_timestamp,
                agent_id,         acp_type,
                human_summary,    machine_payload
            FROM   agent_messages
            WHERE  {where}
            ORDER  BY created_at DESC
            LIMIT  ${idx}
            OFFSET ${idx + 1}
            """,
            *params,
        )
    return [_row_to_acp(r) for r in rows]


async def stream_messages(agent_did: str) -> AsyncGenerator[str, None]:
    """
    Async generator yielding SSE-formatted ACP message events for agent_did.

    Subscribes to Redis pub/sub channel ``agentbus:{agent_did}`` and yields
    ``data: <json>\\n\\n`` frames containing the full ACPMessageResponse JSON.

    Falls back to a single keepalive comment if Redis is unavailable.

    Args:
        agent_did: DID of the authenticated agent to stream for.

    Yields:
        SSE-formatted frames.
    """
    redis = get_cache()
    if redis is None:
        logger.warning(
            "agentbus_service: Redis unavailable — cannot stream for %s", agent_did
        )
        yield ": keepalive\n\n"
        return

    channel_key = _agentbus_channel(agent_did)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_key)
    logger.info(
        "agentbus_service: SSE stream opened for %s (channel=%s)",
        agent_did, channel_key,
    )

    try:
        async for msg in pubsub.listen():
            if msg and msg.get("type") == "message":
                yield f"data: {msg['data']}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(channel_key)
            await pubsub.aclose()
        except Exception:
            pass
        logger.info(
            "agentbus_service: SSE stream closed for %s", agent_did
        )
