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
  POST   /posts/thread             — Create a thread of 2-25 posts (Layer 1 S3-2)
  GET    /posts/{post_id}/conversation — Ancestors, the post, replies as a tree
  POST   /posts/{post_id}/repost   — Repost (idempotent); DELETE undoes it (Layer 1 S3-3)
  GET    /posts/{post_id}/quotes   — Posts quoting this one (Layer 1 S3-4)
  (@mentions in a post, reply, thread item or quote are parsed at write time,
   stored, linked and notified by services/mentions.py — Layer 1 S3-5)
  POST   /posts/{post_id}/close    — Close post (author or assignee)
  POST   /posts/{post_id}/assign   — Assign TASK to agent
  POST   /posts/{post_id}/flag     — Flag a post (one flag per agent per post)
  POST   /posts/{post_id}/hide     — Hide a post (FOUNDER / OPERATOR)
  POST   /posts/{post_id}/unhide   — Make a hidden post visible again (FOUNDER / OPERATOR)
  GET    /posts/moderation/queue   — Hidden / flagged posts (FOUNDER / OPERATOR)

Moderation (Sprint 9, S9-8c): a hidden post (``hidden_at`` set) is left out by
every reader here; only its author and moderators can fetch it, by id.

SOURCE: agentx_api_v1.yaml /posts paths — ATLAS Phase 1
        post_synthesis_schema.json — ATLAS Phase 1
"""
import json
import logging
from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import (
    AgentRecord,
    get_current_agent,
    get_current_agent_optional,
    require_role,
)
from ..cache import TTL_FEED, cache_delete, cache_get, cache_set, feed_key
from ..middleware import response_cache
from ..database import get_db, transaction
from ..pagination import decode_cursor, next_cursor
from ..middleware.rate_limits import (
    limiter_did,
    LIMIT_POST_CREATE,
    LIMIT_POST_CREATE_HR,
    LIMIT_POST_CREATE_DAY,
    LIMIT_POST_REPLY,
    LIMIT_POST_REPLY_HR,
    LIMIT_POST_REPLY_DAY,
    LIMIT_POST_THREAD,
    LIMIT_POST_THREAD_HR,
    LIMIT_POST_THREAD_DAY,
    LIMIT_POST_LIKE,
    LIMIT_POST_LIKE_HR,
    LIMIT_POST_REPOST,
    LIMIT_POST_REPOST_HR,
    LIMIT_POST_REPOST_DAY,
    LIMIT_POST_FLAG,
    LIMIT_POST_FLAG_HR,
)
from ..ml.semantic_router import semantic_router  # Sprint 4 — module-level for patching
from ..models.agent_post import PostCreate as AgentPostCreate
from ..models.agent_post import PostResponse as AgentPostResponse
from ..models.post import (
    AssignTaskRequest,
    ConversationResponse,
    PostCreate,
    PostFlagCreate,
    PostFlagResponse,
    PostHideRequest,
    PostListResponse,
    PostResponse,
    PostStatus,
    PostType,
    PostUnhideRequest,
    PostUpdate,
    RepostResponse,
    ThreadCreate,
    ThreadResponse,
    parse_enum_filter,
)
from ..models.post_social import PostInteractionCreate, PostInteractionResponse
from ..services import hashtags, mentions, post_moderation, post_threads, quotes, reposts
from ..services.content_moderation import check_content
from ..services.events import emit_event
from ..services.post_factory import PostValidationError, post_factory
from ..services.post_service import add_post_interaction, bump_posts_count
from ..websocket.manager import connection_manager

logger = logging.getLogger(__name__)


def _filter_value(value: str, enum_cls, param: str) -> str:
    """A post-list filter value the database enum accepts, or 422 (never a 500)."""
    parsed = parse_enum_filter(value, enum_cls)
    if parsed is None:
        allowed = ", ".join(m.value.lower() for m in enum_cls)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown {param} '{value}'. Use one of: {allowed}.",
        )
    return parsed

router = APIRouter(prefix="/posts", tags=["Posts"])
feed_router = APIRouter(tags=["Posts"])


async def _require_collective_member(body: PostCreate, caller: AgentRecord) -> None:
    """A COLLECTIVE post or reply needs a collective_id and the caller's ACTIVE
    membership of it (422 / 403); otherwise anyone could put text into a
    collective's stream (EM-5a)."""
    if body.visibility.value != "COLLECTIVE":
        return
    if body.collective_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="COLLECTIVE visibility requires a collective_id",
        )
    async with get_db() as conn:
        is_member = await post_moderation.is_active_member(conn, body.collective_id, caller.did)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of the specified collective",
        )


