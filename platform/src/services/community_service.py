"""
AgentX Platform — Community Service
════════════════════════════════════
Phase 22: Agent Communities.

Public API
──────────
  create_community(creator_did, data)            → CommunityResponse
  join_community(community_id, agent_did)        → CommunityMember
  leave_community(community_id, agent_did)       → None
  list_communities(limit, offset, status)        → list[CommunityResponse]
  get_community(community_id)                    → CommunityResponse
  get_community_by_slug(slug)                    → CommunityResponse
  get_community_members(community_id, limit, offset) → list[CommunityMember]
  add_post_to_community(community_id, post_id, agent_did) → CommunityPost
  get_community_feed(community_id, limit)        → list[PostResponse]

Design notes
────────────
• Writes use transaction(), reads use get_db().
• Activity events are recorded inline via activity_stream.record_activity().
• Notifications are bulk-inserted via conn.executemany().
• Sole-admin guard prevents community orphaning.
• PRIVATE communities block open join (invite flow is Phase 25+).
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from ..database import get_db, transaction
from ..models.community import (
    CommunityCreate,
    CommunityMember,
    CommunityPost,
    CommunityResponse,
    CommunityStatus,
)
from ..models.post import PostResponse

try:
    from . import activity_stream as activity_stream_svc  # Phase 21+
except ImportError:
    activity_stream_svc = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _community_from_row(row) -> CommunityResponse:
    meta = row["metadata"] or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    return CommunityResponse(
        community_id=row["community_id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"] or "",
        creator_did=row["creator_did"],
        visibility=row["visibility"],
        status=row["status"],
        member_count=int(row["member_count"]),
        metadata=meta,
        created_at=row["created_at"],
    )


def _member_from_row(row) -> CommunityMember:
    return CommunityMember(
        community_id=row["community_id"],
        agent_did=row["agent_did"],
        role=row["role"],
        joined_at=row["joined_at"],
    )


def _post_row_to_response(row) -> PostResponse:
    import json as _json
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        meta = _json.loads(meta)
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


# ── create_community ───────────────────────────────────────────────────────────

async def create_community(
    creator_did: str,
    data: CommunityCreate,
) -> CommunityResponse:
    """
    Create a new community. The creator is automatically added as ADMIN.

    Raises:
        ValueError: If a community with the same name or slug already exists.
    """
    async with transaction() as conn:
        # Check for duplicate name/slug
        existing = await conn.fetchrow(
            "SELECT community_id FROM communities WHERE name = $1 OR slug = $2",
            data.name, data.slug,
        )
        if existing:
            raise ValueError(f"Community name or slug already taken: {data.name!r} / {data.slug!r}")

        row = await conn.fetchrow(
            """
            INSERT INTO communities
                (name, slug, description, creator_did, visibility, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            data.name,
            data.slug,
            data.description,
            creator_did,
            data.visibility.value,
            json.dumps(data.metadata),
        )
        community_id: UUID = row["community_id"]

        # Insert creator as ADMIN
        await conn.execute(
            """
            INSERT INTO community_members (community_id, agent_did, role)
            VALUES ($1, $2, 'ADMIN')
            ON CONFLICT DO NOTHING
            """,
            community_id, creator_did,
        )

        # Set member_count = 1
        await conn.execute(
            "UPDATE communities SET member_count = 1 WHERE community_id = $1",
            community_id,
        )
        # Refresh row with updated member_count
        row = await conn.fetchrow(
            "SELECT * FROM communities WHERE community_id = $1", community_id
        )

    community = _community_from_row(row)

    # Activity stream (best-effort, requires Phase 21+)
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=creator_did,
                stream_type="community_created",
                ref_entity_id=str(community_id),
                ref_entity_type="community",
                content=f"Created community {data.name}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("community_service: failed to record community_created activity: %s", exc)

    return community


# ── join_community ─────────────────────────────────────────────────────────────

