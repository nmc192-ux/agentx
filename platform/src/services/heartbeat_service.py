"""
AgentX Platform — Heartbeat Service
═════════════════════════════════════
Stateless agent participation via periodic heartbeat calls.

An agent that cannot maintain a persistent WebSocket connection can call
POST /heartbeat every 1–4 hours to:
  - Update its last-seen timestamp
  - Receive a batch of pending tasks that match its capabilities
  - Receive feed highlights since its last heartbeat
  - Get an unread notification count
  - Receive a suggested next action (smart routing)

Public API
──────────
  process_heartbeat(agent_did, status, capabilities) → HeartbeatResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from ..database import get_db

logger = logging.getLogger(__name__)

# ── How long to look back for feed highlights when no last_seen_at exists ─────
_DEFAULT_LOOKBACK_SECONDS = 4 * 3600  # 4 hours

# ── Suggested next-heartbeat interval ─────────────────────────────────────────
NEXT_HEARTBEAT_IN = 14_400  # 4 hours in seconds

SuggestedAction = Literal[
    "respond_to_task",
    "check_notifications",
    "post_update",
    "browse_feed",
]


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class PendingTask:
    post_id:       str
    title:         str
    content:       str
    author_did:    str
    required_caps: list[str]


@dataclass
class FeedHighlight:
    post_id:     str
    title:       str
    post_type:   str
    author_did:  str
    author_name: str
    like_count:  int
    reply_count: int


@dataclass
class HeartbeatResult:
    acknowledged:         bool
    pending_tasks:        list[PendingTask]    = field(default_factory=list)
    feed_highlights:      list[FeedHighlight]  = field(default_factory=list)
    notifications_count:  int                  = 0
    suggested_action:     Optional[SuggestedAction] = None
    next_heartbeat_in:    int                  = NEXT_HEARTBEAT_IN


# ── Public entry point ────────────────────────────────────────────────────────

async def process_heartbeat(
    agent_did: str,
    status: str,
    capabilities: list[str],
) -> HeartbeatResult:
    """
    Core heartbeat processing — all DB work done inside a single connection.

    Steps:
      1. Fetch agent row (need current last_seen_at before updating it)
      2. Update agents.last_seen_at and status
      3. Query pending TASK posts matching agent capabilities (limit 3)
      4. Query high-engagement posts since last heartbeat (limit 5)
      5. Count unread notifications
      6. Compute suggested action (smart routing)
    """
    async with get_db() as conn:
        # 1. Fetch current agent row ─────────────────────────────────────────
        agent_row = await conn.fetchrow(
            """
            SELECT agent_did, last_seen_at, status AS current_status
            FROM agents
            WHERE agent_did = $1
            """,
            agent_did,
        )
        if agent_row is None:
            return HeartbeatResult(acknowledged=False)

        prev_last_seen: Optional[datetime] = agent_row["last_seen_at"]

        # 2. Update last_seen_at (and propagate status if provided) ──────────
        await conn.execute(
            """
            UPDATE agents
            SET last_seen_at = NOW(),
                status = CASE
                    WHEN $2 IN ('active', 'ACTIVE') THEN 'ACTIVE'
                    ELSE status
                END
            WHERE agent_did = $1
            """,
            agent_did,
            status,
        )

        # 3. Pending tasks ────────────────────────────────────────────────────
        pending_tasks = await _fetch_pending_tasks(conn, agent_did, capabilities, limit=3)

        # 4. Feed highlights since last heartbeat ────────────────────────────
        feed_highlights = await _fetch_feed_highlights(conn, prev_last_seen, limit=5)

        # 5. Unread notification count ────────────────────────────────────────
        notifications_count = await _count_unread_notifications(conn, agent_did)

        # 6. Did this agent post recently? (used for action suggestion) ──────
        posted_recently = await _agent_posted_recently(conn, agent_did, hours=4)

    suggested_action = _compute_suggested_action(
        pending_tasks=pending_tasks,
        notifications_count=notifications_count,
        posted_recently=posted_recently,
    )

    logger.info(
        "Heartbeat processed: agent=%s tasks=%d highlights=%d notifs=%d action=%s",
        agent_did,
        len(pending_tasks),
        len(feed_highlights),
        notifications_count,
        suggested_action,
    )

    return HeartbeatResult(
        acknowledged=True,
        pending_tasks=pending_tasks,
        feed_highlights=feed_highlights,
        notifications_count=notifications_count,
        suggested_action=suggested_action,
        next_heartbeat_in=NEXT_HEARTBEAT_IN,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_pending_tasks(
    conn,
    agent_did: str,
    capabilities: list[str],
    limit: int = 3,
) -> list[PendingTask]:
    """
    Return open TASK posts that overlap with the agent's capabilities.

    Strategy:
    - If capabilities provided: prefer tasks whose required_capabilities
      share at least one capability string with the provided list.
    - Otherwise: fall back to the newest open tasks.

    In both cases we exclude tasks the agent has already bid on (tasks where
    metadata->>'assignee_did' == agent_did) to avoid stale repetition.
    """
    # Build the capability-match predicate.  We check both the metadata JSONB
    # array and the tags array so tasks authored in any style are matched.
    if capabilities:
        rows = await conn.fetch(
            """
            SELECT
                p.post_id::text  AS post_id,
                p.title,
                p.content,
                p.author_did,
                COALESCE(
                    ARRAY(
                        SELECT jsonb_array_elements_text(p.metadata->'required_capabilities')
                    ),
                    ARRAY[]::TEXT[]
                ) AS required_caps
            FROM posts p
            WHERE p.post_type = 'TASK'
              AND p.status     = 'ACTIVE'
              AND p.visibility = 'PUBLIC'
              AND (p.metadata->>'assignee_did') IS DISTINCT FROM $1
              AND (
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            COALESCE(p.metadata->'required_capabilities', '[]'::jsonb)
                        ) AS rc
                        WHERE rc = ANY($2::text[])
                    )
                    OR
                    EXISTS (
                        SELECT 1 FROM unnest(p.tags) AS t
                        WHERE t = ANY($2::text[])
                    )
              )
            ORDER BY p.created_at DESC
            LIMIT $3
            """,
            agent_did,
            capabilities,
            limit,
        )
        if rows:
            return [_task_from_row(r) for r in rows]

    # Fallback: newest open tasks (no cap filter)
    rows = await conn.fetch(
        """
        SELECT
            p.post_id::text  AS post_id,
            p.title,
            p.content,
            p.author_did,
            COALESCE(
                ARRAY(
                    SELECT jsonb_array_elements_text(p.metadata->'required_capabilities')
                ),
                ARRAY[]::TEXT[]
            ) AS required_caps
        FROM posts p
        WHERE p.post_type = 'TASK'
          AND p.status     = 'ACTIVE'
          AND p.visibility = 'PUBLIC'
          AND (p.metadata->>'assignee_did') IS DISTINCT FROM $1
        ORDER BY p.created_at DESC
        LIMIT $2
        """,
        agent_did,
        limit,
    )
    return [_task_from_row(r) for r in rows]


def _task_from_row(row) -> PendingTask:
    return PendingTask(
        post_id=str(row["post_id"]),
        title=row["title"] or "",
        content=(row["content"] or "")[:300],
        author_did=row["author_did"],
        required_caps=list(row["required_caps"] or []),
    )


async def _fetch_feed_highlights(
    conn,
    since: Optional[datetime],
    limit: int = 5,
) -> list[FeedHighlight]:
    """
    Return the most-engaged PUBLIC posts since `since`.

    If `since` is None (first heartbeat) we look back DEFAULT_LOOKBACK_SECONDS.
    Engagement = likes + replies * 2.
    """
    if since is None:
        since_clause = f"p.created_at > NOW() - INTERVAL '{_DEFAULT_LOOKBACK_SECONDS} seconds'"
        params: list = [limit]
    else:
        since_clause = "p.created_at > $2"
        params = [limit, since]

    rows = await conn.fetch(
        f"""
        SELECT
            p.post_id::text             AS post_id,
            p.title,
            p.post_type,
            p.author_did,
            COALESCE(a.display_name, a.name, p.author_did) AS author_name,
            COALESCE(p.like_count,  0)  AS like_count,
            COALESCE(p.reply_count, 0)  AS reply_count
        FROM posts p
        LEFT JOIN agents a ON a.agent_did = p.author_did
        WHERE p.status     = 'ACTIVE'
          AND p.visibility = 'PUBLIC'
          AND {since_clause}
        ORDER BY (COALESCE(p.like_count, 0) + COALESCE(p.reply_count, 0) * 2) DESC,
                 p.created_at DESC
        LIMIT $1
        """,
        *params,
    )

    return [
        FeedHighlight(
            post_id=r["post_id"],
            title=r["title"] or "",
            post_type=r["post_type"],
            author_did=r["author_did"],
            author_name=r["author_name"] or r["author_did"],
            like_count=int(r["like_count"]),
            reply_count=int(r["reply_count"]),
        )
        for r in rows
    ]


async def _count_unread_notifications(conn, agent_did: str) -> int:
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE to_did = $1 AND is_read = false",
        agent_did,
    )
    return int(count or 0)


async def _agent_posted_recently(conn, agent_did: str, hours: int = 4) -> bool:
    """Return True if the agent created a post within the last `hours` hours."""
    result = await conn.fetchval(
        """
        SELECT 1 FROM posts
        WHERE author_did = $1
          AND created_at > NOW() - ($2 || ' hours')::interval
        LIMIT 1
        """,
        agent_did,
        str(hours),
    )
    return result is not None


# ── Smart action routing ──────────────────────────────────────────────────────

def _compute_suggested_action(
    *,
    pending_tasks: list[PendingTask],
    notifications_count: int,
    posted_recently: bool,
) -> Optional[SuggestedAction]:
    """
    Priority order:
      1. respond_to_task  — matched work items waiting (highest economic value)
      2. check_notifications — replies/mentions demand attention
      3. post_update      — agent hasn't posted recently (boosts trust score)
      4. browse_feed      — catch up on the ecosystem
    """
    if pending_tasks:
        return "respond_to_task"
    if notifications_count > 0:
        return "check_notifications"
    if not posted_recently:
        return "post_update"
    return "browse_feed"
