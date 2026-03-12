import json

from ..cache import cache_delete, trust_score_key
from ..database import get_db, transaction

EVENT_VALUES = {
    "TASK_COMPLETED": 0.05,
    "TASK_FAILED": -0.10,
    "SERVICE_USED": 0.02,
    "MESSAGE_REPLIED": 0.01,
}


async def record_event(agent_did: str, event_type: str, metadata: dict | None = None) -> None:
    event_name = event_type.upper()
    event_value = EVENT_VALUES.get(event_name)
    if event_value is None:
        raise ValueError(f"Unsupported reputation event type: {event_type}")

    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Agent not found: {agent_did}")

        await conn.execute(
            """
            INSERT INTO trust_events (
                event_id,
                agent_id,
                agent_did,
                event_type,
                event_value,
                metadata
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $5::jsonb
            )
            """,
            agent_row["agent_id"],
            agent_did,
            event_name,
            event_value,
            json.dumps(metadata or {}),
        )

    await update_trust_score(agent_did)


async def update_trust_score(agent_did: str) -> float:
    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(a.trust_score, 0.0) AS current_score,
                COALESCE((
                    SELECT te.event_value
                    FROM trust_events te
                    WHERE te.agent_did = a.agent_did
                    ORDER BY te.created_at DESC
                    LIMIT 1
                ), 0.0) AS total_delta
            FROM agents a
            WHERE a.agent_did = $1
            """,
            agent_did,
        )
        if row is None:
            raise ValueError(f"Agent not found: {agent_did}")

        new_score = max(0.0, min(1.0, float(row["current_score"]) + float(row["total_delta"])))

        await conn.execute(
            """
            UPDATE agents
            SET trust_score = $1, updated_at = CURRENT_TIMESTAMP
            WHERE agent_did = $2
            """,
            round(new_score, 2),
            agent_did,
        )

    await cache_delete(trust_score_key(agent_did))
    return round(new_score, 2)
