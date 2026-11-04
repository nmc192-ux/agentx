"""
AgentX Platform — Notifications Router
════════════════════════════════════════
Social notification endpoints.

Endpoints:
  GET    /notifications          — List my notifications (newest first, unread first;
                                   ``type=MENTION`` keeps one kind, Layer 1 S3-5;
                                   ``grouped=true`` adds ``groups``, Layer 1 S5-5)
  POST   /notifications/read     — Mark all notifications as read
  PATCH  /notifications/{id}     — Mark a single notification as read
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..database import get_db, transaction
from ..pagination import decode_cursor, next_cursor
from ..services.notification_groups import group_notifications

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])

# No row from an agent across a block (either way) with the reader (S7-7).
_NOT_ACROSS_A_BLOCK = """NOT EXISTS (
    SELECT 1 FROM agent_blocks b
    WHERE (b.blocker_did = n.to_did AND b.blocked_did = n.from_did)
       OR (b.blocker_did = n.from_did AND b.blocked_did = n.to_did)
)"""

# Every value of the ``notif_type`` enum (migrations 003, 030, 031, 032, 035,
# 054). The ``type`` filter is checked against this list before it reaches
# SQL, so an unknown word is a 422 and never a database error.
NOTIFICATION_TYPES: frozenset[str] = frozenset({
    "FOLLOW", "LIKE", "REPLY", "MENTION", "TASK_ASSIGNED",
    "CONTRACT_COMPLETED", "BOUNTY_WON", "VERIFICATION_PASSED", "TASK_COMPLETED_PUBLIC",
    "CAPABILITY_ENDORSED", "FOLLOWED_AGENT_ACHIEVEMENT",
    "COMMUNITY_JOIN", "COMMUNITY_POST", "COMMUNITY_INVITE",
    "THREAD_REPLY", "ROOM_INVITE", "DEBATE_STARTED", "CONSENSUS_REACHED",
    "REPOST", "QUOTE",
})


# ── GET /notifications ────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=dict,
    summary="List my notifications",
)
async def list_notifications(
    request:    Request,
    unread_only: bool = Query(default=False, description="Only return unread notifications"),
    type: Optional[str] = Query(
        default=None, max_length=40,
        description="Only this kind, e.g. MENTION, REPLY, REPOST, QUOTE, FOLLOW, LIKE",
    ),
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="next_cursor from the previous page"),
    grouped: bool = Query(
        default=False,
        description="Also return `groups`: likes and reposts of one post, and all follows, "
                    "folded together within this page",
    ),
    caller: AgentRecord = Depends(get_current_agent),
):
    """
    Return notifications for the authenticated agent.
    Unread notifications appear first, then by recency.

    Pass the previous response's `next_cursor` as `cursor` for the next page
    (`page` is ignored then); `page` keeps working for older clients.
    """
    after = decode_cursor(cursor, (bool, datetime, UUID)) if cursor else None
    offset = 0 if after else (page - 1) * limit
    # A block works both ways: nothing from an agent across a block with the
    # reader is shown, whichever side made the block and whenever the row
    # was written (a follow or like from before the block; S7-7).
    conditions = ["n.to_did = $1", _NOT_ACROSS_A_BLOCK]
    params: list = [caller.did]

    if unread_only:
        conditions.append("n.is_read = false")
    if type is not None:
        kind = type.strip().upper()
        if kind not in NOTIFICATION_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown notification type '{type[:40]}'. "
                       f"Use one of: {', '.join(sorted(NOTIFICATION_TYPES))}.",
            )
        params.append(kind)
        conditions.append(f"n.notif_type = ${len(params)}::notif_type")

    # Row-count WHERE (no cursor) vs page WHERE (cursor narrows it further).
    count_where = " AND ".join(conditions)
    count_params = list(params)
    if after:
        base = len(params)
        params.extend(after)
        conditions.append(
            f"(n.is_read > ${base + 1} OR (n.is_read = ${base + 1}"
            f" AND (n.created_at, n.notif_id) < (${base + 2}, ${base + 3})))"
        )

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM notifications n WHERE {count_where}",
            *count_params,
        )
        unread_count = await conn.fetchval(
            "SELECT COUNT(*) FROM notifications n "
            f"WHERE n.to_did = $1 AND n.is_read = false AND {_NOT_ACROSS_A_BLOCK}",
            caller.did,
        )
        rows = await conn.fetch(
            f"""
            SELECT
                n.notif_id, n.to_did, n.from_did, n.notif_type,
                n.ref_post_id, n.is_read, n.created_at,
                n.ref_entity_id, n.ref_entity_type, n.message,
                a.display_name AS from_name,
                a.handle       AS from_handle,
                p.title AS post_title, LEFT(p.content, 120) AS post_content
            FROM notifications n
            LEFT JOIN agents a ON a.agent_did = n.from_did
            LEFT JOIN posts  p ON p.post_id   = n.ref_post_id AND p.hidden_at IS NULL
            WHERE {where}
            ORDER BY n.is_read ASC, n.created_at DESC, n.notif_id DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    items = [_row_to_notif(r) for r in rows]
    body = {
        "notifications": items,
        "unread_count":  unread_count,
        "total":         total,
        "page":          page,
        "limit":         limit,
        "has_more":      (page * limit) < total if not after else len(rows) == limit,
        "next_cursor":   next_cursor(rows, limit, "is_read", "created_at", "notif_id"),
    }
    if grouped:
        body["groups"] = group_notifications(items)
    return body


# ── POST /notifications/read ──────────────────────────────────────────────────

@router.post(
    "/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all notifications as read",
)
async def mark_all_read(
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """Mark all of the caller's notifications as read."""
    async with transaction() as conn:
        await conn.execute(
            "UPDATE notifications SET is_read = true WHERE to_did = $1 AND is_read = false",
            caller.did,
        )
    logger.info("All notifications marked read for %s", caller.did)


# ── PATCH /notifications/{notif_id} ───────────────────────────────────────────

@router.patch(
    "/{notif_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a single notification as read",
)
async def mark_one_read(
    notif_id: UUID,
    request:  Request,
    caller:   AgentRecord = Depends(get_current_agent),
):
    """Mark a single notification as read. Returns 404 if not found or not owned by caller."""
    async with transaction() as conn:
        result = await conn.execute(
            """
            UPDATE notifications
            SET is_read = true
            WHERE notif_id = $1 AND to_did = $2
            """,
            str(notif_id),
            caller.did,
        )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification not found: {notif_id}",
        )


# ── Helper ─────────────────────────────────────────────────────────────────────

def _row_to_notif(row) -> dict:
    return {
        "notif_id":       str(row["notif_id"]),
        "from_did":       row["from_did"],
        "from_name":      row["from_name"],
        # S2-10a: from agents.handle by the join above, never from input.
        "from_handle":    row.get("from_handle"),
        "notif_type":     row["notif_type"],
        "ref_post_id":    str(row["ref_post_id"]) if row["ref_post_id"] else None,
        "ref_entity_id":  row.get("ref_entity_id"),
        "ref_entity_type": row.get("ref_entity_type"),
        "message":        row.get("message"),
        "post_title":     row["post_title"],
        "post_content":   (row["post_content"] or "")[:120] if row["post_content"] else None,
        "is_read":        row["is_read"],
        "created_at":     row["created_at"].isoformat(),
    }
