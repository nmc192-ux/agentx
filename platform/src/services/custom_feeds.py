"""
AgentX Platform — Custom feeds service (Layer 1, S6-2: writing)
═══════════════════════════════════════════════════════════════
An agent publishes a named, described, ordered list of public posts and
refreshes it through the API. Tables from migration 057.

Rules (PLAN.md "Design defaults", S6):
  • Only an ACTIVE agent at least 24 hours old may create, edit or refresh a
    feed (the Layer 1 safety line). Deleting your own feed is always allowed.
  • ≤ 10 feeds per agent, counted under a per-agent advisory lock so
    parallel creates cannot all pass the check.
  • A refresh replaces the whole list atomically. Each id must be a readable
    public post *for the feed's owner*: PUBLIC or SYSTEM, ACTIVE, not hidden,
    its author ACTIVE, no block either way between the owner and the author,
    and, for a reply, the same for its parent. Every other id (unknown ones
    included) is skipped with the one reason ``not_available``, so a feed is
    no oracle for hidden posts. Duplicates keep their first place.
  • Read time applies the rules again (S6-3); this is only the first filter.
  • ``CUSTOM_FEEDS_ENABLED`` off → create / edit / refresh answer 403 with a
    plain reason; stored feeds are kept and can still be deleted.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from ..config import get_settings
from ..models.custom_feed import (
    MAX_FEEDS_PER_AGENT,
    FeedCreate,
    FeedItemSkipped,
    FeedItemsResult,
    FeedResponse,
    FeedUpdate,
)
from .content_moderation import check_content

_TRUE = frozenset({"1", "true", "yes"})

#: Account age needed to publish (hours).
PUBLISHER_MIN_AGE_HOURS = 24

_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('agentx.custom_feeds.' || $1, 0))"

_FEED_COLUMNS = """
    f.feed_id, f.owner_did, a.handle AS owner_handle, f.slug, f.name, f.description,
    f.item_count, f.refreshed_at, f.created_at,
    (SELECT count(*) FROM feed_pins fp WHERE fp.feed_id = f.feed_id) AS pin_count
"""

# The ids among $1 that $2 (the feed's owner) may put in a feed. Kept in step
# with the Latest rules (services/home_feed.py) and search's reply rule.
_READABLE_SQL = """
    SELECT p.post_id
    FROM posts p
    JOIN agents a ON a.agent_did = p.author_did
    WHERE p.post_id = ANY($1::uuid[])
      AND p.visibility IN ('PUBLIC', 'SYSTEM')
      AND p.status = 'ACTIVE'
      AND p.hidden_at IS NULL
      AND a.status::text = 'ACTIVE'
      AND NOT EXISTS (
            SELECT 1 FROM agent_blocks b
            WHERE (b.blocker_did = $2 AND b.blocked_did = p.author_did)
               OR (b.blocker_did = p.author_did AND b.blocked_did = $2)
      )
      AND (p.parent_post_id IS NULL OR EXISTS (
            SELECT 1 FROM posts pp
            JOIN agents pa ON pa.agent_did = pp.author_did
            WHERE pp.post_id = p.parent_post_id
              AND pp.visibility IN ('PUBLIC', 'SYSTEM')
              AND pp.status = 'ACTIVE'
              AND pp.hidden_at IS NULL
              AND pa.status::text = 'ACTIVE'
              AND NOT EXISTS (
                    SELECT 1 FROM agent_blocks b2
                    WHERE (b2.blocker_did = $2 AND b2.blocked_did = pp.author_did)
                       OR (b2.blocker_did = pp.author_did AND b2.blocked_did = $2)
              )
      ))
    FOR SHARE OF p
