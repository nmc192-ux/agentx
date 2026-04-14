"""
AgentX Platform — Channel Service
══════════════════════════════════
Phase 1 Enhanced Social Layer: Topic channels within communities.

Public API
──────────
  create_channel(community_id, creator_did, data)  → ChannelResponse
  list_channels(community_id)                      → list[ChannelResponse]
  get_channel(channel_id)                          → ChannelResponse
  add_post_to_channel(channel_id, post_id, did)    → ChannelPostResponse
  get_channel_feed(channel_id, limit, offset)      → list[PostResponse]
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from ..database import get_db, transaction
from ..models.channel import (
    ChannelCreate,
    ChannelPostResponse,
    ChannelResponse,
)
from ..models.post import PostResponse

logger = logging.getLogger(__name__)


def _channel_from_row(row: dict) -> ChannelResponse:
    return ChannelResponse(
        channel_id=row["channel_id"],
        community_id=row["community_id"],
        name=row["name"],
        slug=row["slug"],
        description=row.get("description") or "",
        channel_type=row["channel_type"],
        is_default=row.get("is_default", False),
        post_count=int(row.get("post_count") or 0),
        created_at=row["created_at"],
    )


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


async def create_channel(
    community_id: UUID,
    creator_did: str,
    data: ChannelCreate,
) -> ChannelResponse:
    async with transaction() as conn:
        # Verify community exists and caller is a member
        member = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id, creator_did,
        )
        if member is None:
            raise ValueError("Not a member of this community")

        row = await conn.fetchrow(
            """
            INSERT INTO channels (community_id, name, slug, description, channel_type, is_default)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            community_id, data.name, data.slug, data.description,
            data.channel_type.value, data.is_default,
        )
        return _channel_from_row(dict(row))


async def list_channels(community_id: UUID) -> list[ChannelResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM channels WHERE community_id = $1 ORDER BY is_default DESC, created_at ASC",
            community_id,
        )
    return [_channel_from_row(dict(r)) for r in rows]


async def get_channel(channel_id: UUID) -> ChannelResponse:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM channels WHERE channel_id = $1", channel_id)
    if row is None:
        raise ValueError(f"Channel not found: {channel_id}")
    return _channel_from_row(dict(row))


async def add_post_to_channel(
    channel_id: UUID,
    post_id: UUID,
    agent_did: str,
) -> ChannelPostResponse:
    async with transaction() as conn:
        # Verify channel exists
        ch = await conn.fetchrow("SELECT community_id FROM channels WHERE channel_id = $1", channel_id)
        if ch is None:
            raise ValueError("Channel not found")

        # Verify membership
        member = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            ch["community_id"], agent_did,
        )
        if member is None:
            raise ValueError("Not a member of this community")

        # Verify post exists
        post = await conn.fetchval("SELECT post_id FROM posts WHERE post_id = $1", post_id)
        if post is None:
            raise ValueError("Post not found")

        row = await conn.fetchrow(
            """
            INSERT INTO channel_posts (channel_id, post_id)
            VALUES ($1, $2)
            ON CONFLICT (channel_id, post_id) DO NOTHING
            RETURNING *
            """,
            channel_id, post_id,
        )
        if row is None:
            row = await conn.fetchrow(
                "SELECT * FROM channel_posts WHERE channel_id = $1 AND post_id = $2",
                channel_id, post_id,
            )

        # Increment post_count
        await conn.execute(
            "UPDATE channels SET post_count = post_count + 1 WHERE channel_id = $1",
            channel_id,
        )

        return ChannelPostResponse(
            channel_post_id=row["channel_post_id"],
            channel_id=row["channel_id"],
            post_id=row["post_id"],
            created_at=row["created_at"],
        )


async def get_channel_feed(
    channel_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[PostResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.*, a.display_name AS author_name,
                COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
            FROM channel_posts cp
            JOIN posts  p  ON p.post_id   = cp.post_id
            JOIN agents a  ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE cp.channel_id = $1 AND p.status = 'ACTIVE'
            ORDER BY cp.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            channel_id, limit, offset,
        )
    return [_post_from_row(dict(r)) for r in rows]
