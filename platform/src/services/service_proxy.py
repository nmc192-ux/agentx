"""
AgentX Platform — Service Invocation Proxy
═══════════════════════════════════════════
Enables agents to call each other's registered services.

Core functions:
  invoke_service()        — caller requests a service; creates pending invocation
  complete_invocation()   — provider marks invocation completed with result
  list_invocations()      — list invocations by caller or provider role
"""
from __future__ import annotations

import json
from uuid import UUID

from ..database import get_db, transaction
from ..services.events import emit_event
from ..services.reputation import record_event


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _row_to_invocation(row) -> dict:
    return {
        "invocation_id": str(row["invocation_id"]),
        "service_id": str(row["service_id"]),
        "caller_did": row["caller_did"],
        "provider_did": row["provider_did"],
        "payload": _decode_json(row.get("payload")),
        "result": _decode_json(row.get("result")) if row.get("result") is not None else None,
        "status": row["status"],
        "price": row["price"],
        "token_type": row["token_type"],
        "created_at": row["created_at"].isoformat(),
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
    }


# ── Service Functions ──────────────────────────────────────────────────────────

async def invoke_service(
    caller_did: str,
    service_id: UUID,
    payload: dict,
) -> dict:
    """
    Caller requests a service invocation.

    Steps:
      1. Look up service by ID and verify it is active.
      2. Verify caller has sufficient balance if the service has a price.
      3. Create a service_invocations record with status 'pending'.
      4. Record SERVICE_USED trust event for the service provider.
      5. Emit SERVICE_INVOKED WebSocket event.
      6. Return the invocation record.

    Actual execution is async — the provider's agent polls for pending invocations.
    """
    async with transaction() as conn:
        # 1. Look up the service
        service_row = await conn.fetchrow(
            """
            SELECT service_id, agent_did, service_name, is_active, price, pricing_model
            FROM services
            WHERE service_id = $1
            """,
            service_id,
        )
        if service_row is None:
            raise ValueError(f"Service not found: {service_id}")
        if not service_row["is_active"]:
            raise ValueError(f"Service is not active: {service_id}")

        provider_did = service_row["agent_did"]
        service_price = int(service_row["price"]) if service_row.get("price") is not None else 0
        token_type = "WORK"

        # 2. Verify caller has sufficient balance (only if service has a price)
        if service_price > 0:
            balance_row = await conn.fetchrow(
                """
                SELECT balance
                FROM token_balances
                WHERE agent_did = $1 AND token_type = $2::token_type
                """,
                caller_did,
                token_type,
            )
            current_balance = int(balance_row["balance"]) if balance_row else 0
            if current_balance < service_price:
                raise ValueError(
                    f"Insufficient {token_type} balance: "
                    f"{caller_did} has {current_balance}, needs {service_price}"
                )

        # 3. Create the invocation record
        row = await conn.fetchrow(
            """
            INSERT INTO service_invocations (
                invocation_id,
                service_id,
                caller_did,
                provider_did,
                payload,
                status,
                price,
                token_type
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4::jsonb,
                'pending',
                $5,
                $6
            )
            RETURNING
                invocation_id,
                service_id,
                caller_did,
                provider_did,
                payload,
                result,
                status,
                price,
                token_type,
                created_at,
                completed_at
            """,
            service_id,
            caller_did,
            provider_did,
            json.dumps(payload or {}),
            service_price,
            token_type,
        )

    invocation = _row_to_invocation(dict(row))

    # 4. Record trust event for provider (outside transaction to avoid nested locks)
    try:
        await record_event(
            provider_did,
            "service_used",
            {
                "invocation_id": invocation["invocation_id"],
                "service_id": str(service_id),
                "caller_did": caller_did,
            },
        )
    except Exception:
        # Trust events are best-effort — do not fail the invocation
        pass

    # 5. Emit WebSocket event
    await emit_event(
        "SERVICE_INVOKED",
        caller_did,
        {
            "invocation_id": invocation["invocation_id"],
            "service_id": str(service_id),
            "provider_did": provider_did,
            "caller_did": caller_did,
        },
    )

    return invocation


async def complete_invocation(
    invocation_id: UUID,
    provider_did: str,
    result: dict,
) -> dict:
    """
    Provider completes a pending invocation with a result payload.

    Only the service provider (matched by provider_did) may complete their own
    invocations. Updates status to 'completed' and records the result.
    """
    async with transaction() as conn:
        # Fetch the invocation and verify ownership
        inv_row = await conn.fetchrow(
            """
            SELECT invocation_id, service_id, caller_did, provider_did, status
            FROM service_invocations
            WHERE invocation_id = $1
            """,
            invocation_id,
        )
        if inv_row is None:
            raise ValueError(f"Invocation not found: {invocation_id}")
        if inv_row["provider_did"] != provider_did:
            raise PermissionError(
                "Only the service provider can complete this invocation"
            )
        if inv_row["status"] not in ("pending", "in_progress"):
            raise ValueError(
                f"Invocation cannot be completed (status={inv_row['status']})"
            )

        # Update the invocation with result and mark completed
        updated_row = await conn.fetchrow(
            """
            UPDATE service_invocations
            SET
                result       = $2::jsonb,
                status       = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE invocation_id = $1
            RETURNING
                invocation_id,
                service_id,
                caller_did,
                provider_did,
                payload,
                result,
                status,
                price,
                token_type,
                created_at,
                completed_at
            """,
            invocation_id,
            json.dumps(result or {}),
        )

    invocation = _row_to_invocation(dict(updated_row))

    # Record trust event for the provider (outside transaction)
    try:
        await record_event(
            provider_did,
            "task_completed",
            {
                "invocation_id": str(invocation_id),
                "service_id": invocation["service_id"],
            },
        )
    except Exception:
        pass

    # Emit completion event
    await emit_event(
        "SERVICE_INVOCATION_COMPLETED",
        provider_did,
        {
            "invocation_id": str(invocation_id),
            "service_id": invocation["service_id"],
            "caller_did": invocation["caller_did"],
            "provider_did": provider_did,
        },
    )

    return invocation


async def list_invocations(
    agent_did: str,
    role: str = "both",
) -> list[dict]:
    """
    List service invocations for the given agent.

    role:
      "caller"   — invocations where this agent is the caller
      "provider" — invocations where this agent is the provider
      "both"     — all invocations where agent is caller or provider
    """
    conditions: list[str] = []
    params: list[object] = [agent_did]

    if role == "caller":
        conditions.append("caller_did = $1")
    elif role == "provider":
        conditions.append("provider_did = $1")
    else:
        # both
        conditions.append("(caller_did = $1 OR provider_did = $1)")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                invocation_id,
                service_id,
                caller_did,
                provider_did,
                payload,
                result,
                status,
                price,
                token_type,
                created_at,
                completed_at
            FROM service_invocations
            WHERE {where}
            ORDER BY created_at DESC
            """,
            *params,
        )

    return [_row_to_invocation(dict(row)) for row in rows]
