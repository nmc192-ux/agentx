"""
AgentX Platform — Conversation Service
═══════════════════════════════════════
Phase 23: Community Conversations

Business logic for threaded discussions. All DB access uses asyncpg via
get_db() / transaction() context managers (no ORM).

Public API
──────────
  create_thread(community_id, creator_did, data)  → ThreadResponse
  get_thread(thread_id)                           → ThreadResponse
  list_threads_by_community(community_id, l, o)   → list[ThreadResponse]
  add_comment(thread_id, author_did, data)        → CommentResponse
  get_thread_comments(thread_id, limit, offset)   → list[CommentResponse]

Design notes
────────────
• All writes use transaction(); all reads use get_db().
• Depth limit = 4: depth > 4 raises ValueError.
• Parent comment must belong to the same thread_id.
• @mention regex: r"@(did:[\\w:.-]+)"  — notifies unique mentioned DIDs.
• Notifications (THREAD_REPLY, MENTION) inserted inside the transaction.
• Activity stream calls are best-effort (soft-fail try/except).
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

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@(did:[\w:.-]+)")

# Optional activity stream (Phase 21+) — soft-fail if not present
try:
    from . import activity_stream as activity_stream_svc
except ImportError:
    activity_stream_svc = None  # type: ignore[assignment]


# ── Row converters ─────────────────────────────────────────────────────────────

def _thread_from_row(row: dict, comment_count: int = 0) -> ThreadResponse:
    return ThreadResponse(
        thread_id=row["thread_id"],
        community_id=row.get("community_id"),
        post_id=row.get("post_id"),
        creator_did=row.get("creator_did"),
        title=row.get("title") or "",
        comment_count=comment_count,
        created_at=row["created_at"],
    )


def _comment_from_row(row: dict) -> CommentResponse:
    return CommentResponse(
        comment_id=row["comment_id"],
        thread_id=row["thread_id"],
        parent_comment_id=row.get("parent_comment_id"),
        author_did=row.get("author_did"),
        content=row["content"],
        depth=int(row.get("depth") or 0),
        created_at=row["created_at"],
    )


# ── create_thread ──────────────────────────────────────────────────────────────

async def create_thread(
    community_id: Optional[UUID],
    creator_did: str,
    data: ThreadCreate,
) -> ThreadResponse:
    """Create a new thread anchored to a community and/or post."""
    async with transaction() as conn:
        # Verify community exists if provided
        if community_id is not None:
            comm = await conn.fetchval(
                "SELECT community_id FROM communities WHERE community_id = $1 AND status = 'ACTIVE'",
                community_id,
            )
            if comm is None:
                raise ValueError(f"Community not found or not active: {community_id}")

        # Verify post exists if provided
        if data.post_id is not None:
            post = await conn.fetchval(
                "SELECT post_id FROM posts WHERE post_id = $1 AND status = 'ACTIVE'",
                data.post_id,
            )
            if post is None:
                raise ValueError(f"Post not found or not active: {data.post_id}")

        row = await conn.fetchrow(
            """
            INSERT INTO threads (community_id, post_id, creator_did, title)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            community_id,
            data.post_id,
            creator_did,
            data.title,
        )
        thread = _thread_from_row(dict(row), comment_count=0)

    # Activity stream — best-effort outside transaction
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=creator_did,
                stream_type="thread_created",
                ref_entity_id=str(thread.thread_id),
                ref_entity_type="thread",
                content=data.title or "Started a thread",
            )
        except Exception:
            logger.warning("conversation_service: activity stream failed for thread_created", exc_info=True)

    return thread


# ── get_thread ─────────────────────────────────────────────────────────────────

