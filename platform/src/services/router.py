import json

from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction

TTL_ROUTER = 60


async def select_executor(service_type: str) -> str | None:
    cache_key = f"router:{service_type}"
    cached = await cache_get(cache_key)
    if cached:
        return cached.get("agent_did")

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.agent_did
            FROM services s
            JOIN agents a ON a.agent_did = s.agent_did
            WHERE s.is_active = TRUE
              AND s.service_type = $1
              AND a.status = 'ACTIVE'
            ORDER BY a.trust_score DESC, s.created_at DESC
            LIMIT 1
            """,
            service_type,
        )

    if row is None:
        return None

    agent_did = row["agent_did"]
    await cache_set(cache_key, {"agent_did": agent_did}, ttl=TTL_ROUTER)
    return agent_did


async def create_task_record(
    requester_agent_did: str,
    executor_agent_did: str,
    task_type: str,
    payload: dict | None = None,
) -> dict:
    async with transaction() as conn:
        requester_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            requester_agent_did,
        )
        if requester_row is None:
            raise ValueError(f"Requester agent not found: {requester_agent_did}")

        executor_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            executor_agent_did,
        )
        if executor_row is None:
            raise ValueError(f"Executor agent not found: {executor_agent_did}")

        row = await conn.fetchrow(
            """
            INSERT INTO tasks (
                task_id,
                requester_agent_id,
                executor_agent_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $5,
                $6::jsonb,
                'PENDING',
                NULL
            )
            RETURNING
                task_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result,
                created_at,
                updated_at
            """,
            requester_row["agent_id"],
            executor_row["agent_id"],
            requester_agent_did,
            executor_agent_did,
            task_type,
            json.dumps(payload or {}),
        )

    await cache_delete(f"tasks:{requester_agent_did}")
    await cache_delete(f"tasks:{executor_agent_did}")
    return dict(row)


async def create_routed_task(
    requester_agent_did: str,
    task_type: str,
    payload: dict | None = None,
) -> dict | None:
    executor_agent_did = await select_executor(task_type)
    if executor_agent_did is None:
        return None
    return await create_task_record(
        requester_agent_did=requester_agent_did,
        executor_agent_did=executor_agent_did,
        task_type=task_type,
        payload=payload,
    )
