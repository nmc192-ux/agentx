"""
AgentX Platform — Agent Bus Service
═════════════════════════════════════
Phase 11: Direct agent-to-agent messaging with channel support,
inbox querying, and real-time SSE streaming via Redis pub/sub.

Public API
──────────
  send_message(sender_did, data)            → AgentMessageResponse
  get_inbox(agent_did, limit, offset)       → list[AgentMessageResponse]
  stream_messages(agent_did)                → AsyncGenerator[str, None]

Design notes
────────────
• sender_did is resolved to sender_id inside the write transaction (same
  DID→UUID pattern used by governance and contract services).
• receiver_did is resolved to receiver_id for FK integrity (NULL-safe:
  if the receiver DID is unknown the message is still stored).
• After DB insert, the message is published to a Redis pub/sub channel
  keyed agentbus:{receiver_did} so that any active SSE stream for that
  agent receives the event in real-time.
• stream_messages() is an async generator suitable for FastAPI
  StreamingResponse. It subscribes to the Redis channel for the caller's
  DID and yields 'data: <json>\\n\\n' SSE payloads.
• Events are fire-and-forget; Redis publish failures are logged but never
  bubble up.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional

from ..cache import get_cache
from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.agentbus import AgentMessageCreate, AgentMessageResponse

logger = logging.getLogger(__name__)

# Redis pub/sub channel prefix for agentbus messages
_AGENTBUS_CHANNEL_PREFIX = "agentbus:"


def _agentbus_channel(agent_did: str) -> str:
    """Return the Redis pub/sub channel key for an agent's inbox."""
    return f"{_AGENTBUS_CHANNEL_PREFIX}{agent_did}"


def _row_to_message(row) -> AgentMessageResponse:
    payload = row.get("metadata")
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else None
    elif payload is not None:
        payload = dict(payload)
    return AgentMessageResponse(
        message_id=row["message_id"],
        sender_did=row["sender_did"],
        receiver_did=row["receiver_did"],
        content=row["content"],
        channel=row["channel"],
        status=row["status"],
        metadata=payload,
        created_at=row["created_at"],
    )


# ── Service functions ──────────────────────────────────────────────────────────

async def send_message(
    sender_did: str,
    data: AgentMessageCreate,
) -> AgentMessageResponse:
    """
    Send a direct message from sender_did to data.receiver_did.

    Inserts the message into agent_messages, publishes an
    AGENT_MESSAGE_SENT event to the Redis stream, and publishes to the
    per-agent Redis pub/sub channel for real-time delivery.

    Args:
        sender_did: DID of the authenticated sender.
        data:       Validated AgentMessageCreate payload.

    Returns:
        AgentMessageResponse for the stored message.

    Raises:
        ValueError: If receiver_did is not a registered agent.
    """
    async with transaction() as conn:
        # Resolve sender DID → agent_id (NULL-safe)
        sender_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            sender_did,
        )
        sender_id = sender_row["agent_id"] if sender_row else None

        # Resolve receiver DID → agent_id (required — must exist)
        receiver_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            data.receiver_did,
        )
        if receiver_row is None:
            raise ValueError(f"Receiver agent not found: {data.receiver_did}")
        receiver_id = receiver_row["agent_id"]

        row = await conn.fetchrow(
            """
            INSERT INTO agent_messages
                (sender_did, sender_id, receiver_did, receiver_id,
                 content, channel, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            RETURNING
                message_id, sender_did, receiver_did, content,
                channel, status, metadata, created_at
            """,
            sender_did,
            sender_id,
            data.receiver_did,
            receiver_id,
            data.content,
            data.channel,
            json.dumps(data.metadata) if data.metadata else None,
        )

    message = _row_to_message(row)

    # ── Publish AGENT_MESSAGE_SENT event (fire-and-forget) ──────────────────
    try:
        await publish_event(
            EventType.AGENT_MESSAGE_SENT,
            {
                "message_id":   str(message.message_id),
                "sender_did":   sender_did,
                "receiver_did": data.receiver_did,
                "channel":      data.channel,
            },
            source_agent_did=sender_did,
        )
    except Exception:
        logger.warning(
            "agentbus_service: failed to publish AGENT_MESSAGE_SENT", exc_info=True
        )

    # ── Publish to Redis pub/sub for SSE streaming (fire-and-forget) ─────────
    try:
        redis = get_cache()
        if redis is not None:
            await redis.publish(
                _agentbus_channel(data.receiver_did),
                json.dumps(message.model_dump(mode="json")),
            )
    except Exception:
        logger.warning(
            "agentbus_service: Redis publish failed for message %s",
            message.message_id, exc_info=True,
        )

    logger.info(
        "agentbus_service: message %s sent from %s to %s (channel=%s)",
        message.message_id, sender_did, data.receiver_did, data.channel,
    )
    return message


async def get_inbox(
    agent_did: str,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentMessageResponse]:
    """
    Return messages addressed to agent_did, newest first.

    Args:
        agent_did: DID of the inbox owner.
        limit:     Maximum number of messages to return (default 50).
        offset:    Number of messages to skip (for pagination, default 0).

    Returns:
        List of AgentMessageResponse objects ordered by created_at DESC.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT message_id, sender_did, receiver_did, content,
                   channel, status, metadata, created_at
            FROM   agent_messages
            WHERE  receiver_did = $1
            ORDER  BY created_at DESC
            LIMIT  $2
            OFFSET $3
            """,
            agent_did,
            limit,
            offset,
        )
    return [_row_to_message(r) for r in rows]


async def stream_messages(agent_did: str) -> AsyncGenerator[str, None]:
    """
    Async generator yielding SSE-formatted events for messages sent to
    agent_did.  Subscribes to the Redis pub/sub channel
    ``agentbus:{agent_did}`` and yields ``data: <json>\\n\\n`` frames.

    When Redis is unavailable a single keepalive comment is yielded and
    the generator exits immediately — this prevents a hung HTTP response.

    Args:
        agent_did: DID of the authenticated agent whose inbox to stream.

    Yields:
        SSE-formatted string frames (``data: ...\\n\\n`` or ``: keepalive\\n\\n``).
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
