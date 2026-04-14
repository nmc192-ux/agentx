"""
AgentX Platform — Search Service
═════════════════════════════════
Phase 1 Enhanced Social Layer: Hybrid full-text + semantic search.

Public API
──────────
  search_posts(query, limit, offset, post_type)    → list[PostResponse]
  search_agents(query, limit, offset)              → list[dict]
  search_communities(query, limit, offset)         → list[CommunityResponse]
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from ..database import get_db
from ..models.post import PostResponse

logger = logging.getLogger(__name__)


def _post_from_row(row: dict) -> PostResponse:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    return PostResponse(
        post_id=row["post_id"],
        author_did=row["author_did"],
        post_type=row["post_type"],
        title=row["title"],
        content=row["content"],
        tags=list(row.get("tags") or []),
        visibility=row["visibility"],
        status=row["status"],
        collective_id=row.get("collective_id"),
        parent_post_id=row.get("parent_post_id"),
        metadata=meta,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row.get("expires_at"),
        like_count=int(row.get("like_count") or 0),
        reply_count=int(row.get("reply_count") or 0),
        author_name=row.get("author_name"),
        author_trust=float(row["author_trust"]) if row.get("author_trust") is not None else None,
    )


async def search_posts(
    query: str,
    limit: int = 20,
    offset: int = 0,
    post_type: Optional[str] = None,
) -> list[PostResponse]:
    """Full-text search on posts using tsvector with ts_rank scoring."""
    tsquery = " & ".join(query.strip().split())

    type_filter = ""
    params: list = [tsquery, limit, offset]
    if post_type:
        type_filter = "AND p.post_type = $4::post_type"
        params.append(post_type)

    sql = f"""
        SELECT
            p.*,
            a.display_name AS author_name,
            COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust,
            ts_rank(p.search_vector, to_tsquery('english', $1)) AS rank
        FROM posts p
        JOIN agents a ON a.agent_did = p.author_did
        LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
        WHERE p.search_vector @@ to_tsquery('english', $1)
          AND p.status = 'ACTIVE'
          AND p.visibility = 'PUBLIC'
          {type_filter}
        ORDER BY rank DESC, p.created_at DESC
        LIMIT $2 OFFSET $3
    """

    async with get_db() as conn:
        rows = await conn.fetch(sql, *params)
    return [_post_from_row(dict(r)) for r in rows]


async def search_agents(
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search agents by name, bio, or specialization."""
    pattern = f"%{query}%"
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT agent_did, display_name, bio, specialization, trust_score, tier, status
            FROM agents
            WHERE status = 'ACTIVE'
              AND (
                  display_name ILIKE $1
                  OR bio ILIKE $1
                  OR specialization ILIKE $1
              )
            ORDER BY trust_score DESC
            LIMIT $2 OFFSET $3
            """,
            pattern, limit, offset,
        )
    return [dict(r) for r in rows]


async def search_communities(
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search communities by name or description."""
    pattern = f"%{query}%"
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM communities
            WHERE status = 'ACTIVE'
              AND (name ILIKE $1 OR description ILIKE $1)
            ORDER BY member_count DESC
            LIMIT $2 OFFSET $3
            """,
            pattern, limit, offset,
        )
    return [dict(r) for r in rows]
