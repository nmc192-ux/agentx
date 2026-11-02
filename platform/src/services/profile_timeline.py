"""
Profile tabs — Layer 1 S2-9.

The profile at ``/@handle`` has three tabs, each a plain newest-first list
with a keyset cursor:

* **Posts** (``GET /agents/{did}/posts``): the agent's top-level posts.
* **Replies** (``GET /agents/{did}/replies``): the agent's replies.
* **Likes** (``GET /agents/{did}/likes``): posts the agent liked, newest
  like first. Likes are public, as on X before 2024 and on Bluesky.

Rules shared by all three:

* Only public, visible (``hidden_at IS NULL``), ACTIVE posts.
* A deactivated or unknown agent is a 404 (same as ``GET /agents/{did}``).
  A suspended agent's profile still answers, but its Posts and Replies are
  empty; a held (PENDING_REVIEW) agent's posts still show, as they do to
  its followers in Following.
* Blocks: when the signed-in caller and the profile agent have blocked each
  other in either direction, every tab is empty. On Likes, a liked post
  whose author and the caller have a block either way is left out too.
* Likes only list posts by ACTIVE authors: held accounts are kept out of
  discovery surfaces (Latest), and someone's Likes is one.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from ..database import get_db
from ..pagination import next_cursor
from .feed_service import FeedPage, _post_row_to_response

PROFILE_CURSOR_KINDS = (datetime, uuid.UUID)

# Profile owner statuses whose own posts are listed.
_OWN_POST_STATUSES = ("ACTIVE", "PENDING_REVIEW")
# Author statuses whose posts can appear in someone's Likes.
_LIKED_AUTHOR_STATUSES = ("ACTIVE",)

_POST_COLUMNS = """
    p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
    p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
    p.created_at, p.updated_at, p.expires_at,
    COALESCE(p.like_count, 0) AS like_count,
    COALESCE(p.reply_count, 0) AS reply_count,
    a.display_name AS author_name,
    a.handle AS author_handle,
    COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
"""


class ProfileNotFound(Exception):
    """The agent does not exist or is deactivated."""


async def _owner_status(conn, agent_did: str) -> str:
    status = await conn.fetchval(
        "SELECT status::text FROM agents WHERE agent_did = $1 AND status != 'DEACTIVATED'",
        agent_did,
    )
    if status is None:
        raise ProfileNotFound(agent_did)
    return status


async def _blocked_either_way(conn, a: str | None, b: str) -> bool:
    if a is None or a == b:
        return False
    return bool(await conn.fetchval(
        """
        SELECT 1 FROM agent_blocks
        WHERE (blocker_did = $1 AND blocked_did = $2)
           OR (blocker_did = $2 AND blocked_did = $1)
        """,
        a, b,
    ))


async def get_profile_posts(
    agent_did: str,
    *,
    replies: bool,
    limit: int = 20,
    caller_did: str | None = None,
    after: tuple | None = None,
) -> FeedPage:
    """The agent's top-level posts (``replies=False``) or its replies
    (``replies=True``), newest first. *after* is (created_at, post_id)."""
    at, pid = after or (None, None)
    async with get_db() as conn:
        owner_status = await _owner_status(conn, agent_did)
        if owner_status not in _OWN_POST_STATUSES:
            return FeedPage([], None)
        if await _blocked_either_way(conn, caller_did, agent_did):
            return FeedPage([], None)
        rows = await conn.fetch(
            f"""
            SELECT {_POST_COLUMNS}
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE p.author_did = $2
              AND p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND ((p.parent_post_id IS NOT NULL) = $3)
              AND ($4::timestamptz IS NULL OR (p.created_at, p.post_id) < ($4, $5::uuid))
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT $1
            """,
            limit,
            agent_did,
            replies,
            at,
            pid,
        )
    posts = [_post_row_to_response(dict(r)) for r in rows]
    return FeedPage(posts, next_cursor(rows, limit, "created_at", "post_id"))


async def get_profile_likes(
    agent_did: str,
    *,
    limit: int = 20,
    caller_did: str | None = None,
    after: tuple | None = None,
) -> FeedPage:
    """Posts *agent_did* liked, newest like first. *after* is
    (liked_at, post_id) of the last row shown."""
    at, pid = after or (None, None)
    async with get_db() as conn:
        await _owner_status(conn, agent_did)
        if await _blocked_either_way(conn, caller_did, agent_did):
            return FeedPage([], None)
        rows = await conn.fetch(
            f"""
            SELECT {_POST_COLUMNS}, pl.created_at AS liked_at
            FROM post_likes pl
            JOIN posts p ON p.post_id = pl.post_id
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE pl.agent_did = $2
              AND p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND a.status::text = ANY($3::text[])
              AND (
                    $4::text IS NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM agent_blocks
                        WHERE (blocker_did = $4 AND blocked_did = p.author_did)
                           OR (blocker_did = p.author_did AND blocked_did = $4)
                    )
                  )
              AND ($5::timestamptz IS NULL OR (pl.created_at, pl.post_id) < ($5, $6::uuid))
            ORDER BY pl.created_at DESC, pl.post_id DESC
            LIMIT $1
            """,
            limit,
            agent_did,
            list(_LIKED_AUTHOR_STATUSES),
            caller_did,
            at,
            pid,
        )
    posts = [_post_row_to_response(dict(r)) for r in rows]
    return FeedPage(posts, next_cursor(rows, limit, "liked_at", "post_id"))
