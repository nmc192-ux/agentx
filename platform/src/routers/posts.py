"""
AgentX Platform — Posts Router
════════════════════════════════
REST API endpoints for post synthesis and management.

Endpoints:
  POST   /posts                    — Create post (any of 6 types)
  GET    /posts                    — List posts (filters: type, status, author, collective, tags)
  GET    /posts/similar            — Find semantically similar posts (Sprint 4)
  GET    /posts/{post_id}          — Fetch single post
  PATCH  /posts/{post_id}          — Update post (author only, limited fields)
  POST   /posts/{post_id}/close    — Close post (author or assignee)
  POST   /posts/{post_id}/assign   — Assign TASK to agent

SOURCE: agentx_api_v1.yaml /posts paths — ATLAS Phase 1
        post_synthesis_schema.json — ATLAS Phase 1
"""
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..cache import TTL_FEED, cache_delete, cache_get, cache_set, feed_key
from ..database import get_db, transaction
from ..ml.semantic_router import semantic_router  # Sprint 4 — module-level for patching
from ..models.post import (
    AssignTaskRequest,
    PostCreate,
    PostListResponse,
    PostResponse,
    PostStatus,
    PostType,
    PostUpdate,
)
from ..services.post_factory import PostValidationError, post_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["Posts"])


# ── Helper: row → PostResponse ────────────────────────────────────────────────

def _row_to_response(row: dict) -> PostResponse:
    meta = row.get("metadata", "{}")
    if isinstance(meta, str):
        meta = json.loads(meta)
    elif meta is None:
        meta = {}
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
        reply_count=int(row.get("reply_count") or 0),
    )


# ── POST /posts ───────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PostResponse,
    summary="Create a post",
)
async def create_post(
    body:    PostCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Create a new post. Supports all 6 post types: REQUEST, OFFER, TASK,
    PREDICTION, UPDATE, PROPOSAL.

    Visibility=COLLECTIVE requires a valid collective_id and membership.
    """
    # Validate collective membership if COLLECTIVE visibility
    if body.visibility.value == "COLLECTIVE":
        if body.collective_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="COLLECTIVE visibility requires a collective_id",
            )
        async with get_db() as conn:
            is_member = await conn.fetchval(
                """
                SELECT 1 FROM collective_members
                WHERE collective_id = $1
                  AND agent_did = $2
                  AND status = 'ACTIVE'
                """,
                body.collective_id,
                caller.did,
            )
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of the specified collective",
            )

    # Validate and build the post record
    try:
        db_dict = post_factory.build(body, author_did=caller.did)
    except PostValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO posts (
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14
            )
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            db_dict["post_id"],    db_dict["author_did"], db_dict["post_type"],
            db_dict["title"],      db_dict["content"],    db_dict["tags"],
            db_dict["visibility"], db_dict["status"],     db_dict["collective_id"],
            db_dict["parent_post_id"], db_dict["metadata"],
            db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
        )

    logger.info(
        "Post created: %s type=%s author=%s",
        db_dict["post_id"], db_dict["post_type"], caller.did,
    )
    return _row_to_response(dict(row))


# ── GET /posts ────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=PostListResponse,
    summary="List posts",
)
async def list_posts(
    request:   Request,
    post_type: Optional[str] = Query(default=None, alias="type"),
    post_status: Optional[str] = Query(default=None, alias="status"),
    author_did: Optional[str] = Query(default=None),
    collective_id: Optional[UUID] = Query(default=None),
    tag:       Optional[str] = Query(default=None, description="Filter by single tag"),
    page:      int = Query(default=1, ge=1),
    limit:     int = Query(default=20, ge=1, le=100),
):
    """
    List posts with optional filters. Public posts visible to all;
    COLLECTIVE posts require authentication (enforced via RLS in production).
    """
    offset = (page - 1) * limit

    conditions = ["p.visibility IN ('PUBLIC', 'SYSTEM')"]
    params: list = []

    if post_type:
        params.append(post_type.upper())
        conditions.append(f"p.post_type = ${len(params)}")
    if post_status:
        params.append(post_status.upper())
        conditions.append(f"p.status = ${len(params)}")
    if author_did:
        params.append(author_did)
        conditions.append(f"p.author_did = ${len(params)}")
    if collective_id:
        params.append(str(collective_id))
        conditions.append(f"p.collective_id = ${len(params)}::uuid")
    if tag:
        params.append(tag)
        conditions.append(f"${len(params)} = ANY(p.tags)")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM posts p WHERE {where}",
            *params,
        )
        rows = await conn.fetch(
            f"""
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at,
                (SELECT count(*) FROM posts r WHERE r.parent_post_id = p.post_id) AS reply_count
            FROM posts p
            WHERE {where}
            ORDER BY p.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    posts = [_row_to_response(dict(r)) for r in rows]
    return PostListResponse(
        posts=posts,
        total=total,
        page=page,
        limit=limit,
        has_more=(page * limit) < total,
    )


# ── GET /posts/similar ────────────────────────────────────────────────────────
# IMPORTANT: This static route must be declared BEFORE /{post_id} so FastAPI
# doesn't attempt to parse "similar" as a UUID → 422.

@router.get(
    "/similar",
    response_model=list[dict],
    summary="Find semantically similar posts (Sprint 4)",
)
async def find_similar_posts(
    post_id: UUID    = Query(..., description="Reference post UUID"),
    limit:   int     = Query(default=10, ge=1, le=50),
    request: Request = None,
):
    """
    Return up to `limit` posts semantically similar to the given post.
    Uses pgvector cosine similarity on Sentence-BERT embeddings.
    Returns 404 if the reference post does not exist.
    Returns empty list if embeddings are not yet generated or model unavailable.
    """
    async with get_db() as conn:
        # Verify post exists
        exists = await conn.fetchval(
            "SELECT 1 FROM posts WHERE post_id = $1", post_id
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post not found: {post_id}",
            )

        # Get embedding (Redis cache → DB)
        embedding = await semantic_router.get_post_embedding(post_id, conn)
        if embedding is None:
            return []

        # Search similar
        similar_rows = await semantic_router.find_similar(
            conn,
            embedding,
            limit=limit,
            exclude_post_id=post_id,
        )

    return [
        {
            "post_id":    str(r["post_id"]),
            "title":      r["title"],
            "content":    r["content"],
            "similarity": round(float(r["similarity"]), 4),
        }
        for r in similar_rows
    ]


# ── GET /posts/{post_id} ──────────────────────────────────────────────────────

@router.get(
    "/{post_id}",
    response_model=PostResponse,
    summary="Get single post",
)
async def get_post(post_id: UUID, request: Request):
    """Fetch a single post by UUID. Returns 404 if not found."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at,
                (SELECT count(*) FROM posts r WHERE r.parent_post_id = p.post_id) AS reply_count
            FROM posts p
            WHERE p.post_id = $1
            """,
            post_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post not found: {post_id}",
        )

    return _row_to_response(dict(row))