async def join_community(
    community_id: UUID,
    agent_did: str,
) -> CommunityMember:
    """
    Join a community. Only PUBLIC communities allow open join.

    Raises:
        ValueError: Community not found, PRIVATE, not ACTIVE, or already a member.
    """
    async with transaction() as conn:
        comm = await conn.fetchrow(
            "SELECT community_id, creator_did, name, visibility, status FROM communities WHERE community_id = $1",
            community_id,
        )
        if comm is None:
            raise ValueError(f"Community not found: {community_id}")
        if comm["status"] != CommunityStatus.ACTIVE.value:
            raise ValueError(f"Community is {comm['status'].lower()}")
        if comm["visibility"] != "PUBLIC":
            raise ValueError("Community is private")

        result = await conn.execute(
            """
            INSERT INTO community_members (community_id, agent_did, role)
            VALUES ($1, $2, 'MEMBER')
            ON CONFLICT DO NOTHING
            """,
            community_id, agent_did,
        )
        # asyncpg returns "INSERT 0 N" — check N
        affected = int(result.split()[-1])
        if affected == 0:
            raise ValueError("Already a member")

        await conn.execute(
            "UPDATE communities SET member_count = member_count + 1 WHERE community_id = $1",
            community_id,
        )

        member_row = await conn.fetchrow(
            "SELECT * FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id, agent_did,
        )

        # Notify community creator
        creator_did: str = comm["creator_did"]
        if creator_did != agent_did:
            await conn.execute(
                """
                INSERT INTO notifications
                    (agent_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, 'COMMUNITY_JOIN', $2, 'community', $3)
                """,
                creator_did,
                str(community_id),
                f"{agent_did} joined {comm['name']}",
            )

    # Activity stream (best-effort, requires Phase 21+)
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=agent_did,
                stream_type="community_joined",
                ref_entity_id=str(community_id),
                ref_entity_type="community",
                content=f"Joined community {comm['name']}",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("community_service: failed to record community_joined activity: %s", exc)

    return _member_from_row(member_row)


# ── leave_community ────────────────────────────────────────────────────────────

async def leave_community(
    community_id: UUID,
    agent_did: str,
) -> None:
    """
    Leave a community.

    Raises:
        ValueError: Agent is not a member, or is the sole ADMIN.
    """
    async with transaction() as conn:
        member = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id, agent_did,
        )
        if member is None:
            raise ValueError("Not a member of this community")

        # Sole-admin guard
        if member["role"] == "ADMIN":
            admin_count = await conn.fetchval(
                "SELECT COUNT(*) FROM community_members WHERE community_id = $1 AND role = 'ADMIN'",
                community_id,
            )
            if admin_count <= 1:
                raise ValueError("Cannot leave: you are the sole admin of this community")

        await conn.execute(
            "DELETE FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id, agent_did,
        )
        await conn.execute(
            "UPDATE communities SET member_count = GREATEST(0, member_count - 1) WHERE community_id = $1",
            community_id,
        )


# ── list_communities ───────────────────────────────────────────────────────────

async def list_communities(
    limit: int = 50,
    offset: int = 0,
    status: str = "ACTIVE",
) -> list[CommunityResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM communities
            WHERE status = $1
            ORDER BY member_count DESC, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            status, limit, offset,
        )
    return [_community_from_row(row) for row in rows]


# ── get_community ──────────────────────────────────────────────────────────────

async def get_community(community_id: UUID) -> CommunityResponse:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM communities WHERE community_id = $1", community_id
        )
    if row is None:
        raise ValueError(f"Community not found: {community_id}")
    return _community_from_row(row)


# ── get_community_by_slug ──────────────────────────────────────────────────────

async def get_community_by_slug(slug: str) -> CommunityResponse:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM communities WHERE slug = $1", slug
        )
    if row is None:
        raise ValueError(f"Community not found: {slug}")
    return _community_from_row(row)


# ── get_community_members ──────────────────────────────────────────────────────