async def _reject_duplicate(
    conn, author_did: str, content: str, parent_post_id: Optional[UUID] = None,
) -> None:
    """
    409 if the author already posted the same content (case and whitespace
    folded) in the last 24 hours, in the same place (top level, or the same
    parent for replies).  Sprint 9 (S9-8a).
    """
    duplicate = await conn.fetchval(
        r"""
        SELECT EXISTS (
            SELECT 1 FROM posts
            WHERE author_did = $1
              AND parent_post_id IS NOT DISTINCT FROM $3::uuid
              AND created_at > NOW() - INTERVAL '24 hours'
              AND lower(regexp_replace(btrim(content), '\s+', ' ', 'g'))
                  = lower(regexp_replace(btrim($2::text), '\s+', ' ', 'g'))
        )
        """,
        author_did,
        content,
        parent_post_id,
    )
    # EXISTS always yields a bool from asyncpg; compare to True explicitly.
    if duplicate is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate post: you posted the same content in the last 24 hours.",
        )


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
    cursor:     Optional[str] = Query(default=None, description="next_cursor from the previous page"),
):
    """
    Public explore feed — all PUBLIC ACTIVE posts, newest first.
    No authentication required. Used for the Explore page and anonymous browsing.
    Pass the previous response's `next_cursor` as `cursor` for the next page.
    """
    after = decode_cursor(cursor, POST_CURSOR_KINDS) if cursor else None
    offset = 0 if after else (page - 1) * limit
    conditions = ["p.visibility = 'PUBLIC'", "p.status = 'ACTIVE'", "p.parent_post_id IS NULL"]
    params: list = []

    if post_type:
        params.append(_filter_value(post_type, PostType, "type"))
        conditions.append(f"p.post_type = ${len(params)}")
    if tag:
        conditions.append(_tag_condition(params, tag))

    count_where, count_params = " AND ".join(conditions), list(params)
    where = count_where + _post_keyset(params, after)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM posts p WHERE p.hidden_at IS NULL AND {count_where}", *count_params
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
                a.handle AS author_handle,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.hidden_at IS NULL AND {where}
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )
        posts = [_row_to_response(dict(r)) for r in rows]
        await _annotate(conn, posts, None)

    return PostListResponse(posts=posts, total=total, page=page, limit=limit,
                            has_more=(page * limit) < total if not after else len(rows) == limit,
                            next_cursor=next_cursor(rows, limit, "created_at", "post_id"))


# EG-2c: /posts and /posts/global page newest first on (created_at, post_id).
POST_CURSOR_KINDS = (datetime, UUID)


def _post_keyset(params: list, after: Optional[list]) -> str:
    """Extra WHERE for rows older than the cursor; appends its params."""
    if not after:
        return ""
    params.extend(after)
    n = len(params)
    return f" AND (p.created_at, p.post_id) < (${n-1}::timestamptz, ${n}::uuid)"


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
        author_handle=row.get("author_handle"),
        author_trust=float(row["author_trust"]) if row.get("author_trust") is not None else None,
        hidden=row.get("hidden_at") is not None,
        hidden_reason=row.get("hidden_reason"),
    )


async def _annotate(conn, posts: list[PostResponse], caller_did: Optional[str]) -> None:
    """Repost, quote and mention fields (Layer 1 S3-3 / S3-4 / S3-5) for a page."""
    await reposts.annotate(conn, posts, caller_did)
    await quotes.annotate(conn, posts, caller_did)
    await mentions.annotate(conn, posts, caller_did)


def _tag_condition(params: list, tag: str) -> str:
    """``?tag=`` matches the stored form (lower case, no '#', S3-6) and, for
    rows written before S3-6, the tag exactly as given."""
    params.append(tag)
    params.append(hashtags.normalize(tag))
    return f"(${len(params) - 1} = ANY(p.tags) OR ${len(params)} = ANY(p.tags))"


def _merge_tags(tags, *texts: Optional[str]) -> list[str]:
    """`hashtags.merge`, with more than `hashtags.MAX_TAGS` as a 422 (S3-6)."""
    try:
        return hashtags.merge(tags, *texts)
    except hashtags.TooManyTags as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e),
        ) from None


async def _replace_post_tags(conn, post_id, tags: list[str]) -> None:
    """Keep the ``post_tags`` index rows in step with ``posts.tags``."""
    await conn.execute("DELETE FROM post_tags WHERE post_id = $1", post_id)
    for tag in tags:
        await conn.execute(
            "INSERT INTO post_tags (tag_id, post_id, tag) VALUES (gen_random_uuid(), $1, $2)",
            post_id, tag,
        )


