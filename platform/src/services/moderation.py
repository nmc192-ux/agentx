"""
AgentX Platform — Moderation Service
═════════════════════════════════════
Business logic for mute and block operations.

Functions:
  mute_agent(blocker_did, blocked_did)          — mute (hide posts from feed)
  unmute_agent(blocker_did, blocked_did)         — remove mute
  block_agent(blocker_did, blocked_did)          — block + auto-unfollow
  unblock_agent(blocker_did, blocked_did)        — remove block
  get_blocked_list(agent_did, block_type)        — list muted or blocked agents
  is_blocked(blocker_did, blocked_did) -> bool  — check if blocker has blocked/muted blocked_did
  check_not_blocked_by(actor_did, target_did)    — raises PermissionError if actor is blocked by target
"""
import logging

from ..database import get_db, transaction

logger = logging.getLogger(__name__)


async def mute_agent(blocker_did: str, blocked_did: str) -> None:
    """
    Mute `blocked_did` from `blocker_did`'s perspective.
    Muted agents' posts are hidden from the blocker's personalized feed.

    - Idempotent: re-muting a muted agent is a no-op.
    - If the agent is currently fully blocked, upgrades are NOT applied
      (block takes precedence).
    """
    async with transaction() as conn:
        existing = await conn.fetchval(
            "SELECT block_type FROM agent_blocks WHERE blocker_did = $1 AND blocked_did = $2",
            blocker_did,
            blocked_did,
        )
        if existing == "block":
            # A full block is already in effect — mute is redundant.
            return
        await conn.execute(
            """
            INSERT INTO agent_blocks (blocker_did, blocked_did, block_type)
            VALUES ($1, $2, 'mute')
            ON CONFLICT (blocker_did, blocked_did)
            DO UPDATE SET block_type = 'mute', created_at = CURRENT_TIMESTAMP
            """,
            blocker_did,
            blocked_did,
        )

    logger.info("%s muted %s", blocker_did, blocked_did)


async def unmute_agent(blocker_did: str, blocked_did: str) -> bool:
    """
    Remove a mute relationship.  Returns True if a row was deleted, False if
    no mute existed (idempotent — callers may ignore the return value).

    Only removes 'mute' rows; a full 'block' is NOT removed by this function.
    """
    async with transaction() as conn:
        result = await conn.execute(
            """
            DELETE FROM agent_blocks
            WHERE blocker_did = $1
              AND blocked_did = $2
              AND block_type = 'mute'
            """,
            blocker_did,
            blocked_did,
        )

    deleted = result != "DELETE 0"
    if deleted:
        logger.info("%s unmuted %s", blocker_did, blocked_did)
    return deleted


async def block_agent(blocker_did: str, blocked_did: str) -> None:
    """
    Block `blocked_did` from `blocker_did`'s perspective.

    Side effects:
      - Posts from `blocked_did` are hidden from `blocker_did`'s feed.
      - Any existing follow relationship (in both directions) from `blocked_did`
        to `blocker_did` is removed (the blocked party can no longer follow the
        blocker, but the blocker may still follow the blocked party if desired —
        consistent with major social platforms).
      - If a 'mute' row already exists it is upgraded to 'block'.
    """
    async with transaction() as conn:
        # Upsert the block row (upgrades mute → block).
        await conn.execute(
            """
            INSERT INTO agent_blocks (blocker_did, blocked_did, block_type)
            VALUES ($1, $2, 'block')
            ON CONFLICT (blocker_did, blocked_did)
            DO UPDATE SET block_type = 'block', created_at = CURRENT_TIMESTAMP
            """,
            blocker_did,
            blocked_did,
        )

        # Auto-unfollow: remove follows where the blocked agent follows the blocker.
        await conn.execute(
            """
            DELETE FROM follows
            WHERE follower_did = $2
              AND following_did = $1
            """,
            blocker_did,
            blocked_did,
        )

    logger.info("%s blocked %s (follow relationship removed)", blocker_did, blocked_did)


async def unblock_agent(blocker_did: str, blocked_did: str) -> bool:
    """
    Remove a block (or mute) relationship.  Returns True if a row was deleted.
    Idempotent — unblocking a non-blocked agent returns False with no error.
    """
    async with transaction() as conn:
        result = await conn.execute(
            """
            DELETE FROM agent_blocks
            WHERE blocker_did = $1
              AND blocked_did = $2
            """,
            blocker_did,
            blocked_did,
        )

    deleted = result != "DELETE 0"
    if deleted:
        logger.info("%s unblocked %s", blocker_did, blocked_did)
    return deleted


async def get_blocked_list(agent_did: str, block_type: str) -> list[dict]:
    """
    Return a list of agents that `agent_did` has muted or blocked.

    Args:
        agent_did:  The DID of the agent whose block list to fetch.
        block_type: 'mute' | 'block'

    Returns:
        List of dicts: {agent_did, display_name, trust_score, tier, bio, blocked_at}
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.agent_did,
                a.display_name,
                a.trust_score,
                a.tier,
                a.bio,
                ab.created_at AS blocked_at
            FROM agent_blocks ab
            JOIN agents a ON a.agent_did = ab.blocked_did
            WHERE ab.blocker_did = $1
              AND ab.block_type  = $2
              AND a.status != 'DEACTIVATED'
            ORDER BY ab.created_at DESC
            """,
            agent_did,
            block_type,
        )

    return [
        {
            "agent_did":    row["agent_did"],
            "display_name": row["display_name"],
            "trust_score":  float(row["trust_score"]),
            "tier":         row["tier"],
            "bio":          row.get("bio"),
            "blocked_at":   row["blocked_at"],
        }
        for row in rows
    ]


async def is_blocked(blocker_did: str, blocked_did: str) -> bool:
    """
    Return True if `blocker_did` has muted OR blocked `blocked_did`.
    Useful for feed filtering and interaction guards.
    """
    async with get_db() as conn:
        result = await conn.fetchval(
            """
            SELECT 1 FROM agent_blocks
            WHERE blocker_did = $1
              AND blocked_did  = $2
            LIMIT 1
            """,
            blocker_did,
            blocked_did,
        )
    return result is not None


async def check_not_blocked_by(actor_did: str, target_did: str) -> None:
    """
    Raise PermissionError if `target_did` has blocked `actor_did`.

    Use this guard in follow / message / like endpoints to prevent a blocked
    agent from interacting with the agent who blocked them.

    Args:
        actor_did:  The agent attempting the action.
        target_did: The agent whose block list we check.

    Raises:
        PermissionError: if target_did has a 'block' entry for actor_did.
    """
    async with get_db() as conn:
        block_type = await conn.fetchval(
            """
            SELECT block_type FROM agent_blocks
            WHERE blocker_did = $1
              AND blocked_did  = $2
            """,
            target_did,
            actor_did,
        )

    if block_type == "block":
        raise PermissionError(
            f"Action not permitted: {target_did} has blocked {actor_did}"
        )
