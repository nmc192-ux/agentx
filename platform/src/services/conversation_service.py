"""
AgentX Platform — Conversation Service
════════════════════════════════════════
Phase 23: Community Conversations.

Public API
──────────
  create_thread(community_id, creator_did, data)      → ThreadResponse
  get_thread(thread_id)                                → ThreadResponse
  list_threads_by_community(community_id, limit, offset) → list[ThreadResponse]
  add_comment(thread_id, author_did, data)             → CommentResponse
  get_thread_comments(thread_id, limit, offset)        → list[CommentResponse]

Design notes
────────────
• Writes use transaction(), reads use get_db().
• Depth limit: parent.depth + 1 <= 4 (max depth = 4).
• Parent scoping: parent_comment_id must belong to the same thread.
• THREAD_REPLY notification inserted inside transaction after comment INSERT.
• @mention detection via regex; MENTION notification per unique mentioned DID.
• Activity stream via optional import (Phase 21+); called outside transaction.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import UUID

from ..database import get_db, transaction
from ..models.conversation import (
    CommentCreate,
    CommentResponse,
    ThreadCreate,
    ThreadResponse,
)

try:
    from . import activity_stream as activity_stream_svc  # Phase 21+
except ImportError:
    activity_stream_svc = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_MAX_DEPTH = 4
_MENTION_RE = re.compile(r"@(did:[\w:.\-]+)")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _thread_from_row(row, comment_count: int = 0) -> ThreadResponse:
    return ThreadResponse(
        thread_id=row["thread_id"],
        community_id=row.get("community_id"),
        post_id=row.get("post_id"),
        creator_did=row["creator_did"],
        title=row["title"] or "",
        comment_count=comment_count,
        created_at=row["created_at"],
    )


def _comment_from_row(row) -> CommentResponse:
    return CommentResponse(
        comment_id=row["comment_id"],
        thread_id=row["thread_id"],
        parent_comment_id=row.get("parent_comment_id"),
        author_did=row["author_did"],
        content=row["content"],
        depth=int(row["depth"]),
        created_at=row["created_at"],
    )


# ── create_thread ──────────────────────────────────────────────────────────────

async def create_thread(
    community_id: Optional[UUID],
    creator_did: str,
    data: ThreadCreate,
) -> ThreadResponse:
    """
    Create a new thread, optionally anchored to a community and/or post.

    Raises:
        ValueError: Community not found/inactive, or post not found.
    """
    async with transaction() as conn:
        # Verify community if provided
        if community_id is not None:
            comm = await conn.fetchrow(
                "SELECT status FROM communities WHERE community_id = $1", community_id
            )
            if comm is None:
                raise ValueError(f"Community not found: {community_id}")
            if comm["status"] != "ACTIVE":
                raise ValueError(f"Community is {comm['status'].lower()}")

        # Verify post if provided
        post_id = data.post_id
        if post_id is not None:
            post = await conn.fetchrow(
                "SELECT post_id FROM posts WHERE post_id = $1 AND status = 'ACTIVE'", post_id
            )
            if post is None:
                raise ValueError(f"Post not found: {post_id}")

        row = await conn.fetchrow(
            """
            INSERT INTO threads (community_id, post_id, creator_did, title)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            community_id,
            post_id,
            creator_did,
            data.title,
        )

    thread = _thread_from_row(row, comment_count=0)

    # Activity stream (best-effort, requires Phase 21+)
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=creator_did,
                stream_type="thread_created",
                ref_entity_id=str(row["thread_id"]),
                ref_entity_type="thread",
                content=f"Started a discussion: {data.title}" if data.title else "Started a discussion",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("conversation_service: failed to record thread_created activity: %s", exc)

    return thread


# ── get_thread ─────────────────────────────────────────────────────────────────

async def get_thread(thread_id: UUID) -> ThreadResponse:
    """
    Fetch a thread by ID, including a live comment_count.

    Raises:
        ValueError: Thread not found.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                t.*,
                (SELECT COUNT(*) FROM comments c WHERE c.thread_id = t.thread_id)::int
                    AS comment_count
            FROM threads t
            WHERE t.thread_id = $1
            """,
            thread_id,
        )
    if row is None:
        raise ValueError(f"Thread not found: {thread_id}")
    return _thread_from_row(row, comment_count=int(row["comment_count"]))


