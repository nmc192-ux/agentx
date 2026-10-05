"""
AgentX Platform — Storing direct messages
══════════════════════════════════════════
The INSERT behind POST /messages/send, shared with the founder heartbeat
(S10-5) so both write the same row in whichever table shape the database has.
Checks (identity, block, limits) stay with the callers.
"""
from __future__ import annotations

import json

__all__ = ["RETURNING", "messages_key", "store_message"]

RETURNING = "message_id, sender_agent_did, receiver_agent_did, message, metadata, created_at"


def messages_key(agent_did: str) -> str:
    """The Redis key GET /messages/{did} caches an agent's messages under."""
    return f"messages:{agent_did}"


# S9-6e: `messages` exists in two shapes. The init-db.sql baseline (and, per
# the reconciliation briefing, production) is DID-only; a database built by
# migration 006 alone also has NOT NULL sender_agent_id / receiver_agent_id
# (007 adds the DID columns). The INSERT used to name the id columns always,
# so sending answered 500 on the baseline. Looked up once per process.
_legacy_id_columns: bool | None = None


async def _has_legacy_id_columns(conn) -> bool:
    global _legacy_id_columns
    if _legacy_id_columns is None:
        _legacy_id_columns = bool(await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'messages'
                  AND column_name = 'sender_agent_id'
            )
            """
        ))
    return _legacy_id_columns


async def store_message(
    conn, sender_agent_id, receiver_agent_id, sender_did: str, receiver_did: str,
    text: str, metadata: dict | None, at=None,
):
    """INSERT one message on *conn*; *at* sets created_at (the founder
    heartbeat's clock), else the database's now. Returns the row (RETURNING)."""
    if await _has_legacy_id_columns(conn):
        return await conn.fetchrow(
            f"""
            INSERT INTO messages (
                sender_agent_id, receiver_agent_id,
                sender_agent_did, receiver_agent_did, message, metadata, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, COALESCE($7::timestamptz, CURRENT_TIMESTAMP))
            RETURNING {RETURNING}
            """,
            sender_agent_id, receiver_agent_id, sender_did, receiver_did,
            text, json.dumps(metadata or {}), at,
        )
    return await conn.fetchrow(
        f"""
        INSERT INTO messages (
            sender_agent_did, receiver_agent_did, message, metadata, created_at
        )
        VALUES ($1, $2, $3, $4::jsonb, COALESCE($5::timestamptz, CURRENT_TIMESTAMP))
        RETURNING {RETURNING}
        """,
        sender_did, receiver_did, text, json.dumps(metadata or {}), at,
    )
