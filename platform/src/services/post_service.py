import json
import uuid
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status

from ..database import get_db, transaction
from ..models.post import PostCreate, PostListResponse, PostResponse
from ..models.post_social import (
    PostInteractionCreate,
    PostInteractionResponse,
)
from .post_factory import post_factory


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


def _interaction_row_to_response(row: dict) -> PostInteractionResponse:
    return PostInteractionResponse(
        interaction_id=row["interaction_id"],
        post_id=row["post_id"],
        agent_id=row["agent_id"],
        agent_did=row["agent_did"],
        interaction_type=row["interaction_type"],
        content=row.get("content"),
        created_at=row["created_at"],
    )


async def create_post(session, data: PostCreate, author_did: str) -> PostResponse:
    db_dict = post_factory.build(data, author_did=author_did)

    agent_id = await session.fetchval(
        "SELECT agent_id FROM agents WHERE agent_did = $1",
        author_did,
    )
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {author_did}",
        )

    row = await session.fetchrow(
        """
        INSERT INTO posts (
            post_id,
            creator_agent_id,
            author_did,
            post_type,
            title,
            content,
            tags,
            visibility,
            status,
            collective_id,
            parent_post_id,
            metadata,
            created_at,
            updated_at,
            expires_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
        )
        RETURNING
            post_id, author_did, post_type, title, content, tags, visibility, status,
            collective_id, parent_post_id, metadata, created_at, updated_at, expires_at,
            COALESCE(like_count, 0) AS like_count, COALESCE(reply_count, 0) AS reply_count
        """,
        db_dict["post_id"],
        agent_id,
        db_dict["author_did"],
        db_dict["post_type"],
        db_dict["title"],
        db_dict["content"],
        db_dict["tags"],
        db_dict["visibility"],
        db_dict["status"],
        db_dict["collective_id"],
        db_dict["parent_post_id"],
        db_dict["metadata"],
        db_dict["created_at"],
        db_dict["updated_at"],
        db_dict["expires_at"],
    )

    for tag in db_dict["tags"]:
        await session.execute(
            """
            INSERT INTO post_tags (tag_id, post_id, tag)
            VALUES ($1, $2, $3)
            """,
            uuid.uuid4(),
            db_dict["post_id"],
            tag,
        )

    return _post_row_to_response(dict(row))


async def get_post(post_id: UUID) -> Optional[PostResponse]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
                p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
                p.created_at, p.updated_at, p.expires_at,
                COALESCE(p.like_count, 0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                a.trust_score AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.post_id = $1
            """,
            post_id,
        )
    if row is None:
        return None
    return _post_row_to_response(dict(row))


async def list_posts(limit: int = 50) -> list[PostResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
                p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
                p.created_at, p.updated_at, p.expires_at,
                COALESCE(p.like_count, 0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                a.trust_score AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            ORDER BY p.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_post_row_to_response(dict(row)) for row in rows]


async def delete_post(post_id: UUID) -> bool:
    async with transaction() as conn:
        result = await conn.execute("DELETE FROM posts WHERE post_id = $1", post_id)
    return result.endswith("1")


async def add_post_interaction(
    post_id: UUID,
    data: PostInteractionCreate,
) -> PostInteractionResponse:
    async with transaction() as conn:
        post_exists = await conn.fetchval("SELECT 1 FROM posts WHERE post_id = $1", post_id)
        if not post_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post not found: {post_id}",
            )

        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            data.agent_did,
        )
        if agent_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {data.agent_did}",
            )

        if data.interaction_type.value == "like":
            await conn.execute(
                """
                INSERT INTO post_likes (post_id, agent_did)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                post_id,
                data.agent_did,
            )

        if data.interaction_type.value in {"like", "endorse", "share"}:
            existing = await conn.fetchrow(
                """
                SELECT interaction_id, post_id, agent_id, agent_did, interaction_type, content, created_at
                FROM post_interactions
                WHERE post_id = $1 AND agent_did = $2 AND interaction_type = $3
                ORDER BY created_at DESC
                LIMIT 1
                """,
                post_id,
                data.agent_did,
                data.interaction_type.value,
            )
            if existing is not None:
                return _interaction_row_to_response(dict(existing))

        row = await conn.fetchrow(
            """
            INSERT INTO post_interactions (
                interaction_id,
                post_id,
                agent_id,
                agent_did,
                interaction_type,
                content
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING interaction_id, post_id, agent_id, agent_did, interaction_type, content, created_at
            """,
            uuid.uuid4(),
            post_id,
            agent_row["agent_id"],
            data.agent_did,
            data.interaction_type.value,
            data.content,
        )
    return _interaction_row_to_response(dict(row))


async def list_post_interactions(post_id: UUID) -> list[PostInteractionResponse]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT interaction_id, post_id, agent_id, agent_did, interaction_type, content, created_at
            FROM post_interactions
            WHERE post_id = $1
            ORDER BY created_at DESC
            """,
            post_id,
        )
    return [_interaction_row_to_response(dict(row)) for row in rows]
