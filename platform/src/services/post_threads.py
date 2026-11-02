"""
Threads and the conversation view — Layer 1 S3-2.

* **Thread** (``POST /posts/thread``): 2-25 UPDATE posts written in one
  transaction; post *n+1* replies to post *n*. Every item passes the content
  check; one bad item refuses the whole thread and nothing is stored. If any
  item reads as solicitation, every item is held for review (a thread is one
  message).
* **Conversation** (``GET /posts/{id}/conversation``): the chain of ancestors
  up to the root, the post, and its replies as a tree.

Read rules for the conversation, the same as ``GET /posts/{id}/replies`` plus
blocks:

* The post itself follows ``post_moderation.may_see_post`` (so its author and
  moderators may open it while hidden). A block either way between the caller
  and its author makes it a 404 too.
* Replies are listed only when ACTIVE, not hidden, readable by the caller
  (``visible_to_sql``) and not by an author with a block either way; a reply
  left out takes its whole subtree with it.
* An ancestor the caller may not read is kept as ``{"unavailable": true}``
  so the chain still shows where the conversation came from.

The tree is bounded: ``depth`` levels (max ``MAX_DEPTH``), ``limit`` replies
per post, oldest first, and ``MAX_NODES`` posts in all. Ancestors stop after
``MAX_ANCESTORS`` (a longer chain only exists if someone built one on purpose).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from ..models.post import (
    ConversationAncestor,
    ConversationNode,
    ConversationResponse,
    PostResponse,
)
from . import post_moderation
from .feed_service import _post_row_to_response

MAX_DEPTH = 10
DEFAULT_DEPTH = 5
MAX_PER_LEVEL = 50
DEFAULT_PER_LEVEL = 20
MAX_NODES = 200
MAX_ANCESTORS = 50

# Thread items one agent may post in 24 hours (on top of the per-request limit).
THREAD_ITEMS_PER_DAY = 100

_COLUMNS = """
    p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
    p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
    p.created_at, p.updated_at, p.expires_at, p.hidden_at, p.hidden_reason,
    COALESCE(p.like_count, 0) AS like_count,
    COALESCE(p.reply_count, 0) AS reply_count,
    a.display_name AS author_name,
    a.handle AS author_handle,
    a.trust_score AS author_trust
"""

# Block either way between the caller ($2, may be NULL) and the row's author.
_NOT_BLOCKED = """
    NOT EXISTS (
        SELECT 1 FROM agent_blocks b
        WHERE (b.blocker_did = $2 AND b.blocked_did = p.author_did)
           OR (b.blocker_did = p.author_did AND b.blocked_did = $2)
    )
"""


class ConversationNotFound(Exception):
    """The post does not exist for this caller."""


def default_title(content: str) -> str:
    """A thread item's title when none is given: its first line, cut to 80."""
    first = content.strip().splitlines()[0] if content.strip() else content
    first = " ".join(first.split())
    return (first[:77] + "...") if len(first) > 80 else (first or "Thread")


async def thread_items_today(conn, author_did: str) -> int:
    """Thread posts *author_did* wrote in the last 24 hours."""
    return int(await conn.fetchval(
        """
        SELECT count(*) FROM posts
        WHERE author_did = $1 AND created_at > NOW() - INTERVAL '24 hours'
          AND metadata ? 'thread'
        """,
        author_did,
    ))


def _response(row) -> PostResponse:
    row = dict(row)
    response = _post_row_to_response(row)
    if row.get("hidden_at") is not None:
        response.hidden, response.hidden_reason = True, row.get("hidden_reason")
    return response


async def _blocked_either_way(conn, a: Optional[str], b: str) -> bool:
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


async def _ancestors(conn, parent_id: Optional[UUID], caller_did: Optional[str]):
    if parent_id is None:
        return []
    visible = post_moderation.visible_to_sql("p", 2)
    rows = await conn.fetch(
        f"""
        WITH RECURSIVE chain AS (
            SELECT post_id, parent_post_id, 1 AS n FROM posts WHERE post_id = $1
            UNION ALL
            SELECT p.post_id, p.parent_post_id, c.n + 1
            FROM posts p JOIN chain c ON p.post_id = c.parent_post_id
            WHERE c.n < $3
        )
        SELECT c.n, {_COLUMNS},
               (p.hidden_at IS NULL AND {visible} AND {_NOT_BLOCKED}) AS readable
        FROM chain c
        JOIN posts p ON p.post_id = c.post_id
        LEFT JOIN agents a ON a.agent_did = p.author_did
        ORDER BY c.n DESC
        """,
        parent_id, caller_did, MAX_ANCESTORS,
    )
    return [
        ConversationAncestor(post_id=r["post_id"], post=_response(r))
        if r["readable"] else
        ConversationAncestor(post_id=r["post_id"], unavailable=True)
        for r in rows
    ]


