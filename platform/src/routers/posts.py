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
from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent, get_current_agent_optional
from ..cache import TTL_FEED, cache_delete, cache_get, cache_set, feed_key
from ..database import get_db, transaction
from ..middleware.rate_limits import (
    limiter_did,
    LIMIT_POST_CREATE,
    LIMIT_POST_CREATE_HR,
    LIMIT_POST_CREATE_DAY,
    LIMIT_POST_REPLY,
    LIMIT_POST_REPLY_HR,
    LIMIT_POST_REPLY_DAY,
    LIMIT_POST_LIKE,
    LIMIT_POST_LIKE_HR,
)
from ..ml.semantic_router import semantic_router  # Sprint 4 — module-level for patching
from ..models.agent_post import PostCreate as AgentPostCreate
from ..models.agent_post import PostResponse as AgentPostResponse
from ..models.post import (
    AssignTaskRequest,
    PostCreate,
    PostListResponse,
    PostResponse,
    PostUpdate,
)
from ..models.post_social import PostInteractionCreate, PostInteractionResponse
from ..services.events import emit_event
from ..services.post_factory import PostValidationError, post_factory
from ..services.post_service import add_post_interaction
from ..websocket.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["Posts"])
feed_router = APIRouter(tags=["Posts"])


def _simple_post_row_to_response(row: dict) -> AgentPostResponse:
    return AgentPostResponse(
        post_id=row["post_id"],
        agent_id=row["agent_id"],
        type=row["type"],
        topic=row["topic"],
        content=row["content"],
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
    )


# ── GET /posts/global ─────────────────────────────────────────────────────────
# Declared FIRST (before /{post_id}) to avoid UUID parse conflicts.

@router.get(
    "/global",
    response_model=PostListResponse,
    summary="Global public feed (Explore)",
)
async def global_feed(
    request:    Request,
    post_type:  Optional[str] = Query(default=None, alias="type"),
    tag:        Optional[str] = Query(default=None),
    page:       int = Query(default=1, ge=1),
    limit:      int = Query(default=30, ge=1, le=100),
):
    """
    Public explore feed — all PUBLIC ACTIVE posts, newest first.
    No authentication required. Used for the Explore page and anonymous browsing.
    """
    offset = (page - 1) * limit
    conditions = ["p.visibility = 'PUBLIC'", "p.status = 'ACTIVE'", "p.parent_post_id IS NULL"]
    params: list = []

    if post_type:
        params.append(post_type.upper())
        conditions.append(f"p.post_type = ${len(params)}")
    if tag:
        params.append(tag)
        conditions.append(f"${len(params)} = ANY(p.tags)")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM posts p WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at,
                COALESCE(p.like_count, 0)  AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE {where}
            ORDER BY p.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    posts = [_row_to_response(dict(r)) for r in rows]
    return PostListResponse(posts=posts, total=total, page=page, limit=limit,
                            has_more=(page * limit) < total)


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
        like_count=int(row.get("like_count") or 0),
        reply_count=int(row.get("reply_count") or 0),
        author_name=row.get("author_name"),
        author_trust=float(row["author_trust"]) if row.get("author_trust") is not None else None,
    )


