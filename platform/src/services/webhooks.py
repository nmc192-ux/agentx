"""
AgentX Platform — Webhook Service
══════════════════════════════════
Phase 5: Push-based event delivery

Webhook delivery:
  1. Agent registers a webhook URL + event filter
  2. On each emit_event(), matching webhooks are queued
  3. Background delivery with HMAC-SHA256 signature verification
  4. Auto-disable after 10 consecutive failures

Signature header (X-AgentX-Signature):
  HMAC-SHA256(webhook_secret, request_body)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from uuid import UUID

from ..database import get_db, transaction

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_LENGTH = 32
MAX_FAILURE_COUNT = 10


async def create_webhook(
    agent_did: str,
    callback_url: str,
    name: str = "default",
    event_types: list[str] | None = None,
) -> dict:
    """Register a new webhook endpoint for an agent."""
    secret = secrets.token_urlsafe(WEBHOOK_SECRET_LENGTH)
    events = event_types or ["*"]

    async with transaction() as conn:
        agent_exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1", agent_did,
        )
        if not agent_exists:
            raise ValueError(f"Agent not found: {agent_did}")

        row = await conn.fetchrow(
            """
            INSERT INTO webhooks (agent_did, name, callback_url, secret, event_types)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING webhook_id, name, callback_url, event_types,
                      is_active, failure_count, last_triggered_at, created_at
            """,
            agent_did, name, callback_url, secret, events,
        )

    result = _row_to_response(dict(row))
    result["secret"] = secret  # Show once on creation
    return result


async def list_webhooks(agent_did: str) -> list[dict]:
    """List all webhooks for an agent."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT webhook_id, name, callback_url, event_types,
                   is_active, failure_count, last_triggered_at, created_at
            FROM webhooks
            WHERE agent_did = $1
            ORDER BY created_at DESC
            """,
            agent_did,
        )
    return [_row_to_response(dict(r)) for r in rows]


async def update_webhook(
    webhook_id: UUID,
    agent_did: str,
    callback_url: str | None = None,
    event_types: list[str] | None = None,
    is_active: bool | None = None,
) -> dict:
    """Update webhook configuration."""
    updates = []
    params: list = []

    if callback_url is not None:
        params.append(callback_url)
        updates.append(f"callback_url = ${len(params)}")

    if event_types is not None:
        params.append(event_types)
        updates.append(f"event_types = ${len(params)}")

    if is_active is not None:
        params.append(is_active)
        updates.append(f"is_active = ${len(params)}")
        if is_active:
            updates.append("failure_count = 0")  # Reset on re-enable

    if not updates:
        raise ValueError("No fields to update")

    params.append(webhook_id)
    params.append(agent_did)

    async with transaction() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE webhooks
            SET {', '.join(updates)}
            WHERE webhook_id = ${len(params) - 1} AND agent_did = ${len(params)}
            RETURNING webhook_id, name, callback_url, event_types,
                      is_active, failure_count, last_triggered_at, created_at
            """,
            *params,
        )
    if row is None:
        raise ValueError(f"Webhook not found: {webhook_id}")
    return _row_to_response(dict(row))


async def delete_webhook(webhook_id: UUID, agent_did: str) -> dict:
    """Delete a webhook."""
    async with transaction() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM webhooks WHERE webhook_id = $1 AND agent_did = $2 RETURNING webhook_id",
            webhook_id, agent_did,
        )
    if deleted is None:
        raise ValueError(f"Webhook not found: {webhook_id}")
    return {"webhook_id": str(webhook_id), "deleted": True}


