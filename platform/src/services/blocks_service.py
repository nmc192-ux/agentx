"""
AgentX Platform — Agent Blocks Service
════════════════════════════════════════
Pure DB-level helpers for the block/unblock social graph.

All functions accept an open asyncpg connection so they compose
cleanly inside transaction() blocks in the router.

Public API:
  block(conn, blocker_did, blocked_did)         — upsert a block row
  unblock(conn, blocker_did, blocked_did)       — delete the block row (no-op if absent)
  has_blocked(conn, blocker_did, blocked_did)   — True if blocker → blocked row exists
  get_blocked_dids(conn, blocker_did)           — list of DIDs blocker has blocked
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


async def block(conn: "asyncpg.Connection", blocker_did: str, blocked_did: str) -> None:
    """
    Record that *blocker_did* has blocked *blocked_did*.
    Idempotent — re-blocking an already-blocked agent is a no-op.
    """
    await conn.execute(
        """
        INSERT INTO agent_blocks (blocker_did, blocked_did)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        blocker_did,
        blocked_did,
    )


async def unblock(conn: "asyncpg.Connection", blocker_did: str, blocked_did: str) -> None:
    """
    Remove the block.  No-op if the row does not exist.
    """
    await conn.execute(
        "DELETE FROM agent_blocks WHERE blocker_did = $1 AND blocked_did = $2",
        blocker_did,
        blocked_did,
    )


async def has_blocked(
    conn: "asyncpg.Connection",
    blocker_did: str,
    blocked_did: str,
) -> bool:
    """
    Return True if *blocker_did* has blocked *blocked_did*.
    Used by follows / messages to gate interactions.
    """
    val = await conn.fetchval(
        """
        SELECT 1 FROM agent_blocks
        WHERE blocker_did = $1 AND blocked_did = $2
        """,
        blocker_did,
        blocked_did,
    )
    return val is not None


async def get_blocked_dids(conn: "asyncpg.Connection", blocker_did: str) -> list[str]:
    """
    Return the list of DIDs that *blocker_did* has blocked.
    """
    rows = await conn.fetch(
        "SELECT blocked_did FROM agent_blocks WHERE blocker_did = $1",
        blocker_did,
    )
    return [r["blocked_did"] for r in rows]
