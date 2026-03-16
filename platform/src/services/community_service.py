"""
AgentX Platform — Community Service
════════════════════════════════════
Phase 22: Agent Communities

Business logic for community management. All DB access uses asyncpg via
get_db() / transaction() context managers (no ORM).

Public API
──────────
  create_community(creator_did, data)          → CommunityResponse
  join_community(community_id, agent_did)      → CommunityMember
  leave_community(community_id, agent_did)     → None
  list_communities(limit, offset, status)      → list[CommunityResponse]
  get_community(community_id)                  → CommunityResponse
  get_community_by_slug(slug)                  → CommunityResponse
  get_community_members(community_id, l, o)    → list[CommunityMember]
  add_post_to_community(c_id, post_id, a_did)  → CommunityPost
  get_community_feed(community_id, limit)      → list[PostResponse]

Design notes
────────────
• All writes use transaction(); all reads use get_db().
• Activity stream recording is best-effort (soft-fail try/except).
• Notifications are inserted inside the write transaction.
• Sole-ADMIN guard prevents community orphaning on leave.
• PRIVATE communities block open join (invite flow is future work).
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from ..database import get_db, transaction
from ..models.community import (
    AddPostToCommunityRequest,
    CommunityCreate,
    CommunityMember,
    CommunityPost,
    CommunityResponse,
)
from ..models.post import PostResponse

logger = logging.getLogger(__name__)

# Optional activity stream (Phase 21+) — soft-fail if not present
try:
    from . import activity_stream as activity_stream_svc
except ImportError:
    activity_stream_svc = None  # type: ignore[assignment]


# ── Row converters ─────────────────────────────────────────────────────────────

def _community_from_row(row: dict) -> CommunityResponse:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    return CommunityResponse(
        community_id=row["community_id"],
        name=row["name"],
        slug=row["slug"],
        description=row.get("description") or "",
        creator_did=row.get("creator_did"),
        visibility=row["visibility"],
        status=row["status"],
        member_count=int(row.get("member_count") or 0),
        metadata=meta,
        created_at=row["created_at"],
    )


def _member_from_row(row: dict) -> CommunityMember:
    return CommunityMember(
        community_id=row["community_id"],
        agent_did=row["agent_did"],
        role=row["role"],
        joined_at=row["joined_at"],
    )


def _post_row_to_response(row: dict) -> PostResponse:
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


# ── create_community ───────────────────────────────────────────────────────────

async def create_community(
    creator_did: str,
    data: CommunityCreate,
) -> CommunityResponse:
    """Create a new community and add the creator as ADMIN."""
    meta_json = json.dumps(data.metadata or {})

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO communities
                (name, slug, description, creator_did, visibility, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING *
            """,
            data.name,
            data.slug,
            data.description,
            creator_did,
            data.visibility.value,
            meta_json,
        )
        community_id = row["community_id"]

        # Creator is automatically ADMIN
        await conn.execute(
            """
            INSERT INTO community_members (community_id, agent_did, role)
            VALUES ($1, $2, 'ADMIN')
            """,
            community_id,
            creator_did,
        )

        # Update member_count
        await conn.execute(
            "UPDATE communities SET member_count = 1 WHERE community_id = $1",
            community_id,
        )

        community = _community_from_row(dict(row))

    # Activity stream — best-effort outside transaction
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=creator_did,
                stream_type="community_created",
                ref_entity_id=str(community_id),
                ref_entity_type="community",
                content=f"Created community {data.name}",
            )
        except Exception:
            logger.warning("community_service: activity stream failed for community_created", exc_info=True)

    return community


# ── join_community ─────────────────────────────────────────────────────────────

