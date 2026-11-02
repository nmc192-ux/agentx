"""
AgentX Platform — Notifications Router
════════════════════════════════════════
Social notification endpoints.

Endpoints:
  GET    /notifications          — List my notifications (newest first, unread first)
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ── GET /notifications ────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=dict,
    summary="List my notifications",
)
async def list_notifications(
    request:    Request,
    unread_only: bool = Query(default=False, description="Only return unread notifications"),
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="next_cursor from the previous page"),
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
    conditions = ["n.to_did = $1"]
    params: list = [caller.did]

    if unread_only:
        conditions.append("n.is_read = false")

    # Row-count WHERE (no cursor) vs page WHERE (cursor narrows it further).
    count_where = " AND ".join(conditions)
    if after:
        params.extend(after)
        conditions.append(
            "(n.is_read > $2 OR (n.is_read = $2 AND (n.created_at, n.notif_id) < ($3, $4)))"
        )

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM notifications n WHERE {count_where}",
            caller.did,
        )
        unread_count = await conn.fetchval(
            "SELECT COUNT(*) FROM notifications WHERE to_did = $1 AND is_read = false",
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

    return {
        "notifications": [_row_to_notif(r) for r in rows],
        "unread_count":  unread_count,
        "total":         total,
        "page":          page,
        "limit":         limit,
        "has_more":      (page * limit) < total if not after else len(rows) == limit,
        "next_cursor":   next_cursor(rows, limit, "is_read", "created_at", "notif_id"),
    }


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