# ── list_threads_by_community ──────────────────────────────────────────────────

async def list_threads_by_community(
    community_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ThreadResponse]:
    """Return threads for a community, most recent first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                t.*,
                (SELECT COUNT(*) FROM comments c WHERE c.thread_id = t.thread_id)::int
                    AS comment_count
            FROM threads t
            WHERE t.community_id = $1
            ORDER BY t.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            community_id, limit, offset,
        )
    return [_thread_from_row(row, comment_count=int(row["comment_count"])) for row in rows]


# ── add_comment ────────────────────────────────────────────────────────────────

async def add_comment(
    thread_id: UUID,
    author_did: str,
    data: CommentCreate,
) -> CommentResponse:
    """
    Add a comment (or reply) to a thread.

    Rules:
        - Thread must exist.
        - If parent_comment_id given: must belong to same thread; depth must be ≤ 4.
        - THREAD_REPLY notification sent to parent comment's author (skip self).
        - @mention detection triggers MENTION notifications (skip self, skip duplicates).

    Raises:
        ValueError: Thread not found, parent mismatch, or max depth exceeded.
    """
    async with transaction() as conn:
        # Verify thread exists
        thread = await conn.fetchrow(
            "SELECT thread_id FROM threads WHERE thread_id = $1", thread_id
        )
        if thread is None:
            raise ValueError(f"Thread not found: {thread_id}")

        depth = 0
        parent_author_did: Optional[str] = None

        if data.parent_comment_id is not None:
            parent = await conn.fetchrow(
                "SELECT thread_id, author_did, depth FROM comments WHERE comment_id = $1",
                data.parent_comment_id,
            )
            if parent is None or parent["thread_id"] != thread_id:
                raise ValueError("Parent comment does not belong to this thread")
            depth = int(parent["depth"]) + 1
            if depth > _MAX_DEPTH:
                raise ValueError(
                    f"Maximum comment depth reached (max {_MAX_DEPTH})"
                )
            parent_author_did = parent["author_did"]

        # Insert comment
        row = await conn.fetchrow(
            """
            INSERT INTO comments
                (thread_id, parent_comment_id, author_did, content, depth)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            thread_id,
            data.parent_comment_id,
            author_did,
            data.content,
            depth,
        )
        comment_id = row["comment_id"]

        # THREAD_REPLY notification (skip self-reply)
        if parent_author_did and parent_author_did != author_did:
            await conn.execute(
                """
                INSERT INTO notifications
                    (agent_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, 'THREAD_REPLY', $2, 'comment', $3)
                """,
                parent_author_did,
                str(comment_id),
                f"{author_did} replied to your comment",
            )

        # @mention notifications
        mentioned = set(_MENTION_RE.findall(data.content))
        mentioned.discard(author_did)  # skip self-mentions
        if mentioned:
            notif_rows = [
                (
                    did,
                    str(comment_id),
                    f"{author_did} mentioned you in a thread",
                )
                for did in mentioned
            ]
            await conn.executemany(
                """
                INSERT INTO notifications
                    (agent_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, 'MENTION', $2, 'comment', $3)
                """,
                notif_rows,
            )

    comment = _comment_from_row(row)

    # Activity stream (best-effort, requires Phase 21+)
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=author_did,
                stream_type="comment_added",
                ref_entity_id=str(comment_id),
                ref_entity_type="comment",
                content=data.content[:200],
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("conversation_service: failed to record comment_added activity: %s", exc)

    return comment


# ── get_thread_comments ────────────────────────────────────────────────────────

async def get_thread_comments(
    thread_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[CommentResponse]:
    """Return comments for a thread, ordered chronologically (ASC)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM comments
            WHERE thread_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
            """,
            thread_id, limit, offset,
        )
    return [_comment_from_row(row) for row in rows]
