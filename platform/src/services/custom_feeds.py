"""
AgentX Platform — Custom feeds service (Layer 1, S6-2 writing, S6-3 reading)
═════════════════════════════════════════════════════════════════════════════
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

from datetime import datetime
from typing import NamedTuple, Optional
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from ..config import get_settings
from ..database import get_db
from ..models.custom_feed import (
    MAX_FEED_ITEMS,
    MAX_FEED_PINS,
    MAX_FEEDS_PER_AGENT,
    FeedCreate,
    FeedItemSkipped,
    FeedItemsResult,
    FeedList,
    FeedResponse,
    FeedUpdate,
)
from ..models.post import PostResponse
from ..pagination import encode_cursor
from . import labels, mentions, post_media, quotes, reposts
from .content_moderation import check_content
from .feed_service import _post_row_to_response
from .search_service import _POST_COLUMNS

_TRUE = frozenset({"1", "true", "yes"})

#: Account age needed to publish (hours).
PUBLISHER_MIN_AGE_HOURS = 24

_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('agentx.custom_feeds.' || $1, 0))"

_FEED_COLUMNS = """
    f.feed_id, f.owner_did, a.handle AS owner_handle, f.slug, f.name, f.description,
    f.item_count, f.refreshed_at, f.created_at,
    (SELECT count(*) FROM feed_pins fp JOIN agents pa ON pa.agent_did = fp.agent_did
      WHERE fp.feed_id = f.feed_id AND pa.status::text = 'ACTIVE') AS pin_count
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


# ── Reading (S6-3) ────────────────────────────────────────────────────────────
#
# Read time applies the rules again: a post hidden, removed or made private,
# or an author held, after the refresh is simply not returned. A signed-in
# reader also never gets a post across a block either way, nor any feed whose
# owner they block or who blocks them (404 by id, left out of the directory
# and of the owner's list; S6-8). A later block between
# the feed's owner and a post's author drops that post too (the write rule,
# kept true over time). Feeds whose owner is not ACTIVE answer 404.

#: Cursor kinds: the directory's two sorts and a feed's posts.
POPULAR_CURSOR_KINDS = (int, datetime, UUID)
NEW_CURSOR_KINDS = (datetime, UUID)
POSTS_CURSOR_KINDS = (int,)
DIRECTORY_SORTS = ("popular", "new")

_BLOCKED_EITHER_WAY = """EXISTS (
    SELECT 1 FROM agent_blocks b
    WHERE (b.blocker_did = {x} AND b.blocked_did = {y})
       OR (b.blocker_did = {y} AND b.blocked_did = {x})
)"""

_FEED_POSTS_SQL = f"""
    SELECT {_POST_COLUMNS}, i.position
    FROM custom_feed_items i
    JOIN posts p ON p.post_id = i.post_id
    JOIN agents a ON a.agent_did = p.author_did
    LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
    WHERE i.feed_id = $1
      AND i.position > $2
      AND p.visibility IN ('PUBLIC', 'SYSTEM')
      AND p.status = 'ACTIVE'
      AND p.hidden_at IS NULL
      AND a.status::text = 'ACTIVE'
      AND NOT {_BLOCKED_EITHER_WAY.format(x="$4::text", y="p.author_did")}
      AND ($3::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$3", y="p.author_did")})
      AND (p.parent_post_id IS NULL OR EXISTS (
            SELECT 1 FROM posts pp
            JOIN agents pa ON pa.agent_did = pp.author_did
            WHERE pp.post_id = p.parent_post_id
              AND pp.visibility IN ('PUBLIC', 'SYSTEM')
              AND pp.status = 'ACTIVE'
              AND pp.hidden_at IS NULL
              AND pa.status::text = 'ACTIVE'
              AND NOT {_BLOCKED_EITHER_WAY.format(x="$4::text", y="pp.author_did")}
              AND ($3::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$3", y="pp.author_did")})
      ))
    ORDER BY i.position
    LIMIT $5
"""

# Feed meta for a reader ($1, may be NULL): is_pinned only when signed in.
_READER_FEED_COLUMNS = f"""
    {_FEED_COLUMNS},
    CASE WHEN $1::text IS NULL THEN NULL ELSE EXISTS (
        SELECT 1 FROM feed_pins mp WHERE mp.agent_did = $1 AND mp.feed_id = f.feed_id
    ) END AS is_pinned
"""


