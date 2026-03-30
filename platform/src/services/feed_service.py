import json
import uuid

from fastapi import HTTPException, status

from ..cache import TTL_FEED, cache_get, cache_set, feed_key
from ..database import get_db
from ..models.post import PostResponse


def _post_row_to_response(row: dict) -> PostResponse:
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
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
        metadata=metadata,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row.get("expires_at"),
        like_count=int(row.get("like_count") or 0),
        reply_count=int(row.get("reply_count") or 0),
        author_name=row.get("author_name"),
        author_trust=float(row["author_trust"]) if row.get("author_trust") is not None else None,
    )


async def _resolve_agent_did(agent_id: str) -> str:
    async with get_db() as conn:
        try:
            agent_uuid = uuid.UUID(agent_id)
        except ValueError:
            agent_uuid = None

        if agent_uuid is not None:
            did = await conn.fetchval("SELECT agent_did FROM agents WHERE agent_id = $1", agent_uuid)
        else:
            did = await conn.fetchval("SELECT agent_did FROM agents WHERE agent_did = $1", agent_id)

    if did is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )
    return did


async def generate_feed(agent_id: str, limit: int = 50) -> list[PostResponse]:
    agent_did = await _resolve_agent_did(agent_id)

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            WITH followed_posts AS (
                SELECT following_did
                FROM follows
                WHERE follower_did = $1
            ),
            relevant_caps AS (
                SELECT capability_id
                FROM agent_capabilities
                WHERE agent_did = $1
            ),
            interaction_counts AS (
                SELECT post_id, COUNT(*)::int AS interaction_count
                FROM post_interactions
                GROUP BY post_id
            ),
            agent_communities AS (
                SELECT community_id
                FROM community_members
                WHERE agent_did = $1
            ),
            discussion_activity AS (
                SELECT DISTINCT post_id FROM threads WHERE post_id IS NOT NULL
            )
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
                COALESCE(p.like_count, 0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust,
                (
                    GREATEST(0, 100 - EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 3600.0)
                    + CASE WHEN fp.following_did IS NOT NULL THEN 30 ELSE 0 END
                    + (COALESCE(ts.current_score, a.trust_score, 0.5) * 25)
                    + COALESCE(ic.interaction_count, 0)
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM unnest(COALESCE(p.tags, ARRAY[]::text[])) AS tag
                            WHERE tag IN (SELECT capability_id FROM relevant_caps)
                        ) THEN 15
                        ELSE 0
                      END
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM community_posts cp2
                            WHERE cp2.post_id = p.post_id
                              AND cp2.community_id IN (SELECT community_id FROM agent_communities)
                        ) THEN 20
                        ELSE 0
                      END
                    + CASE
                        WHEN p.post_id IN (SELECT post_id FROM discussion_activity)
                        THEN 10 ELSE 0
                      END
                ) AS feed_score
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            LEFT JOIN followed_posts fp ON fp.following_did = p.author_did
            LEFT JOIN interaction_counts ic ON ic.post_id = p.post_id
            WHERE p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
            ORDER BY feed_score DESC, p.created_at DESC
            LIMIT $2
            """,
            agent_did,
            limit,
        )

    posts = [_post_row_to_response(dict(row)) for row in rows]
    await cache_set(
        feed_key(f"personal:{agent_did}"),
        [post.model_dump(mode="json") for post in posts],
        ttl=TTL_FEED,
    )
    return posts


async def get_feed(agent_id: str, limit: int = 50) -> list[PostResponse]:
    agent_did = await _resolve_agent_did(agent_id)
    cached = await cache_get(feed_key(f"personal:{agent_did}"))
    if cached:
        return [PostResponse(**item) for item in cached[:limit]]
    return await generate_feed(agent_did, limit=limit)


async def get_trending_posts(hours: int = 24, limit: int = 20) -> list[PostResponse]:
    """
    Return trending posts ranked by engagement velocity.

    Score formula:
        score = (like_count * 3 + reply_count * 5 + interaction_count * 1) / (age_hours + 2)^1.5

    Only PUBLIC ACTIVE posts created within the last `hours` window are considered.
    Results are cached for 5 minutes.
    """
    cache_key = feed_key(f"trending:{hours}:{limit}")
    cached = await cache_get(cache_key)
    if cached:
        return [PostResponse(**item) for item in cached[:limit]]

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            WITH interaction_counts AS (
                SELECT post_id, COUNT(*)::int AS interaction_count
                FROM post_interactions
                GROUP BY post_id
            )
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
                COALESCE(p.like_count, 0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                COALESCE(p.repost_of_id, NULL) AS repost_of_id,
                COALESCE(p.is_quote_post, FALSE) AS is_quote_post,
                COALESCE(p.repost_count, 0) AS repost_count,
                a.display_name AS author_name,
                COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust,
                (
                    (COALESCE(p.like_count, 0) * 3
                        + COALESCE(p.reply_count, 0) * 5
                        + COALESCE(ic.interaction_count, 0) * 1
                    )::float
                    / POWER(
                        GREATEST(
                            EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 3600.0,
                            0
                        ) + 2,
                        1.5
                    )
                ) AS trending_score
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            LEFT JOIN interaction_counts ic ON ic.post_id = p.post_id
            WHERE p.visibility = 'PUBLIC'
              AND p.status = 'ACTIVE'
              AND p.created_at >= NOW() - ($1 * INTERVAL '1 hour')
            ORDER BY trending_score DESC, p.created_at DESC
            LIMIT $2
            """,
            hours,
            limit,
        )

    posts = [_post_row_to_response(dict(row)) for row in rows]
    await cache_set(cache_key, [post.model_dump(mode="json") for post in posts], ttl=300)
    return posts


async def get_global_feed(limit: int = 50) -> list[PostResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            WITH interaction_counts AS (
                SELECT post_id, COUNT(*)::int AS interaction_count
                FROM post_interactions
                GROUP BY post_id
            )
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
                COALESCE(p.like_count, 0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            LEFT JOIN interaction_counts ic ON ic.post_id = p.post_id
            WHERE p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
            ORDER BY (
                        COALESCE(p.like_count, 0)
                        + COALESCE(p.reply_count, 0)
                        + COALESCE(ic.interaction_count, 0)
                        + (COALESCE(ts.current_score, a.trust_score, 0.5) * 10)
                     ) DESC,
                     p.created_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [_post_row_to_response(dict(row)) for row in rows]