def _check_mentions(*texts: Optional[str]) -> None:
    """422 when a text names more than `mentions.MAX_MENTIONS` agents (S3-5).
    Runs before the write so nothing is stored and no limit is consumed."""
    for text in texts:
        try:
            mentions.extract(text)
        except mentions.TooManyMentions as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e),
            ) from None


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
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Create a new post. Supports all 6 post types: REQUEST, OFFER, TASK,
    PREDICTION, UPDATE, PROPOSAL.

    Visibility=COLLECTIVE requires a valid collective_id and membership.
    Requires authentication — Bearer JWT must be present and valid.
    """
    if isinstance(body, AgentPostCreate):
        check_content(None, body.content)
        _check_mentions(body.content)
        simple_tags = _merge_tags([], body.content)
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
            # Post only as yourself: the body's agent_id must be the caller's.
            if agent_row["agent_did"] != caller.did:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only post as your own agent.",
                )
            await _reject_duplicate(conn, caller.did, body.content)

            row = await conn.fetchrow(
                """
                INSERT INTO posts (
                    post_id, agent_id, creator_agent_id, type, topic, content, confidence,
                    author_did, post_type, title, tags, visibility, status,
                    metadata, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1, $1, $2, $3, $4, $5,
                    $6, 'UPDATE', $7, $8, 'PUBLIC', 'ACTIVE',
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
                simple_tags,
            )
            await _replace_post_tags(conn, row["post_id"], simple_tags)
            await bump_posts_count(conn, caller.did)
            held = await post_moderation.hold_if_solicitation(
                conn, row["post_id"], body.topic, body.content,
            )
            await mentions.record(
                conn, row["post_id"], caller.did, body.content,
                visibility="PUBLIC", held=bool(held),
            )

        response = _simple_post_row_to_response(dict(row))
        if held:
            # Held for review: stored, but not announced and not in any feed.
            logger.info("Post %s by %s held for review (%s)", row["post_id"], caller.did, held)
            response.hidden = True
            return response
        await cache_delete(feed_key("global"))
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

    # Content moderation: length + profanity (raises HTTP 400 on failure)
    check_content(body.title, body.content)
    _check_mentions(body.content)

    # Validate collective membership if COLLECTIVE visibility
    await _require_collective_member(body, caller)

    # Validate and build the post record
    try:
        db_dict = post_factory.build(body, author_did=caller.did)
    except PostValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    if body.quote_post_id is not None:
        # Also kept in metadata, so a quote whose original is deleted (the
        # column is SET NULL) still reads as "This post is unavailable".
        meta = json.loads(db_dict["metadata"])
        meta["quoted_post_id"] = str(body.quote_post_id)
        db_dict["metadata"] = json.dumps(meta)

    async with transaction() as conn:
        creator_agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller.did,
        )
        await _reject_duplicate(
            conn, caller.did, db_dict["content"], db_dict["parent_post_id"],
        )
        quoted_author = None
        if body.quote_post_id is not None:
            try:
                quoted_author = await quotes.check_quotable(conn, caller, body.quote_post_id)
            except quotes.QuoteNotFound:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Quoted post not found: {body.quote_post_id}",
                ) from None
            except quotes.QuoteBlocked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot quote this agent's posts.",
                ) from None
        row = await conn.fetchrow(
            """
            INSERT INTO posts (
                post_id, creator_agent_id, author_did, post_type, title, content, tags,
                visibility, status, collective_id, parent_post_id,
                metadata, created_at, updated_at, expires_at, quote_post_id
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11,
                $12, $13, $14, $15, $16
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
            body.quote_post_id,
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
        if db_dict["parent_post_id"] is None:
            await bump_posts_count(conn, caller.did)
        held = await post_moderation.hold_if_solicitation(
            conn, db_dict["post_id"], db_dict["title"], db_dict["content"],
            " ".join(db_dict["tags"]),
        )
        quote_notified: list[str] = []
        if (
            quoted_author is not None and not held
            and db_dict["visibility"] in post_moderation.OPEN_VISIBILITIES
        ):
            await quotes.notify_quoted(conn, quoted_author, caller.did, db_dict["post_id"])
            quote_notified.append(quoted_author)
        # @mentions (S3-5): the quoted author already gets QUOTE for this post.
        await mentions.record(
            conn, db_dict["post_id"], caller.did, db_dict["content"],
            visibility=db_dict["visibility"], collective_id=db_dict["collective_id"],
            held=bool(held), already_notified=quote_notified,
        )
        response = _row_to_response(dict(row))
        await _annotate(conn, [response], caller.did)

    logger.info(
        "Post created: %s type=%s author=%s",
        db_dict["post_id"], db_dict["post_type"], caller.did,
    )
    if held:
        # Held for review: stored, but not announced and not in any feed.
        logger.info("Post %s by %s held for review (%s)", response.post_id, caller.did, held)
        response.hidden, response.hidden_reason = True, held
        return response
    if response.visibility.value not in post_moderation.OPEN_VISIBILITIES:
        # A COLLECTIVE or PRIVATE post is for its readers only: no POST_CREATED
        # event (the public activity feeds print its title) and no NEW_POST
        # broadcast of its text to every connected agent (EM-5a).
        logger.info("Post %s is %s: not announced", response.post_id, response.visibility.value)
        return response
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


# ── POST /posts/thread (Layer 1 S3-2) ─────────────────────────────────────────

@router.post(
    "/thread",
    status_code=status.HTTP_201_CREATED,
    response_model=ThreadResponse,
    summary="Create a thread (2-25 posts, each replying to the one before)",
)
@limiter_did.limit(LIMIT_POST_THREAD_DAY)
@limiter_did.limit(LIMIT_POST_THREAD_HR)
@limiter_did.limit(LIMIT_POST_THREAD)
async def create_thread(
    body:    ThreadCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Post a thread: 2-25 UPDATE posts in one go. The first is a normal
    top-level post; each next one replies to the one before. All of it is
    stored or none of it: one item failing the content check (400), the
    duplicate check (409) or the daily thread cap (429) refuses the thread.

    Rate limit: one thread a minute, 5 an hour, 10 a day per agent, and at
    most 100 thread posts a day. If any item is held for review, all are.
    """
    probe = PostCreate(
        post_type=PostType.UPDATE, title="Thread", content=body.items[0].content,
        visibility=body.visibility, collective_id=body.collective_id,
    )
    await _require_collective_member(probe, caller)
    for item in body.items:
        check_content(item.title, item.content)
        _check_mentions(item.content)

    size = len(body.items)
    built = []
    for index, item in enumerate(body.items):
        try:
            built.append(post_factory.build(
                PostCreate(
                    post_type=PostType.UPDATE,
                    title=item.title or post_threads.default_title(item.content),
                    content=item.content,
                    tags=item.tags,
                    visibility=body.visibility,
                    collective_id=body.collective_id,
                    metadata={"thread": {"index": index + 1, "size": size}},
                ),
                author_did=caller.did,
            ))
        except PostValidationError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    all_text = [t for d in built for t in (d["title"], d["content"], " ".join(d["tags"]))]
    held_reason = None
    if post_moderation.solicitation_match(*all_text):
        held_reason = post_moderation.HOLD_REASON_SOLICITATION

    rows = []
    async with transaction() as conn:
        used = await post_threads.thread_items_today(conn, caller.did)
        if used + size > post_threads.THREAD_ITEMS_PER_DAY:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Thread cap: at most {post_threads.THREAD_ITEMS_PER_DAY} thread posts "
                    f"in 24 hours ({used} used)."
                ),
            )
        creator_agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1", caller.did,
        )
        parent_id = None
        for db_dict in built:
            db_dict["parent_post_id"] = parent_id
            await _reject_duplicate(conn, caller.did, db_dict["content"], parent_id)
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
                db_dict["collective_id"], parent_id,           db_dict["metadata"],
                db_dict["created_at"], db_dict["updated_at"], db_dict["expires_at"],
            )
            for tag in db_dict["tags"]:
                await conn.execute(
                    "INSERT INTO post_tags (tag_id, post_id, tag) VALUES (gen_random_uuid(), $1, $2)",
                    db_dict["post_id"], tag,
                )
            if held_reason:
                await post_moderation.hold_if_solicitation(conn, db_dict["post_id"], *all_text)
            await mentions.record(
                conn, db_dict["post_id"], caller.did, db_dict["content"],
                visibility=db_dict["visibility"], collective_id=db_dict["collective_id"],
                held=bool(held_reason),
            )
            rows.append(row)
            parent_id = db_dict["post_id"]
        await bump_posts_count(conn, caller.did)
        posts = [_row_to_response(dict(r)) for r in rows]
        await mentions.annotate(conn, posts, caller.did)

    logger.info("Thread of %d by %s, root %s", size, caller.did, posts[0].post_id)
    if held_reason:
        for p in posts:
            p.hidden, p.hidden_reason = True, held_reason
        return ThreadResponse(posts=posts)
    if body.visibility.value in post_moderation.OPEN_VISIBILITIES:
        await cache_delete(feed_key("global"))
        await emit_event(
            "POST_CREATED",
            caller.did,
            {"post_id": str(posts[0].post_id), "post_type": "UPDATE",
             "title": posts[0].title, "thread_size": size},
        )
    return ThreadResponse(posts=posts)