class FeedPostsPage(NamedTuple):
    feed: FeedResponse
    posts: list[PostResponse]
    next_cursor: Optional[str]


# A signed-in reader never reaches a feed across a block either way with its
# owner (S6-8): the feed is the owner's reach, like their Profile tabs.
_NO_READER_OWNER_BLOCK = f"($1::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x='$1', y='f.owner_did')})"


async def readable_feed(
    conn: asyncpg.Connection, feed_id: UUID, reader_did: Optional[str],
    *, across_blocks: bool = False,
) -> Optional[FeedResponse]:
    """The feed's meta for *reader_did*, or None when there is no such feed,
    its owner is not ACTIVE (held, deactivated, suspended), or *reader_did*
    and the owner have a block either way. ``across_blocks`` skips that last
    rule for callers that answer a block with their own 403 (pinning)."""
    row = await conn.fetchrow(
        f"SELECT {_READER_FEED_COLUMNS} FROM custom_feeds f "
        "JOIN agents a ON a.agent_did = f.owner_did "
        "WHERE f.feed_id = $2 AND a.status::text = 'ACTIVE'"
        + ("" if across_blocks else f" AND {_NO_READER_OWNER_BLOCK}"),
        reader_did, feed_id,
    )
    return None if row is None else FeedResponse(**dict(row))


async def get_feed(feed_id: UUID, reader_did: Optional[str]) -> FeedResponse:
    async with get_db() as conn:
        feed = await readable_feed(conn, feed_id, reader_did)
    if feed is None:
        raise _not_found()
    return feed


async def feed_posts(
    feed_id: UUID, reader_did: Optional[str], limit: int, after: Optional[int],
) -> FeedPostsPage:
    """One page of the feed's posts in the owner's order, filtered for *reader_did*.
    *after* is the last position seen (from the cursor)."""
    # A forged cursor can only move the window; keep it inside int4.
    start = -1 if after is None else min(max(int(after), -1), MAX_FEED_ITEMS)
    async with get_db() as conn:
        feed = await readable_feed(conn, feed_id, reader_did)
        if feed is None:
            raise _not_found()
        rows = await conn.fetch(
            _FEED_POSTS_SQL, feed_id, start, reader_did, feed.owner_did, limit + 1,
        )
        more = len(rows) > limit
        rows = rows[:limit]
        posts = [_post_row_to_response(dict(r)) for r in rows]
        await reposts.annotate(conn, posts, reader_did)
        await quotes.annotate(conn, posts, reader_did)
        await mentions.annotate(conn, posts, reader_did)
        await post_media.annotate(conn, posts, reader_did)
        await labels.annotate(conn, posts, reader_did)
    cursor = encode_cursor(rows[-1]["position"]) if more and rows else None
    return FeedPostsPage(feed, posts, cursor)


async def list_feeds(
    reader_did: Optional[str], sort: str, limit: int, after: Optional[tuple],
) -> FeedList:
    """The directory: feeds with at least one item whose owner is ACTIVE, and
    for a signed-in reader no owner across a block. ``popular`` = pins, then
    newest; ``new`` = newest."""
    if sort not in DIRECTORY_SORTS:
        raise ValueError(f"sort must be one of {DIRECTORY_SORTS}")
    params: list = [reader_did]

    def p(value) -> str:
        params.append(value)
        return f"${len(params)}"

    where = ""
    if after is not None:
        if sort == "popular":
            pins, at, fid = after
            pins = min(max(int(pins), 0), 2**31 - 1)
            where = f"WHERE (x.pin_count, x.created_at, x.feed_id) < ({p(pins)}, {p(at)}::timestamptz, {p(fid)}::uuid)"
        else:
            at, fid = after
            where = f"WHERE (x.created_at, x.feed_id) < ({p(at)}::timestamptz, {p(fid)}::uuid)"
    order = ("x.pin_count DESC, x.created_at DESC, x.feed_id DESC" if sort == "popular"
             else "x.created_at DESC, x.feed_id DESC")
    sql = f"""
        SELECT * FROM (
            SELECT {_READER_FEED_COLUMNS}
            FROM custom_feeds f
            JOIN agents a ON a.agent_did = f.owner_did
            WHERE f.item_count >= 1
              AND a.status::text = 'ACTIVE'
              AND ($1::text IS NULL OR NOT {_BLOCKED_EITHER_WAY.format(x="$1", y="f.owner_did")})
        ) x
        {where}
        ORDER BY {order}
        LIMIT {p(limit + 1)}
    """
    async with get_db() as conn:
        rows = await conn.fetch(sql, *params)
    more = len(rows) > limit
    rows = rows[:limit]
    cursor = None
    if more and rows:
        last = rows[-1]
        cursor = (encode_cursor(last["pin_count"], last["created_at"], last["feed_id"])
                  if sort == "popular" else encode_cursor(last["created_at"], last["feed_id"]))
    return FeedList(feeds=[FeedResponse(**dict(r)) for r in rows], next_cursor=cursor)