async def queue_webhook_deliveries(event_id: UUID, event_type: str, agent_did: str | None) -> int:
    """
    Queue webhook deliveries for an event.
    Called from emit_event() after the event is stored.

    Matches webhooks where:
      - event_types contains '*' (wildcard) OR the specific event_type
      - webhook is active and not failed-out
      - webhook belongs to the event's agent OR is a wildcard subscriber
    """
    async with transaction() as conn:
        # Find matching webhooks
        rows = await conn.fetch(
            """
            SELECT webhook_id
            FROM webhooks
            WHERE is_active = TRUE
              AND failure_count < $1
              AND ($2::text IS NULL OR agent_did = $2 OR '*' = ANY(event_types))
              AND ('*' = ANY(event_types) OR $3 = ANY(event_types))
            """,
            MAX_FAILURE_COUNT,
            agent_did,
            event_type,
        )

        queued = 0
        for row in rows:
            await conn.execute(
                """
                INSERT INTO webhook_deliveries (webhook_id, event_id, event_type, status)
                VALUES ($1, $2, $3, 'pending')
                """,
                row["webhook_id"], event_id, event_type,
            )
            queued += 1

    return queued


def compute_signature(secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def process_pending_deliveries(batch_size: int = 50) -> dict:
    """
    Process pending webhook deliveries.
    Called by a background worker or cron job.

    For each pending delivery:
      1. Fetch the webhook secret and callback URL
      2. Build the payload from the event
      3. POST to callback URL with HMAC signature
      4. Record result (delivered/failed)
      5. Increment failure_count on webhook if failed
    """
    import httpx

    async with get_db() as conn:
        deliveries = await conn.fetch(
            """
            SELECT
                d.delivery_id, d.webhook_id, d.event_id, d.event_type,
                w.callback_url, w.secret, w.agent_did,
                e.payload AS event_payload, e.created_at AS event_created_at
            FROM webhook_deliveries d
            JOIN webhooks w ON w.webhook_id = d.webhook_id
            JOIN events e ON e.event_id = d.event_id
            WHERE d.status = 'pending'
            ORDER BY d.created_at ASC
            LIMIT $1
            """,
            batch_size,
        )

    delivered = 0
    failed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for delivery in deliveries:
            body_dict = {
                "event_id": str(delivery["event_id"]),
                "event_type": delivery["event_type"],
                "agent_did": delivery["agent_did"],
                "payload": json.loads(delivery["event_payload"])
                    if isinstance(delivery["event_payload"], str)
                    else (delivery["event_payload"] or {}),
                "timestamp": delivery["event_created_at"].isoformat(),
            }
            body_bytes = json.dumps(body_dict).encode()
            signature = compute_signature(delivery["secret"], body_bytes)

            try:
                resp = await client.post(
                    delivery["callback_url"],
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-AgentX-Signature": signature,
                        "X-AgentX-Event": delivery["event_type"],
                    },
                )
                response_code = resp.status_code
                is_success = 200 <= response_code < 300
            except Exception as exc:
                logger.warning("Webhook delivery failed: %s → %s", delivery["delivery_id"], exc)
                response_code = None
                is_success = False

            async with transaction() as conn:
                await conn.execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = $2, response_code = $3,
                        attempt_count = attempt_count + 1,
                        last_attempt = CURRENT_TIMESTAMP
                    WHERE delivery_id = $1
                    """,
                    delivery["delivery_id"],
                    "delivered" if is_success else "failed",
                    response_code,
                )

                if is_success:
                    await conn.execute(
                        """
                        UPDATE webhooks
                        SET last_triggered_at = CURRENT_TIMESTAMP, failure_count = 0
                        WHERE webhook_id = $1
                        """,
                        delivery["webhook_id"],
                    )
                    delivered += 1
                else:
                    await conn.execute(
                        """
                        UPDATE webhooks
                        SET failure_count = failure_count + 1
                        WHERE webhook_id = $1
                        """,
                        delivery["webhook_id"],
                    )
                    failed += 1

    return {"delivered": delivered, "failed": failed, "total": len(deliveries)}


def _row_to_response(row: dict) -> dict:
    return {
        "webhook_id": row["webhook_id"],
        "name": row.get("name", "default"),
        "callback_url": row["callback_url"],
        "event_types": list(row.get("event_types", [])),
        "is_active": row.get("is_active", True),
        "failure_count": row.get("failure_count", 0),
        "last_triggered_at": row.get("last_triggered_at"),
        "created_at": row["created_at"],
    }
