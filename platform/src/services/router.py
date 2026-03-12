from ..cache import cache_get, cache_set
from ..database import get_db

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