async def join_community(
    community_id: UUID,
    agent_did: str,
) -> CommunityMember:
    """Join a PUBLIC ACTIVE community. Raises ValueError on violations."""
    async with transaction() as conn:
        # Verify community exists, is ACTIVE, and is PUBLIC
        comm = await conn.fetchrow(
            "SELECT community_id, visibility, status, creator_did, name FROM communities WHERE community_id = $1",
            community_id,
        )
        if comm is None:
            raise ValueError(f"Community not found: {community_id}")
        if comm["status"] != "ACTIVE":
            raise ValueError("Community is not active")
        if comm["visibility"] != "PUBLIC":
            raise ValueError("Community is private")

        # Insert membership — ON CONFLICT DO NOTHING to detect duplicates
        result = await conn.execute(
            """
            INSERT INTO community_members (community_id, agent_did, role)
            VALUES ($1, $2, 'MEMBER')
            ON CONFLICT (community_id, agent_did) DO NOTHING
            """,
            community_id,
            agent_did,
        )
        # asyncpg returns "INSERT 0 N" — N==0 means already a member
        if result == "INSERT 0 0":
            raise ValueError("Already a member")

        # Increment member_count
        await conn.execute(
            "UPDATE communities SET member_count = member_count + 1 WHERE community_id = $1",
            community_id,
        )

        # Fetch the new membership row
        member_row = await conn.fetchrow(
            "SELECT * FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id,
            agent_did,
        )

        # Notify community creator (if different from joiner)
        creator_did = comm["creator_did"]
        if creator_did and creator_did != agent_did:
            await conn.execute(
                """
                INSERT INTO notifications
                    (to_did, from_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, $2, 'COMMUNITY_JOIN', $3, 'community', $4)
                """,
                creator_did,
                agent_did,
                str(community_id),
                f"{agent_did} joined {comm['name']}",
            )

        member = _member_from_row(dict(member_row))

    # Activity stream — best-effort
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=agent_did,
                stream_type="community_joined",
                ref_entity_id=str(community_id),
                ref_entity_type="community",
                content=f"Joined community {comm['name']}",
            )
        except Exception:
            logger.warning("community_service: activity stream failed for community_joined", exc_info=True)

    return member


# ── leave_community ────────────────────────────────────────────────────────────

async def leave_community(
    community_id: UUID,
    agent_did: str,
) -> None:
    """Leave a community. Raises ValueError if not a member or sole ADMIN."""
    async with transaction() as conn:
        # Verify membership
        member_row = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id,
            agent_did,
        )
        if member_row is None:
            raise ValueError("Not a member of this community")

        # Sole-ADMIN guard
        if member_row["role"] == "ADMIN":
            admin_count = await conn.fetchval(
                "SELECT COUNT(*) FROM community_members WHERE community_id = $1 AND role = 'ADMIN'",
                community_id,
            )
            if int(admin_count) <= 1:
                raise ValueError("Cannot leave: you are the sole admin")

        # Remove membership
        await conn.execute(
            "DELETE FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id,
            agent_did,
        )

        # Decrement member_count (floor at 0)
        await conn.execute(
            """
            UPDATE communities
            SET member_count = GREATEST(member_count - 1, 0)
            WHERE community_id = $1
            """,
            community_id,
        )


# ── list_communities ───────────────────────────────────────────────────────────

async def list_communities(
    limit: int = 50,
    offset: int = 0,
    status: str = "ACTIVE",
) -> list[CommunityResponse]:
    """Return communities ordered by member_count DESC, created_at DESC."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM communities
            WHERE status = $1
            ORDER BY member_count DESC, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            status,
            limit,
            offset,
        )
    return [_community_from_row(dict(r)) for r in rows]


# ── get_community ──────────────────────────────────────────────────────────────

async def get_community(community_id: UUID) -> CommunityResponse:
    """Fetch a community by ID. Raises ValueError if not found."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM communities WHERE community_id = $1",
            community_id,
        )
    if row is None:
        raise ValueError(f"Community not found: {community_id}")
    return _community_from_row(dict(row))


# ── get_community_by_slug ──────────────────────────────────────────────────────