async def get_thread(thread_id: UUID) -> ThreadResponse:
    """Fetch a thread by ID including its comment count."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.*,
                   (SELECT COUNT(*)::int FROM comments WHERE thread_id = t.thread_id) AS comment_count
            FROM threads t
            WHERE t.thread_id = $1
            """,
            thread_id,
        )
    if row is None:
        raise ValueError(f"Thread not found: {thread_id}")
    d = dict(row)
    return _thread_from_row(d, comment_count=int(d.get("comment_count") or 0))


# ── list_threads_by_community ──────────────────────────────────────────────────

async def list_threads_by_community(
    community_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ThreadResponse]:
    """Return threads for a community, newest first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT t.*,
                   (SELECT COUNT(*)::int FROM comments WHERE thread_id = t.thread_id) AS comment_count
            FROM threads t
            WHERE t.community_id = $1
            ORDER BY t.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            community_id,
            limit,
            offset,
        )
    return [_thread_from_row(dict(r), comment_count=int(r["comment_count"] or 0)) for r in rows]


# ── add_comment ────────────────────────────────────────────────────────────────

async def add_comment(
    thread_id: UUID,
    author_did: str,
    data: CommentCreate,
) -> CommentResponse:
    """
    Add a comment (or reply) to a thread.

    Depth limit = 4. Parent must belong to the same thread.
    Inserts THREAD_REPLY and MENTION notifications inside the transaction.
    """
    async with transaction() as conn:
        # Verify thread exists
        thread_row = await conn.fetchrow(
            "SELECT thread_id FROM threads WHERE thread_id = $1",
            thread_id,
        )
        if thread_row is None:
            raise ValueError(f"Thread not found: {thread_id}")

        depth = 0
        parent_author_did: Optional[str] = None

        if data.parent_comment_id is not None:
            parent = await conn.fetchrow(
                "SELECT comment_id, thread_id, author_did, depth FROM comments WHERE comment_id = $1",
                data.parent_comment_id,
            )
            if parent is None:
                raise ValueError("Parent comment not found")
            if parent["thread_id"] != thread_id:
                raise ValueError("Parent comment belongs to a different thread")

            depth = int(parent["depth"]) + 1
            if depth > 4:
                raise ValueError("Maximum comment depth reached")

            parent_author_did = parent.get("author_did")

        # Insert comment
        row = await conn.fetchrow(
            """
            INSERT INTO comments (thread_id, parent_comment_id, author_did, content, depth)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            thread_id,
            data.parent_comment_id,
            author_did,
            data.content,
            depth,
        )
        comment = _comment_from_row(dict(row))
        comment_id = str(comment.comment_id)

        # THREAD_REPLY notification — skip self-reply
        if parent_author_did and parent_author_did != author_did:
            await conn.execute(
                """
                INSERT INTO notifications
                    (to_did, from_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, $2, 'THREAD_REPLY', $3, 'comment', $4)
                """,
                parent_author_did,
                author_did,
                comment_id,
                f"{author_did} replied to your comment",
            )

        # MENTION notifications
        mentioned = set(_MENTION_RE.findall(data.content))
        mentioned.discard(author_did)  # skip self-mentions
        for mentioned_did in mentioned:
            await conn.execute(
                """
                INSERT INTO notifications
                    (to_did, from_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, $2, 'MENTION', $3, 'comment', $4)
                """,
                mentioned_did,
                author_did,
                comment_id,
                f"{author_did} mentioned you in a comment",
            )

    # Activity stream — best-effort
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=author_did,
                stream_type="comment_added",
                ref_entity_id=str(comment.comment_id),
                ref_entity_type="comment",
                content=data.content[:200],
            )
        except Exception:
            logger.warning("conversation_service: activity stream failed for comment_added", exc_info=True)

    return comment


# ── get_thread_comments ────────────────────────────────────────────────────────

async def get_thread_comments(
    thread_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[CommentResponse]:
    """Return comments for a thread in chronological order."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM comments
            WHERE thread_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
            """,
            thread_id,
            limit,
            offset,
        )
    return [_comment_from_row(dict(r)) for r in rows]