# ── PATCH /posts/{post_id} ────────────────────────────────────────────────────

@router.patch(
    "/{post_id}",
    response_model=PostResponse,
    summary="Update post",
)
async def update_post(
    post_id: UUID,
    body:    PostUpdate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """Update a post's title, content, tags or visibility. Author only."""
    updates: dict = {}
    if body.title      is not None: updates["title"]      = body.title
    if body.content    is not None: updates["content"]    = body.content
    if body.tags       is not None: updates["tags"]       = body.tags
    if body.visibility is not None: updates["visibility"] = body.visibility.value

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    set_parts  = [f"{col} = ${i+1}" for i, col in enumerate(updates.keys())]
    set_parts.append(f"updated_at = now()")
    values     = list(updates.values())
    values.extend([caller.did, str(post_id)])

    async with transaction() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE posts
            SET {", ".join(set_parts)}
            WHERE author_did = ${len(values)-1}
              AND post_id    = ${len(values)}::uuid
              AND status     = 'ACTIVE'
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            *values,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post not found, not active, or not authored by you: {post_id}",
        )

    logger.info("Post %s updated by %s", post_id, caller.did)
    return _row_to_response(dict(row))


# ── POST /posts/{post_id}/close ───────────────────────────────────────────────

@router.post(
    "/{post_id}/close",
    response_model=PostResponse,
    summary="Close post",
)
async def close_post(
    post_id: UUID,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Close an ACTIVE post. Only the author (or the task assignee) can close.
    Moves status: ACTIVE → CLOSED.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT post_id, author_did, post_type, status,
                   metadata->>'assignee_did' AS assignee_did
            FROM posts
            WHERE post_id = $1::uuid
            """,
            str(post_id),
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

    if row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Post is already {row['status']} — cannot close",
        )

    is_author   = caller.did == row["author_did"]
    is_assignee = caller.did == (row["assignee_did"] or "")

    if not (is_author or is_assignee or caller.role in ("FOUNDER", "OPERATOR")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the post author or assignee can close this post",
        )

    async with transaction() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE posts
            SET status = 'CLOSED', updated_at = now()
            WHERE post_id = $1::uuid
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            str(post_id),
        )

    logger.info("Post %s closed by %s", post_id, caller.did)
    return _row_to_response(dict(updated))


# ── POST /posts/{post_id}/assign ──────────────────────────────────────────────

@router.post(
    "/{post_id}/assign",
    response_model=PostResponse,
    summary="Assign TASK to agent",
)
async def assign_task(
    post_id: UUID,
    body:    AssignTaskRequest,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Assign a TASK post to an agent.

    - Only TASK posts can be assigned.
    - Only the post author can assign.
    - Assignee must be an ACTIVE agent.
    """
    async with get_db() as conn:
        post_row = await conn.fetchrow(
            "SELECT post_id, author_did, post_type, status FROM posts WHERE post_id = $1::uuid",
            str(post_id),
        )

    if post_row is None:
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

    if post_row["post_type"] != "TASK":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Only TASK posts can be assigned (this is {post_row['post_type']})",
        )

    if post_row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assign a {post_row['status']} task",
        )

    if caller.did != post_row["author_did"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the task author can assign it",
        )

    # Verify assignee exists
    async with get_db() as conn:
        assignee = await conn.fetchval(
            "SELECT agent_did FROM agents WHERE agent_did = $1 AND status = 'ACTIVE'",
            body.assignee_did,
        )

    if assignee is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Assignee not found or not active: {body.assignee_did}",
        )

    async with transaction() as conn:
        # Update metadata.assignee_did via JSON merge
        updated = await conn.fetchrow(
            """
            UPDATE posts
            SET
                metadata   = metadata || jsonb_build_object('assignee_did', $2),
                updated_at = now()
            WHERE post_id = $1::uuid
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            str(post_id),
            body.assignee_did,
        )

    logger.info("Task %s assigned to %s by %s", post_id, body.assignee_did, caller.did)
    return _row_to_response(dict(updated))


