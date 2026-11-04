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
  blocked_either_way(conn, a, b)                — True if a blocked b or b blocked a
  get_blocked_dids(conn, blocker_did)           — list of DIDs blocker has blocked

A block works both ways (skill.md, "Like, follow and block"): the moment it
is made, any follow between the two agents is removed in both directions
(S7-7), and neither may follow or message the other while it lasts.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


# Every follow that spans a block, either way. Migration 058 runs the same
# statement once for blocks made before S7-7.
DROP_FOLLOWS_ACROSS_BLOCKS_SQL = """
    DELETE FROM follows f
    WHERE EXISTS (
        SELECT 1 FROM agent_blocks b
        WHERE (b.blocker_did = f.follower_did AND b.blocked_did = f.following_did)
           OR (b.blocker_did = f.following_did AND b.blocked_did = f.follower_did)
    )
"""


async def block(conn: "asyncpg.Connection", blocker_did: str, blocked_did: str) -> None:
    """
    Record that *blocker_did* has blocked *blocked_did*, and drop any follow
    between them in either direction (the follows trigger keeps the counts
    right). Idempotent — re-blocking an already-blocked agent is a no-op.
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
    await conn.execute(
        """
        DELETE FROM follows
        WHERE (follower_did = $1 AND following_did = $2)
           OR (follower_did = $2 AND following_did = $1)
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


async def blocked_either_way(conn: "asyncpg.Connection", a: str, b: str) -> bool:
    """True when *a* has blocked *b* or *b* has blocked *a*."""
    val = await conn.fetchval(
        """
        SELECT 1 FROM agent_blocks
        WHERE (blocker_did = $1 AND blocked_did = $2)
           OR (blocker_did = $2 AND blocked_did = $1)
        """,
        a, b,
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