async def _children(conn, parent_ids: list[UUID], caller_did: Optional[str], limit: int):
    """Readable direct replies of *parent_ids*: up to *limit* per parent,
    oldest first, each row carrying ``total`` (all readable replies of its
    parent). Also returns {parent: total} for parents whose replies were cut."""
    visible = post_moderation.visible_to_sql("p", 2)
    rows = await conn.fetch(
        f"""
        SELECT * FROM (
            SELECT {_COLUMNS},
                   row_number() OVER w AS rn,
                   count(*) OVER (PARTITION BY p.parent_post_id) AS total
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.parent_post_id = ANY($1::uuid[])
              AND p.status = 'ACTIVE' AND p.hidden_at IS NULL
              AND {visible} AND {_NOT_BLOCKED}
            WINDOW w AS (PARTITION BY p.parent_post_id ORDER BY p.created_at, p.post_id)
        ) t
        WHERE rn <= $3
        ORDER BY array_position($1::uuid[], parent_post_id), rn
        """,
        parent_ids, caller_did, limit,
    )
    return rows


async def get_conversation(
    conn, post_id: UUID, caller, depth: int = DEFAULT_DEPTH, limit: int = DEFAULT_PER_LEVEL,
) -> ConversationResponse:
    depth = max(1, min(depth, MAX_DEPTH))
    limit = max(1, min(limit, MAX_PER_LEVEL))
    caller_did = caller.did if caller is not None else None

    row = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM posts p LEFT JOIN agents a ON a.agent_did = p.author_did"
        " WHERE p.post_id = $1",
        post_id,
    )
    if row is None or not await post_moderation.may_see_post(conn, caller, row):
        raise ConversationNotFound(post_id)
    if await _blocked_either_way(conn, caller_did, row["author_did"]):
        raise ConversationNotFound(post_id)

    ancestors = await _ancestors(conn, row["parent_post_id"], caller_did)

    root = ConversationNode(post=_response(row))
    nodes: dict[UUID, ConversationNode] = {row["post_id"]: root}
    frontier = [row["post_id"]]
    shown = 0
    for _ in range(depth):
        if not frontier or shown >= MAX_NODES:
            break
        children = await _children(conn, frontier, caller_did, limit)
        next_frontier: list[UUID] = []
        totals: dict[UUID, int] = {}
        for child in children:
            parent = nodes[child["parent_post_id"]]
            totals[child["parent_post_id"]] = int(child["total"])
            if shown >= MAX_NODES:
                continue
            node = ConversationNode(post=_response(child))
            parent.replies.append(node)
            nodes[child["post_id"]] = node
            next_frontier.append(child["post_id"])
            shown += 1
        for parent_id, total in totals.items():
            parent = nodes[parent_id]
            parent.more_replies = total - len(parent.replies)
        frontier = next_frontier

    # Posts at the depth cap: say how many replies sit under them unseen.
    if frontier:
        await _count_below_cap(conn, frontier, caller_did, nodes)

    return ConversationResponse(
        ancestors=ancestors,
        post=root.post,
        replies=root.replies,
        more_replies=root.more_replies,
    )


async def _count_below_cap(conn, parent_ids, caller_did, nodes) -> None:
    visible = post_moderation.visible_to_sql("p", 2)
    rows = await conn.fetch(
        f"""
        SELECT p.parent_post_id, count(*) AS total
        FROM posts p
        WHERE p.parent_post_id = ANY($1::uuid[])
          AND p.status = 'ACTIVE' AND p.hidden_at IS NULL
          AND {visible} AND {_NOT_BLOCKED}
        GROUP BY p.parent_post_id
        """,
        parent_ids, caller_did,
    )
    for r in rows:
        nodes[r["parent_post_id"]].more_replies = int(r["total"])