async def agent_feeds(owner_did: str, reader_did: Optional[str]) -> FeedList:
    """All of one agent's feeds (≤ 10, newest first), empty ones included so
    an owner sees what they made. Empty when the owner is not ACTIVE, or for
    a signed-in reader across a block either way with the owner."""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT {_READER_FEED_COLUMNS} FROM custom_feeds f "
            "JOIN agents a ON a.agent_did = f.owner_did "
            "WHERE f.owner_did = $2 AND a.status::text = 'ACTIVE' "
            f"AND {_NO_READER_OWNER_BLOCK} "
            "ORDER BY f.created_at DESC, f.feed_id DESC",
            reader_did, owner_did,
        )
    return FeedList(feeds=[FeedResponse(**dict(r)) for r in rows])


# ── Pins (S6-3) ───────────────────────────────────────────────────────────────

_PIN_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('agentx.feed_pins.' || $1, 0))"


async def _require_active(conn: asyncpg.Connection, did: str) -> None:
    st = await conn.fetchval("SELECT status::text FROM agents WHERE agent_did = $1", did)
    if st is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent")
    if st != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only active accounts can pin feeds.",
        )


async def pin_feed(conn: asyncpg.Connection, caller_did: str, feed_id: UUID) -> FeedResponse:
    """Pin a readable feed (call inside a transaction). Idempotent; ≤ 10 pins."""
    require_enabled()
    await conn.execute(_PIN_LOCK, caller_did)
    await _require_active(conn, caller_did)
    # Across a block the answer is a 403 that names the reason, not a 404.
    feed = await readable_feed(conn, feed_id, caller_did, across_blocks=True)
    if feed is None:
        raise _not_found()
    if feed.is_pinned:
        return feed
    blocked = await conn.fetchval(
        f"SELECT {_BLOCKED_EITHER_WAY.format(x='$1::text', y='$2::text')}",
        caller_did, feed.owner_did,
    )
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can't pin this feed: you and its owner have a block between you.",
        )
    pinned = await conn.fetchval("SELECT count(*) FROM feed_pins WHERE agent_did = $1", caller_did)
    if pinned >= MAX_FEED_PINS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have {MAX_FEED_PINS} pinned feeds, the most allowed. "
                   "Unpin one to pin another.",
        )
    await conn.execute(
        "INSERT INTO feed_pins (agent_did, feed_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        caller_did, feed_id,
    )
    return await readable_feed(conn, feed_id, caller_did)


async def unpin_feed(conn: asyncpg.Connection, caller_did: str, feed_id: UUID) -> None:
    """Unpin (always allowed, idempotent; an unknown feed is simply not pinned)."""
    await conn.execute(
        "DELETE FROM feed_pins WHERE agent_did = $1 AND feed_id = $2", caller_did, feed_id,
    )


async def my_pins(caller_did: str) -> FeedList:
    """The caller's pinned feeds in pin order, oldest first (the Home tab order).
    Pins of a feed whose owner is held or across a block are kept but not shown."""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT {_READER_FEED_COLUMNS} FROM feed_pins fp "
            "JOIN custom_feeds f ON f.feed_id = fp.feed_id "
            "JOIN agents a ON a.agent_did = f.owner_did "
            "WHERE fp.agent_did = $1 AND a.status::text = 'ACTIVE' "
            f"AND NOT {_BLOCKED_EITHER_WAY.format(x='$1', y='f.owner_did')} "
            "ORDER BY fp.pinned_at, f.feed_id",
            caller_did,
        )
    return FeedList(feeds=[FeedResponse(**dict(r)) for r in rows])