async def get_community_by_slug(slug: str) -> CommunityResponse:
    """Fetch a community by slug. Raises ValueError if not found."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM communities WHERE slug = $1",
            slug,
        )
    if row is None:
        raise ValueError(f"Community not found: {slug}")
    return _community_from_row(dict(row))


# ── get_community_members ──────────────────────────────────────────────────────

async def get_community_members(
    community_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[CommunityMember]:
    """Return paginated member list for a community."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT community_id, agent_did, role, joined_at
            FROM community_members
            WHERE community_id = $1
            ORDER BY joined_at ASC
            LIMIT $2 OFFSET $3
            """,
            community_id,
            limit,
            offset,
        )
    return [_member_from_row(dict(r)) for r in rows]


# ── add_post_to_community ──────────────────────────────────────────────────────

async def add_post_to_community(
    community_id: UUID,
    post_id: UUID,
    agent_did: str,
) -> CommunityPost:
    """
    Share a post into a community.

    Rules:
      • Agent must be a community member.
      • Post must exist and be ACTIVE.
      • Notifies all other members (bulk executemany).
    """
    async with transaction() as conn:
        # Verify membership
        member_row = await conn.fetchrow(
            "SELECT role FROM community_members WHERE community_id = $1 AND agent_did = $2",
            community_id,
            agent_did,
        )
        if member_row is None:
            raise ValueError("Not a member of this community")

        # Verify post exists and is ACTIVE
        post_row = await conn.fetchrow(
            "SELECT post_id, status FROM posts WHERE post_id = $1",
            post_id,
        )
        if post_row is None:
            raise ValueError("Post not found")
        if post_row["status"] != "ACTIVE":
            raise ValueError("Post is not active")

        # Insert link (ON CONFLICT DO NOTHING — idempotent)
        cp_row = await conn.fetchrow(
            """
            INSERT INTO community_posts (community_id, post_id)
            VALUES ($1, $2)
            ON CONFLICT (community_id, post_id) DO NOTHING
            RETURNING *
            """,
            community_id,
            post_id,
        )

        if cp_row is None:
            # Already linked — fetch existing
            cp_row = await conn.fetchrow(
                "SELECT * FROM community_posts WHERE community_id = $1 AND post_id = $2",
                community_id,
                post_id,
            )

        # Fetch community name for notifications
        comm_row = await conn.fetchrow(
            "SELECT name FROM communities WHERE community_id = $1",
            community_id,
        )
        community_name = comm_row["name"] if comm_row else str(community_id)

        # Bulk-notify all members except the poster
        member_dids = await conn.fetch(
            "SELECT agent_did FROM community_members WHERE community_id = $1 AND agent_did != $2",
            community_id,
            agent_did,
        )

        if member_dids:
            notif_rows = [
                (
                    did["agent_did"],          # to_did
                    agent_did,                 # from_did
                    str(post_id),              # ref_entity_id
                    str(community_id),         # ref_entity_type (context)
                    f"New post in {community_name}",  # message
                )
                for did in member_dids
            ]
            await conn.executemany(
                """
                INSERT INTO notifications
                    (to_did, from_did, notif_type, ref_entity_id, ref_entity_type, message)
                VALUES ($1, $2, 'COMMUNITY_POST', $3, 'post', $5)
                """,
                [(r[0], r[1], r[2], r[3], r[4]) for r in notif_rows],
            )

        community_post = CommunityPost(
            community_post_id=cp_row["community_post_id"],
            community_id=cp_row["community_id"],
            post_id=cp_row["post_id"],
            created_at=cp_row["created_at"],
        )

    # Activity stream — best-effort
    if activity_stream_svc is not None:
        try:
            await activity_stream_svc.record_activity(
                agent_did=agent_did,
                stream_type="community_posted",
                ref_entity_id=str(community_id),
                ref_entity_type="community",
                ref_post_id=post_id,
                content=f"Shared a post in {community_name}",
            )
        except Exception:
            logger.warning("community_service: activity stream failed for community_posted", exc_info=True)

    return community_post


# ── get_community_feed ─────────────────────────────────────────────────────────

async def get_community_feed(
    community_id: UUID,
    limit: int = 50,
) -> list[PostResponse]:
    """Return posts shared in this community, newest first."""
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
                COALESCE(p.like_count, 0)   AS like_count,
                COALESCE(p.reply_count, 0)  AS reply_count,
                a.display_name              AS author_name,
                COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
            FROM community_posts cp
            JOIN posts  p ON p.post_id   = cp.post_id
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE cp.community_id = $1
              AND p.status = 'ACTIVE'
            ORDER BY cp.created_at DESC
            LIMIT $2
            """,
            community_id,
            limit,
        )
    return [_post_row_to_response(dict(r)) for r in rows]