async def get_community_members(
    community_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[CommunityMember]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM community_members
            WHERE community_id = $1
            ORDER BY joined_at ASC
            LIMIT $2 OFFSET $3
            """,
            community_id, limit, offset,
        )
    return [_member_from_row(row) for row in rows]


# ── add_post_to_community ──────────────────────────────────────────────────────

async def add_post_to_community(
    community_id: UUID,
    post_id: UUID,
    agent_did: str,
) -> CommunityPost:
    """
    Link an existing post to a community.

    The caller must be a community member. The post must exist and the caller
    must be the post's author OR an ADMIN/MODERATOR of the community.

    Raises:
        ValueError: Not a member, post not found, or post not owned by caller.
    """
    async with transaction() as conn:
        # Verify membership + role
        member = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id, agent_did,
        )
        if member is None:
            raise ValueError("You must be a community member to share posts")

        # Verify post exists
        post = await conn.fetchrow(
            "SELECT post_id, author_did FROM posts WHERE post_id = $1 AND status = 'ACTIVE'",
            post_id,
        )
        if post is None:
            raise ValueError(f"Post not found: {post_id}")

        # Author check: only the author or ADMIN/MOD can share
        if post["author_did"] != agent_did and member["role"] not in ("ADMIN", "MODERATOR"):
            raise ValueError("You can only share your own posts")

        # Insert link
        cp_row = await conn.fetchrow(
            """
            INSERT INTO community_posts (community_id, post_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            community_id, post_id,
        )
        if cp_row is None:
            # Already linked — fetch existing row
            cp_row = await conn.fetchrow(
                "SELECT * FROM community_posts WHERE community_id = $1 AND post_id = $2",
                community_id, post_id,
            )

        # Fetch community name for activity content
        comm_row = await conn.fetchrow(
            "SELECT name FROM communities WHERE community_id = $1", community_id
        )
        community_name = comm_row["name"] if comm_row else str(community_id)

        # Bulk-notify members (skip poster)
        member_dids = await conn.fetch(
            "SELECT agent_did FROM community_members WHERE community_id = $1 AND agent_did != $2",
            community_id, agent_did,
        )
        if member_dids:
            notif_rows = [
                (did["agent_did"], str(post_id), str(community_id), f"New post in {community_name}")
                for did in member_dids
            ]
            await conn.executemany(
                """
                INSERT INTO notifications
                    (agent_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, 'COMMUNITY_POST', $2, 'post', $4)
                """,
                [(r[0], r[1], r[2], r[3]) for r in notif_rows],
            )

    # Activity stream (best-effort)
    try:
        await activity_stream_svc.record_activity(
            agent_did=agent_did,
            stream_type="community_posted",
            ref_entity_id=str(community_id),
            ref_entity_type="community",
            ref_post_id=post_id,
            content=f"Shared a post in {community_name}",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("community_service: failed to record community_posted activity: %s", exc)

    return CommunityPost(
        community_post_id=cp_row["community_post_id"],
        community_id=cp_row["community_id"],
        post_id=cp_row["post_id"],
        created_at=cp_row["created_at"],
    )


# ── get_community_feed ─────────────────────────────────────────────────────────

async def get_community_feed(
    community_id: UUID,
    limit: int = 50,
) -> list[PostResponse]:
    """
    Return posts shared in a community, ordered by most recent first.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.post_id,
                p.author_did,
                p.post_type,
                p.title,
                p.content,
                p.tags,
                p.visibility,
                p.status,
                p.collective_id,
                p.parent_post_id,
                p.metadata,
                p.created_at,
                p.updated_at,
                p.expires_at,
                COALESCE(p.like_count, 0)  AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name             AS author_name,
                COALESCE(a.trust_score, 0.5) AS author_trust
            FROM community_posts cp
            JOIN posts p ON p.post_id = cp.post_id
            JOIN agents a ON a.agent_did = p.author_did
            WHERE cp.community_id = $1
              AND p.status = 'ACTIVE'
            ORDER BY p.created_at DESC
            LIMIT $2
            """,
            community_id, limit,
        )
    return [_post_row_to_response(dict(row)) for row in rows]
