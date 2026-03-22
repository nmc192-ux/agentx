"""
AgentX Platform — Agent Memory Service
════════════════════════════════════════
CRUD operations for the server-side key-value memory store.

All writes use INSERT … ON CONFLICT DO UPDATE (upsert) so callers never need
to distinguish between create and update.

Database:
  Table: agent_memory
  Unique: (agent_did, key)

Methods:
  save(agent_did, key, value) -> MemoryEntry        — upsert
  load(agent_did, key)        -> MemoryEntry | None — fetch one
  list_keys(agent_did)        -> list[str]          — all keys for agent
  delete(agent_did, key)      -> bool               — True if row existed
  clear(agent_did)            -> int                — count of rows deleted
"""
import json
import logging
from typing import Optional

from ..database import get_db, transaction
from ..models.memory import MemoryEntry

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_entry(row) -> MemoryEntry:
    # asyncpg returns JSONB columns as raw JSON text strings, not parsed Python
    # objects.  We must json.loads() the value so the MemoryEntry holds the
    # actual Python value (str, int, dict, list, …) rather than a JSON-encoded
    # string like '"my-value"'.
    raw = row["value"]
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw   # fallback — keep as-is if not valid JSON
    else:
        value = raw   # asyncpg already parsed it (e.g., dict for complex JSONB)

    return MemoryEntry(
        memory_id  = str(row["memory_id"]),
        agent_did  = row["agent_did"],
        key        = row["key"],
        value      = value,
        created_at = row["created_at"],
        updated_at = row["updated_at"],
    )


# ── Public API ─────────────────────────────────────────────────────────────────

async def save(agent_did: str, key: str, value) -> MemoryEntry:
    """
    Upsert a memory entry for the given agent and key.

    If the key already exists, its value and updated_at are overwritten.
    Returns the resulting MemoryEntry.
    """
    # Serialise value to a JSON string so asyncpg can bind it as JSONB.
    json_value = json.dumps(value)

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_memory (agent_did, key, value)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (agent_did, key) DO UPDATE
                SET value      = EXCLUDED.value,
                    updated_at = now()
            RETURNING memory_id, agent_did, key, value, created_at, updated_at
            """,
            agent_did,
            key,
            json_value,
        )

    logger.debug("Memory saved: agent=%s key=%s", agent_did, key)
    return _row_to_entry(row)


async def load(agent_did: str, key: str) -> Optional[MemoryEntry]:
    """
    Fetch a single memory entry by (agent_did, key).

    Returns None if the key does not exist for the agent.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT memory_id, agent_did, key, value, created_at, updated_at
            FROM   agent_memory
            WHERE  agent_did = $1 AND key = $2
            """,
            agent_did,
            key,
        )

    if row is None:
        return None

    return _row_to_entry(row)


async def list_keys(agent_did: str) -> list[str]:
    """
    Return all keys stored for the given agent, ordered alphabetically.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT key
            FROM   agent_memory
            WHERE  agent_did = $1
            ORDER  BY key
            """,
            agent_did,
        )

    return [r["key"] for r in rows]


async def delete(agent_did: str, key: str) -> bool:
    """
    Delete a single memory entry.

    Returns True if the row existed and was deleted, False otherwise.
    """
    async with transaction() as conn:
        result = await conn.execute(
            "DELETE FROM agent_memory WHERE agent_did = $1 AND key = $2",
            agent_did,
            key,
        )

    deleted = result != "DELETE 0"
    if deleted:
        logger.debug("Memory deleted: agent=%s key=%s", agent_did, key)
    return deleted


async def clear(agent_did: str) -> int:
    """
    Delete ALL memory entries for the given agent.

    Returns the number of rows deleted.
    """
    async with transaction() as conn:
        result = await conn.execute(
            "DELETE FROM agent_memory WHERE agent_did = $1",
            agent_did,
        )

    # asyncpg returns "DELETE N" as a string
    count = int(result.split()[-1])
    logger.info("Memory cleared: agent=%s rows=%d", agent_did, count)
    return count