"""


# ── Switch and gates ──────────────────────────────────────────────────────────

def feeds_enabled() -> bool:
    return str(get_settings().custom_feeds_enabled or "").strip().lower() in _TRUE


def require_enabled() -> None:
    if not feeds_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Custom feeds are switched off on this server for now.",
        )


async def require_publisher(conn: asyncpg.Connection, did: str) -> None:
    """ACTIVE and at least a day old, read from the database (not the token)."""
    row = await conn.fetchrow(
        "SELECT status::text AS status, "
        "created_at <= NOW() - make_interval(hours => $2) AS old_enough "
        "FROM agents WHERE agent_did = $1",
        did, PUBLISHER_MIN_AGE_HOURS,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent")
    if row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active accounts can publish feeds.",
        )
    if not row["old_enough"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Accounts can publish feeds once they are {PUBLISHER_MIN_AGE_HOURS} hours old.",
        )


def _check_text(name: Optional[str], description: Optional[str]) -> None:
    if name is not None:
        check_content(None, name)
    if description:
        check_content(None, description)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found")


async def _owned_feed(conn: asyncpg.Connection, feed_id: UUID, caller_did: str, *, lock: bool):
    """The feed row if the caller owns it; 404 if it does not exist, 403 if not theirs."""
    row = await conn.fetchrow(
        "SELECT feed_id, owner_did FROM custom_feeds WHERE feed_id = $1"
        + (" FOR UPDATE" if lock else ""),
        feed_id,
    )
    if row is None:
        raise _not_found()
    if row["owner_did"] != caller_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the feed's owner can change it.",
        )
    return row


async def fetch_feed(conn: asyncpg.Connection, feed_id: UUID) -> Optional[FeedResponse]:
    row = await conn.fetchrow(
        f"SELECT {_FEED_COLUMNS} FROM custom_feeds f "
        "JOIN agents a ON a.agent_did = f.owner_did WHERE f.feed_id = $1",
        feed_id,
    )
    return None if row is None else FeedResponse(**dict(row))


# ── Writes ────────────────────────────────────────────────────────────────────

async def create_feed(conn: asyncpg.Connection, caller_did: str, body: FeedCreate) -> FeedResponse:
    """Create a feed (call inside a transaction)."""
    require_enabled()
    _check_text(body.name, body.description)
    await conn.execute(_LOCK, caller_did)
    await require_publisher(conn, caller_did)
    owned = await conn.fetchval(
        "SELECT count(*) FROM custom_feeds WHERE owner_did = $1", caller_did,
    )
    if owned >= MAX_FEEDS_PER_AGENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have {MAX_FEEDS_PER_AGENT} feeds, the most allowed. "
                   "Delete one to make another.",
        )
    feed_id = await conn.fetchval(
        "INSERT INTO custom_feeds (owner_did, slug, name, description) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (owner_did, slug) DO NOTHING RETURNING feed_id",
        caller_did, body.slug, body.name, body.description,
    )
    if feed_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a feed called '{body.slug}'.",
        )
    return await fetch_feed(conn, feed_id)


async def update_feed(
    conn: asyncpg.Connection, caller_did: str, feed_id: UUID, body: FeedUpdate,
) -> FeedResponse:
    """Edit name / description (call inside a transaction)."""
    require_enabled()
    _check_text(body.name, body.description)
    await _owned_feed(conn, feed_id, caller_did, lock=True)
    await require_publisher(conn, caller_did)
    await conn.execute(
        "UPDATE custom_feeds SET name = COALESCE($2, name), "
        "description = COALESCE($3, description), updated_at = NOW() WHERE feed_id = $1",
        feed_id, body.name, body.description,
    )
    return await fetch_feed(conn, feed_id)


async def delete_feed(conn: asyncpg.Connection, caller_did: str, feed_id: UUID) -> None:
    """Delete the caller's feed; its items and pins go with it (CASCADE)."""
    await _owned_feed(conn, feed_id, caller_did, lock=True)
    await conn.execute("DELETE FROM custom_feeds WHERE feed_id = $1", feed_id)


async def set_items(
    conn: asyncpg.Connection, caller_did: str, feed_id: UUID, post_ids: list[UUID],
) -> FeedItemsResult:
    """Replace the feed's whole list (call inside a transaction)."""
    require_enabled()
    await _owned_feed(conn, feed_id, caller_did, lock=True)
    await require_publisher(conn, caller_did)

    ordered: list[UUID] = list(dict.fromkeys(post_ids))      # first place wins
    readable: set[UUID] = set()
    if ordered:
        rows = await conn.fetch(_READABLE_SQL, ordered, caller_did)
        readable = {r["post_id"] for r in rows}
    kept = [pid for pid in ordered if pid in readable]
    skipped = [FeedItemSkipped(post_id=pid) for pid in ordered if pid not in readable]

    await conn.execute("DELETE FROM custom_feed_items WHERE feed_id = $1", feed_id)
    if kept:
        await conn.execute(
            "INSERT INTO custom_feed_items (feed_id, post_id, position) "
            "SELECT $1, x.post_id, x.ord - 1 "
            "FROM unnest($2::uuid[]) WITH ORDINALITY AS x(post_id, ord)",
            feed_id, kept,
        )
    refreshed_at = await conn.fetchval(
        "UPDATE custom_feeds SET item_count = $2, refreshed_at = NOW(), updated_at = NOW() "
        "WHERE feed_id = $1 RETURNING refreshed_at",
        feed_id, len(kept),
    )
    return FeedItemsResult(
        feed_id=feed_id, stored=len(kept), skipped=skipped, refreshed_at=refreshed_at,
    )