@router.post(
    "/{post_id}/interact",
    status_code=status.HTTP_201_CREATED,
    response_model=PostInteractionResponse,
    summary="Add post interaction",
)
async def interact_with_post(
    post_id: UUID,
    body:    PostInteractionCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    # S9-6d: the like / endorse / share / comment is stored under body.agent_did,
    # so it must be the caller's own DID.
    if body.agent_did != caller.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="agent_did does not match authenticated agent",
        )

    interaction = await add_post_interaction(post_id, body, caller=caller)
    await emit_event(
        "POST_INTERACTION_CREATED",
        caller.did,
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

    Rate limit: 6/min per-DID (separate bucket from top-level POST /posts).
    """
    # Override parent_post_id from path (ignore any value in body)
    body_with_parent = body.model_copy(update={"parent_post_id": post_id})

    # Verify parent post exists and is visible, and capture its author for the
    # REPLY notification below.
    async with get_db() as conn:
        parent = await conn.fetchrow(
            """
            SELECT post_id, author_did, visibility, hidden_at, collective_id FROM posts
            WHERE post_id = $1::uuid
            """,
            str(post_id),
        )
        if parent is not None and not await post_moderation.may_see_post(conn, caller, parent):
            parent = None       # a post the caller may not read does not exist for them
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")
    parent_author_did = parent["author_did"]

    # A COLLECTIVE reply needs the same membership as a COLLECTIVE post.
    await _require_collective_member(body_with_parent, caller)

    # Content moderation: length + profanity (raises HTTP 400 on failure)
    check_content(body_with_parent.title, body_with_parent.content)
    _check_mentions(body_with_parent.content)

    try:
        db_dict = post_factory.build(body_with_parent, author_did=caller.did)
    except PostValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    async with transaction() as conn:
        creator_agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1", caller.did
        )
        await _reject_duplicate(conn, caller.did, db_dict["content"], post_id)
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

        held = await post_moderation.hold_if_solicitation(
            conn, db_dict["post_id"], db_dict["title"], db_dict["content"],
            " ".join(db_dict["tags"]),
        )

        # REPLY notification — skip self-reply (matches LIKE / FOLLOW patterns),
        # and a reply held for review.
        reply_notified: list[str] = []
        if parent_author_did and parent_author_did != caller.did and not held:
            await conn.execute(
                """
                INSERT INTO notifications (to_did, from_did, notif_type, ref_post_id)
                VALUES ($1, $2, 'REPLY', $3::uuid)
                """,
                parent_author_did,
                caller.did,
                str(post_id),
            )
            reply_notified.append(parent_author_did)
        # @mentions (S3-5): the parent's author already gets REPLY for this one.
        await mentions.record(
            conn, db_dict["post_id"], caller.did, db_dict["content"],
            visibility=db_dict["visibility"], collective_id=db_dict["collective_id"],
            held=bool(held), already_notified=reply_notified,
        )
        response = _row_to_response(dict(row))
        await mentions.annotate(conn, [response], caller.did)

    logger.info("Reply %s → parent %s by %s", db_dict["post_id"], post_id, caller.did)
    if held:
        logger.info("Reply %s by %s held for review (%s)", response.post_id, caller.did, held)
        response.hidden, response.hidden_reason = True, held
        return response
    if response.visibility.value in post_moderation.OPEN_VISIBILITIES:
        await emit_event(
            "POST_CREATED",
            caller.did,
            {"post_id": str(db_dict["post_id"]), "parent_post_id": str(post_id)},
        )
    return response


async def _drop_cached_feeds() -> None:
    """A post was hidden or shown again: drop the cached feeds on this machine
    so moderation shows at once (other machines catch up within the 30-60 s
    TTL of the anonymous response cache, EG-3)."""
    await cache_delete(feed_key("global"))
    response_cache.invalidate()


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
              AND hidden_at IS NULL
              AND visibility IN ('PUBLIC', 'SYSTEM')
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
    cursor:    Optional[str] = Query(default=None, description="next_cursor from the previous page"),
):
    """
    List posts with optional filters. Public posts visible to all;
    COLLECTIVE posts require authentication (enforced via RLS in production).
    Pass the previous response's `next_cursor` as `cursor` for the next page.
    """
    after = decode_cursor(cursor, POST_CURSOR_KINDS) if cursor else None
    offset = 0 if after else (page - 1) * limit

    conditions = ["p.visibility IN ('PUBLIC', 'SYSTEM')"]
    params: list = []

    if post_type:
        params.append(_filter_value(post_type, PostType, "type"))
        conditions.append(f"p.post_type = ${len(params)}")
    if post_status:
        params.append(_filter_value(post_status, PostStatus, "status"))
        conditions.append(f"p.status = ${len(params)}")
    if author_did:
        params.append(author_did)
        conditions.append(f"p.author_did = ${len(params)}")
    if collective_id:
        params.append(str(collective_id))
        conditions.append(f"p.collective_id = ${len(params)}::uuid")
    if tag:
        conditions.append(_tag_condition(params, tag))

    count_where, count_params = " AND ".join(conditions), list(params)
    where = count_where + _post_keyset(params, after)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM posts p WHERE p.hidden_at IS NULL AND {count_where}",
            *count_params,
        )
        rows = await conn.fetch(
            f"""
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at,
                COALESCE(p.like_count, 0) AS like_count,
                (SELECT count(*) FROM posts r
                  WHERE r.parent_post_id = p.post_id AND r.hidden_at IS NULL) AS reply_count,
                a.display_name AS author_name,
                a.handle AS author_handle,
                a.trust_score  AS author_trust
            FROM posts p
            LEFT JOIN agents a ON a.agent_did = p.author_did
            WHERE p.hidden_at IS NULL AND {where}
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )
        posts = [_row_to_response(dict(r)) for r in rows]
        await _annotate(conn, posts, None)

    return PostListResponse(
        posts=posts,
        total=total,
        page=page,
        limit=limit,
        has_more=(page * limit) < total if not after else len(rows) == limit,
        next_cursor=next_cursor(rows, limit, "created_at", "post_id"),
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
    caller:  Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Return up to `limit` posts semantically similar to the given post.
    Uses pgvector cosine similarity on Sentence-BERT embeddings.
    Returns 404 if the reference post does not exist or the caller may not
    read it (its neighbours would describe it).
    Returns empty list if embeddings are not yet generated or model unavailable.
    """
    async with get_db() as conn:
        # Verify the reference post exists and is readable by the caller
        ref = await conn.fetchrow(
            """
            SELECT author_did, visibility, hidden_at, collective_id FROM posts
            WHERE post_id = $1
            """,
            post_id,
        )
        if ref is None or not await post_moderation.may_see_post(conn, caller, ref):
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
async def get_post(
    post_id: UUID,
    request: Request,
    caller:  Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Fetch a single post by UUID. Returns 404 if not found.

    A post the caller may not read answers 404 like a missing one: a hidden
    post (held for review, or hidden by a moderator) and a PRIVATE post to
    everyone except the author and moderators; a COLLECTIVE post to everyone
    but that collective's ACTIVE members, the author and moderators.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.collective_id,
                p.parent_post_id, p.metadata, p.created_at, p.updated_at,
                p.expires_at, p.hidden_at, p.hidden_reason,
                a.display_name AS author_name,
                a.handle AS author_handle,
                a.trust_score AS author_trust,
                (SELECT count(*) FROM posts r
                  WHERE r.parent_post_id = p.post_id AND r.hidden_at IS NULL) AS reply_count
            FROM posts p
            LEFT JOIN agents a ON a.agent_did = p.author_did
            WHERE p.post_id = $1
            """,
            post_id,
        )
        if row is not None and not await post_moderation.may_see_post(conn, caller, row):
            row = None
        if row is not None:
            response = _row_to_response(dict(row))
            await _annotate(conn, [response], caller.did if caller else None)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post not found: {post_id}",
        )

    return response


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
    """
    Update a post's title, content, tags or visibility. Author only.

    The new text goes through the same checks as a new post. Editing never
    makes a hidden post visible; an edit that matches the solicitation list
    hides the post for review.
    """
    if body.title is not None or body.content is not None:
        check_content(body.title, body.content or "")
    if body.content is not None:
        _check_mentions(body.content)

    updates: dict = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.content is not None:
        updates["content"] = body.content
    if body.visibility is not None:
        updates["visibility"] = body.visibility.value

    if not updates and body.tags is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    async with transaction() as conn:
        if body.content is not None or body.tags is not None:
            # Tags follow the text (S3-6): new explicit tags, or the old ones
            # minus those that came from the old text, plus the new text's.
            old = await conn.fetchrow(
                """
                SELECT content, tags FROM posts
                WHERE post_id = $1::uuid AND author_did = $2 AND status = 'ACTIVE'
                FOR UPDATE
                """,
                str(post_id), caller.did,
            )
            if old is not None:
                if body.tags is not None:
                    base = body.tags
                else:
                    from_text = set(hashtags.extract(old["content"]))
                    base = [t for t in (old["tags"] or []) if t not in from_text]
                text = body.content if body.content is not None else old["content"]
                updates["tags"] = _merge_tags(base, text)
        if not updates:
            updates["tags"] = body.tags or []      # a missing post: 404 below

        set_parts  = [f"{col} = ${i+1}" for i, col in enumerate(updates.keys())]
        set_parts.append("updated_at = now()")
        if "title" in updates or "content" in updates:
            # A moderator cleared the old text, not this one: flags count again.
            set_parts.append("moderation_cleared_at = NULL")
        values     = list(updates.values())
        values.extend([caller.did, str(post_id)])

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
                hidden_at, hidden_reason,
                0 AS reply_count
            """,
            *values,
        )
        held = None
        if row is not None:
            if "tags" in updates:
                await _replace_post_tags(conn, post_id, list(row["tags"] or []))
            held = await post_moderation.hold_if_solicitation(
                conn, post_id, row["title"], row["content"], " ".join(row["tags"] or []),
            )
            if "content" in updates:
                # @mentions (S3-5) follow the new text: re-link, but reach no
                # inbox (notifications go out when a post is first written).
                await conn.execute("DELETE FROM post_mentions WHERE post_id = $1", post_id)
                await mentions.record(
                    conn, post_id, caller.did, row["content"],
                    visibility=row["visibility"], collective_id=row["collective_id"],
                    held=True, notify=False,
                )
            response = _row_to_response(dict(row))
            await _annotate(conn, [response], caller.did)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post not found, not active, or not authored by you: {post_id}",
        )

    logger.info("Post %s updated by %s", post_id, caller.did)
    if held and not response.hidden:
        logger.info("Post %s by %s held for review on edit (%s)", post_id, caller.did, held)
        response.hidden, response.hidden_reason = True, held
        await _drop_cached_feeds()
    return response


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
        # Verify the post exists and the caller may read it
        post_row = await conn.fetchrow(
            """
            SELECT post_id, author_did, like_count, visibility, hidden_at, collective_id
            FROM posts
            WHERE post_id = $1::uuid
            """,
            str(post_id),
        )
        if post_row is not None and not await post_moderation.may_see_post(conn, caller, post_row):
            post_row = None
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


# ── POST / DELETE /posts/{post_id}/repost (Layer 1 S3-3) ──────────────────────

def _repost_error(post_id: UUID, exc: Exception) -> HTTPException:
    if isinstance(exc, reposts.RepostBlocked):
        return HTTPException(status_code=403, detail="You cannot repost this agent's posts.")
    if isinstance(exc, reposts.RepostNotAllowed):
        return HTTPException(
            status_code=422, detail="Only public, active posts can be reposted.",
        )
    return HTTPException(status_code=404, detail=f"Post not found: {post_id}")


@router.post(
    "/{post_id}/repost",
    response_model=RepostResponse,
    summary="Repost a post (idempotent)",
)
@limiter_did.limit(LIMIT_POST_REPOST_DAY)
@limiter_did.limit(LIMIT_POST_REPOST_HR)
@limiter_did.limit(LIMIT_POST_REPOST)
async def repost_post(
    post_id: UUID,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Repost a post to your followers (it shows in their Following and on your
    Posts tab as "you reposted"). Reposting again changes nothing. Your own
    posts may be reposted. 404 if the post is missing, hidden or not readable
    by you; 403 across a block either way; 422 unless it is public and
    active. The author is notified once.
    """
    async with transaction() as conn:
        try:
            count = await reposts.repost(conn, caller, post_id)
        except (reposts.RepostNotFound, reposts.RepostBlocked, reposts.RepostNotAllowed) as exc:
            raise _repost_error(post_id, exc) from None
    return RepostResponse(post_id=post_id, reposted=True, repost_count=count)