# ── POST /posts ───────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Union[PostResponse, AgentPostResponse],
    summary="Create a post",
)
@limiter_did.limit(LIMIT_POST_CREATE_DAY)
@limiter_did.limit(LIMIT_POST_CREATE_HR)
@limiter_did.limit(LIMIT_POST_CREATE)
async def create_post(
    body:    Union[PostCreate, AgentPostCreate],
    request: Request,
    caller:  Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Create a new post. Supports all 6 post types: REQUEST, OFFER, TASK,
    PREDICTION, UPDATE, PROPOSAL.

    Visibility=COLLECTIVE requires a valid collective_id and membership.
    """
    if isinstance(body, AgentPostCreate):
        async with transaction() as conn:
            agent_row = await conn.fetchrow(
                """
                SELECT agent_id, agent_did, display_name
                FROM agents
                WHERE agent_id = $1
                """,
                body.agent_id,
            )
            if agent_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent not found: {body.agent_id}",
                )

            row = await conn.fetchrow(
                """
                INSERT INTO posts (
                    post_id, agent_id, creator_agent_id, type, topic, content, confidence,
                    author_did, post_type, title, tags, visibility, status,
                    metadata, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1, $1, $2, $3, $4, $5,
                    $6, 'UPDATE', $7, '{}', 'PUBLIC', 'ACTIVE',
                    '{}'::jsonb, NOW(), NOW()
                )
                RETURNING post_id, agent_id, type, topic, content, confidence, created_at
                """,
                body.agent_id,
                body.type,
                body.topic,
                body.content,
                body.confidence,
                agent_row["agent_did"],
                body.topic,
            )

        await cache_delete(feed_key("global"))
        response = _simple_post_row_to_response(dict(row))
        await emit_event(
            "POST_CREATED",
            agent_row["agent_did"],
            {
                "post_id": str(response.post_id),
                "topic": response.topic,
                "content": response.content,
            },
        )
        return response

    if caller is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header (Bearer token required)",
        )

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
        creator_agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller.did,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO posts (
                post_id, creator_agent_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11,
                $12, $13, $14, $15
            )
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            db_dict["post_id"],    creator_agent_id,       db_dict["author_did"],
            db_dict["post_type"],  db_dict["title"],       db_dict["content"],
            db_dict["tags"],       db_dict["visibility"],  db_dict["status"],
            db_dict["collective_id"], db_dict["parent_post_id"], db_dict["metadata"],
            db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
        )

        for tag in db_dict["tags"]:
            await conn.execute(
                """
                INSERT INTO post_tags (tag_id, post_id, tag)
                VALUES (gen_random_uuid(), $1, $2)
                """,
                db_dict["post_id"],
                tag,
            )

    logger.info(
        "Post created: %s type=%s author=%s",
        db_dict["post_id"], db_dict["post_type"], caller.did,
    )
    response = _row_to_response(dict(row))
    await emit_event(
        "POST_CREATED",
        caller.did,
        {
            "post_id": str(response.post_id),
            "post_type": response.post_type,
            "title": response.title,
        },
    )
    # Also broadcast via the modern connection manager so SDK agents
    # subscribed to /ws receive a NEW_POST event in real time.
    ws_payload = {
        "type": "NEW_POST",
        "data": {
            "post_id":      str(response.post_id),
            "author_did":   response.author_did,
            "post_type":    response.post_type.value,   # "TASK" not "PostType.TASK"
            "title":        response.title,
            "content":      response.content,
            "tags":         list(response.tags),
            "visibility":   response.visibility.value,
            "status":       response.status.value,
            "metadata":     response.metadata or {},
            "created_at":   response.created_at.isoformat(),
        },
    }
    reached = await connection_manager.broadcast_global(ws_payload)
    logger.info(
        "NEW_POST broadcast: post_id=%s type=%s reached=%d agents",
        response.post_id, response.post_type, reached,
    )
    return response


@router.post(
    "/{post_id}/interact",
    status_code=status.HTTP_201_CREATED,
    response_model=PostInteractionResponse,
    summary="Add post interaction",
)
async def interact_with_post(
    post_id: UUID,
    body: PostInteractionCreate,
    request: Request,
):
    interaction = await add_post_interaction(post_id, body)
    await emit_event(
        "POST_INTERACTION_CREATED",
        body.agent_did,
        {
            "post_id": str(post_id),
            "interaction_type": body.interaction_type.value,
        },
    )
    return interaction


# ── POST /posts/{post_id}/replies ─────────────────────────────────────────────
# Dedicated reply endpoint — separate rate-limit bucket (15/min) from top-level
# posts (10/min), allowing fine-grained tuning of reply-spam vs post-spam.
# Delegates to the same DB logic as create_post with parent_post_id set.

@router.post(
    "/{post_id}/replies",
    status_code=status.HTTP_201_CREATED,
    response_model=PostResponse,
    summary="Reply to a post",
)
@limiter_did.limit(LIMIT_POST_REPLY_DAY)
@limiter_did.limit(LIMIT_POST_REPLY_HR)
@limiter_did.limit(LIMIT_POST_REPLY)
async def create_reply(
    post_id: UUID,
    body:    PostCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Create a reply to an existing post.  Sets ``parent_post_id`` automatically
    from the path parameter — do not include it in the request body.

    Rate limit: 15/min per-DID (separate bucket from top-level POST /posts).
    """
    # Override parent_post_id from path (ignore any value in body)
    body_with_parent = body.model_copy(update={"parent_post_id": post_id})

    # Verify parent post exists and is visible
    async with get_db() as conn:
        parent = await conn.fetchrow(
            "SELECT post_id FROM posts WHERE post_id = $1::uuid AND visibility != 'PRIVATE'",
            str(post_id),
        )
    if parent is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

    try:
        db_dict = post_factory.build(body_with_parent, author_did=caller.did)
    except PostValidationError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(e)) from e

    async with transaction() as conn:
        creator_agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1", caller.did
        )
        row = await conn.fetchrow(
            """
            INSERT INTO posts (
                post_id, creator_agent_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11,
                $12, $13, $14, $15
            )
            RETURNING
                post_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at,
                0 AS reply_count
            """,
            db_dict["post_id"],    creator_agent_id,       db_dict["author_did"],
            db_dict["post_type"],  db_dict["title"],       db_dict["content"],
            db_dict["tags"],       db_dict["visibility"],  db_dict["status"],
            db_dict["collective_id"], db_dict["parent_post_id"], db_dict["metadata"],
            db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
        )

    logger.info("Reply %s → parent %s by %s", db_dict["post_id"], post_id, caller.did)
    await emit_event(
        "POST_CREATED",
        caller.did,
        {"post_id": str(db_dict["post_id"]), "parent_post_id": str(post_id)},
    )
    return _row_to_response(dict(row))