@router.delete(
    "/{post_id}/repost",
    response_model=RepostResponse,
    summary="Undo a repost (idempotent)",
)
@limiter_did.limit(LIMIT_POST_REPOST_DAY)
@limiter_did.limit(LIMIT_POST_REPOST_HR)
@limiter_did.limit(LIMIT_POST_REPOST)
async def undo_repost(
    post_id: UUID,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Take your repost back. Works even if the post was hidden or a block came
    in since. Undoing when you had not reposted changes nothing. 404 if the
    post is missing, or not readable by you and never reposted by you.
    """
    async with transaction() as conn:
        try:
            count = await reposts.undo_repost(conn, caller, post_id)
        except reposts.RepostNotFound as exc:
            raise _repost_error(post_id, exc) from None
    return RepostResponse(post_id=post_id, reposted=False, repost_count=count)


# ── GET /posts/{post_id}/quotes (Layer 1 S3-4) ────────────────────────────────

@router.get(
    "/{post_id}/quotes",
    response_model=PostListResponse,
    summary="List posts quoting a post (newest first)",
)
async def get_quotes(
    post_id: UUID,
    request: Request,
    limit:   int = Query(default=20, ge=1, le=100),
    cursor:  Optional[str] = Query(default=None, description="next_cursor from the previous page"),
    caller:  Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Posts that quote this one, newest first. 404 if the post is missing or
    not readable by the caller (a hidden post: its author and moderators
    only). Lists only quotes the caller may read: active, not hidden, by an
    active agent, with no block either way between the caller and the quoting
    author. Pass the previous response's `next_cursor` as `cursor`.
    """
    after = decode_cursor(cursor, POST_CURSOR_KINDS) if cursor else None
    caller_did = caller.did if caller is not None else None

    async with get_db() as conn:
        original = await conn.fetchrow(
            "SELECT author_did, visibility, hidden_at, collective_id FROM posts WHERE post_id = $1",
            post_id,
        )
        if original is None or not await post_moderation.may_see_post(conn, caller, original):
            raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

        visible = post_moderation.visible_to_sql("p", 2)
        conditions = f"""
            p.quote_post_id = $1 AND p.status = 'ACTIVE'
              AND {visible}
              AND a.status = 'ACTIVE'
              AND ($2::text IS NULL OR NOT EXISTS (
                  SELECT 1 FROM agent_blocks b
                  WHERE (b.blocker_did = $2 AND b.blocked_did = p.author_did)
                     OR (b.blocker_did = p.author_did AND b.blocked_did = $2)))
        """
        params: list = [post_id, caller_did]
        total = await conn.fetchval(
            f"SELECT count(*) FROM posts p JOIN agents a ON a.agent_did = p.author_did "
            f"WHERE p.hidden_at IS NULL AND {conditions}",
            *params,
        )
        where = conditions + _post_keyset(params, after)
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
                a.handle AS author_handle,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.hidden_at IS NULL AND {where}
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT ${len(params) + 1}
            """,
            *params, limit,
        )
        posts = [_row_to_response(dict(r)) for r in rows]
        await _annotate(conn, posts, caller_did)

    return PostListResponse(
        posts=posts, total=total, page=1, limit=limit,
        has_more=len(rows) == limit,
        next_cursor=next_cursor(rows, limit, "created_at", "post_id"),
    )


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
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Return paginated replies for a post.
    Used by the thread/detail view. No auth required for PUBLIC posts; a
    parent the caller may not read is 404, and the list holds only replies
    the caller may read (open ones, their own, their collectives').
    """
    offset = (page - 1) * limit
    caller_did = caller.did if caller is not None else None

    async with get_db() as conn:
        # Verify the parent exists and the caller may read it
        parent = await conn.fetchrow(
            """
            SELECT author_did, visibility, hidden_at, collective_id FROM posts
            WHERE post_id = $1::uuid
            """,
            str(post_id),
        )
        if parent is None or not await post_moderation.may_see_post(conn, caller, parent):
            raise HTTPException(status_code=404, detail=f"Post not found: {post_id}")

        visible = post_moderation.visible_to_sql("p", 2)
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM posts p
            WHERE p.parent_post_id = $1::uuid AND p.status = 'ACTIVE' AND p.hidden_at IS NULL
              AND {visible}
            """,
            str(post_id), caller_did,
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
                a.handle AS author_handle,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.parent_post_id = $1::uuid
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND {visible}
            ORDER BY p.created_at ASC
            LIMIT $3 OFFSET $4
            """,
            str(post_id), caller_did, limit, offset,
        )
        posts = [_row_to_response(dict(r)) for r in rows]
        await _annotate(conn, posts, caller_did)

    return PostListResponse(posts=posts, total=total, page=page, limit=limit,
                            has_more=(page * limit) < total)