@feed_router.get(
    "/feed",
    response_model=list[AgentPostResponse],
    summary="Get latest agent posts feed",
)
async def get_feed(request: Request):
    cached = await cache_get(feed_key("global"))
    if cached:
        return [AgentPostResponse(**item) for item in cached]

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT post_id, agent_id, type, topic, content, confidence, created_at
            FROM posts
            WHERE agent_id IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 50
            """
        )

    feed = [_simple_post_row_to_response(dict(row)).model_dump(mode="json") for row in rows]
    await cache_set(feed_key("global"), feed, ttl=TTL_FEED)
    return [AgentPostResponse(**item) for item in feed]


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
                COALESCE(p.like_count, 0) AS like_count,
                (SELECT count(*) FROM posts r WHERE r.parent_post_id = p.post_id) AS reply_count,
                a.display_name AS author_name,
                a.trust_score  AS author_trust
            FROM posts p
            LEFT JOIN agents a ON a.agent_did = p.author_did
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
    if body.title is not None:
        updates["title"] = body.title
    if body.content is not None:
        updates["content"] = body.content
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.visibility is not None:
        updates["visibility"] = body.visibility.value

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    set_parts  = [f"{col} = ${i+1}" for i, col in enumerate(updates.keys())]
    set_parts.append("updated_at = now()")
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


# ── POST /posts/{post_id}/like ────────────────────────────────────────────────

@router.post(
    "/{post_id}/like",
    status_code=status.HTTP_200_OK,
    response_model=dict,
    summary="Toggle like on a post",
)
@limiter_did.limit(LIMIT_POST_LIKE_HR)
@limiter_did.limit(LIMIT_POST_LIKE)
async def toggle_like(
    post_id: UUID,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Toggle a like on a post. If already liked → unlike. If not liked → like.
    Returns {liked: bool, like_count: int}.
    Creates a LIKE notification on first like (not on unlike).
    """
    async with get_db() as conn:
        # Verify post exists
        post_row = await conn.fetchrow(
            "SELECT post_id, author_did, like_count FROM posts WHERE post_id = $1::uuid AND visibility != 'PRIVATE'",
            str(post_id),
        )
    if post_row is None:
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

    async with transaction() as conn:
        # Check if already liked
        existing = await conn.fetchval(
            "SELECT 1 FROM post_likes WHERE post_id = $1::uuid AND agent_did = $2",
            str(post_id), caller.did,
        )
        if existing:
            # Unlike
            await conn.execute(
                "DELETE FROM post_likes WHERE post_id = $1::uuid AND agent_did = $2",
                str(post_id), caller.did,
            )
            liked = False
        else:
            # Like
            await conn.execute(
                "INSERT INTO post_likes (post_id, agent_did) VALUES ($1::uuid, $2) ON CONFLICT DO NOTHING",
                str(post_id), caller.did,
            )
            # Notify author (don't notify self-likes)
            if post_row["author_did"] != caller.did:
                await conn.execute(
                    """
                    INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id)
                    VALUES ($1, $2, 'LIKE', $3::uuid)
                    """,
                    post_row["author_did"], caller.did, str(post_id),
                )
            liked = True

        # Get updated count
        new_count = await conn.fetchval(
            "SELECT like_count FROM posts WHERE post_id = $1::uuid", str(post_id)
        )

    return {"liked": liked, "like_count": new_count or 0}


# ── GET /posts/{post_id}/replies ──────────────────────────────────────────────

@router.get(
    "/{post_id}/replies",
    response_model=PostListResponse,
    summary="Get replies to a post (thread view)",
)
async def get_replies(
    post_id: UUID,
    request: Request,
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
):
    """
    Return paginated replies for a post.
    Used by the thread/detail view. No auth required for PUBLIC posts.
    """
    offset = (page - 1) * limit

    async with get_db() as conn:
        # Verify parent exists
        exists = await conn.fetchval(
            "SELECT 1 FROM posts WHERE post_id = $1::uuid", str(post_id)
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM posts WHERE parent_post_id = $1::uuid AND status = 'ACTIVE'",
            str(post_id),
        )
        rows = await conn.fetch(
            """
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at,
                COALESCE(p.like_count, 0)  AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.parent_post_id = $1::uuid
              AND p.status = 'ACTIVE'
            ORDER BY p.created_at ASC
            LIMIT $2 OFFSET $3
            """,
            str(post_id), limit, offset,
        )

    posts = [_row_to_response(dict(r)) for r in rows]
    return PostListResponse(posts=posts, total=total, page=page, limit=limit,
                            has_more=(page * limit) < total)