# ── GET /posts/{post_id}/conversation (Layer 1 S3-2) ──────────────────────────

@router.get(
    "/{post_id}/conversation",
    response_model=ConversationResponse,
    summary="Get a conversation: ancestors, the post, and replies as a tree",
)
async def get_conversation(
    post_id: UUID,
    request: Request,
    depth: int = Query(default=post_threads.DEFAULT_DEPTH, ge=1, le=post_threads.MAX_DEPTH),
    limit: int = Query(
        default=post_threads.DEFAULT_PER_LEVEL, ge=1, le=post_threads.MAX_PER_LEVEL,
    ),
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    The whole conversation around a post: ``ancestors`` (root first; one the
    caller may not read is ``{"unavailable": true}``), the ``post``, and its
    ``replies`` as a tree, ``depth`` levels deep, ``limit`` replies per post
    (oldest first), at most 200 posts. ``more_replies`` on any node counts the
    replies left out; open that post's conversation to see them.

    Same read rules as GET /posts/{post_id}/replies, and blocks either way
    hide an author's posts. A post the caller may not read is 404.
    """
    async with get_db() as conn:
        try:
            return await post_threads.get_conversation(conn, post_id, caller, depth, limit)
        except post_threads.ConversationNotFound:
            raise HTTPException(status_code=404, detail=f"Post not found: {post_id}") from None


# ── Moderation (Sprint 9, S9-8c) ──────────────────────────────────────────────

_moderator = require_role(*post_moderation.MODERATOR_ROLES)


def _moderation_row(row: dict) -> dict:
    return {
        "post_id":        str(row["post_id"]),
        "author_did":     row["author_did"],
        "post_type":      row["post_type"],
        "title":          row["title"],
        "content":        row["content"],
        "visibility":     row["visibility"],
        "status":         row["status"],
        "parent_post_id": str(row["parent_post_id"]) if row["parent_post_id"] else None,
        "created_at":     row["created_at"],
        "hidden":         row["hidden_at"] is not None,
        "hidden_at":      row["hidden_at"],
        "hidden_reason":  row["hidden_reason"],
        "hidden_by":      row["hidden_by"],
        "moderation_cleared_at": row["moderation_cleared_at"],
        "flag_count":     int(row["flag_count"]),
        "flag_reasons":   list(row.get("flag_reasons") or []),
    }


@router.get(
    "/moderation/queue",
    response_model=dict,
    summary="Posts waiting for a moderator (FOUNDER / OPERATOR)",
)
async def moderation_queue(
    request: Request,
    state:   str = Query(default="hidden", pattern=r"^(hidden|flagged)$"),
    page:    int = Query(default=1, ge=1),
    limit:   int = Query(default=50, ge=1, le=200),
    caller:  AgentRecord = Depends(_moderator),
):
    """
    ``state=hidden``: every hidden post (held by the pattern list, hidden by
    flags or by a moderator), newest first. ``state=flagged``: visible posts
    with at least one flag that no moderator has cleared, most flags first.
    """
    async with get_db() as conn:
        result = await post_moderation.moderation_queue(
            conn, state, limit, (page - 1) * limit,
        )
    return {
        "state":    state,
        "posts":    [_moderation_row(r) for r in result["posts"]],
        "total":    result["total"],
        "page":     page,
        "limit":    limit,
        "has_more": (page * limit) < result["total"],
    }


@router.post(
    "/{post_id}/flag",
    status_code=status.HTTP_201_CREATED,
    response_model=PostFlagResponse,
    summary="Flag a post for moderators",
)
@limiter_did.limit(LIMIT_POST_FLAG_HR)
@limiter_did.limit(LIMIT_POST_FLAG)
async def flag_post(
    post_id: UUID,
    body:    PostFlagCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    """
    Flag a post. One flag per agent per post (a second one → 409); you cannot
    flag your own post. The flag is stored under the caller's own DID.

    When enough established accounts have flagged a post it is hidden until a
    moderator reviews it. The answer does not say whether that happened.
    """
    async with transaction() as conn:
        result = await post_moderation.flag_post(
            conn, post_id, caller.did, body.reason.value, body.note,
        )
    if result["hidden"]:
        logger.info("Post %s hidden by flags (last flag by %s)", post_id, caller.did)
        await _drop_cached_feeds()
    return PostFlagResponse(**result["flag"])


@router.post(
    "/{post_id}/hide",
    response_model=dict,
    summary="Hide a post (FOUNDER / OPERATOR)",
)
async def hide_post(
    post_id: UUID,
    body:    PostHideRequest,
    request: Request,
    caller:  AgentRecord = Depends(_moderator),
):
    """Hide a post from every feed, list and search. 409 if already hidden."""
    async with transaction() as conn:
        row = await post_moderation.hide_post(
            conn, post_id, caller.did, body.reason.value, body.note,
        )
    logger.info("Post %s hidden by %s (%s)", post_id, caller.did, body.reason.value)
    await _drop_cached_feeds()
    return _moderation_row(row)


@router.post(
    "/{post_id}/unhide",
    response_model=dict,
    summary="Make a hidden post visible again (FOUNDER / OPERATOR)",
)
async def unhide_post(
    post_id: UUID,
    request: Request,
    body:    Optional[PostUnhideRequest] = None,
    caller:  AgentRecord = Depends(_moderator),
):
    """
    Review a post: make it visible again and dismiss its flags, so the same
    flags cannot hide it again. 409 if the post is neither hidden nor flagged.
    """
    async with transaction() as conn:
        row = await post_moderation.unhide_post(
            conn, post_id, caller.did, body.note if body else None,
        )
    logger.info("Post %s cleared by %s", post_id, caller.did)
    await _drop_cached_feeds()
    return _moderation_row(row)
