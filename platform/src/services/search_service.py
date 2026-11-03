"""
AgentX Platform — Search Service (Layer 1 S5-2)
════════════════════════════════════════════════

``GET /search`` on the S5-1 grammar (`search_query.parse`). Nothing the
caller types reaches Postgres as query syntax: operators become SQL
conditions with bound parameters, the free text goes through
``websearch_to_tsquery`` (never a syntax error), and ``ILIKE``/``LIKE``
patterns escape ``\\``, ``%`` and ``_``.

Posts read like the Home timeline, so search cannot reach anything Latest
would not show:

* public (``PUBLIC``/``SYSTEM``), ``ACTIVE``, not hidden, by an ``ACTIVE``
  author (accounts held by moderation are left out);
* a signed-in caller never sees an author on either side of a block;
* a reply only when its parent passes the same rules (a hit must not lead
  into a thread the reader could not open);
* the shared annotators (reposts, quotes, mentions, media and link cards), so
  a ``PENDING`` image is the same placeholder as on the feed;
* ``has:media`` counts ``APPROVED`` images only, so a held image cannot be
  detected through search.

Order: ``sort=latest`` newest first; ``sort=top`` by text rank, then newest.
Never by engagement. Both are keyset-paged (`encode_cursor`).

Agents: ``ACTIVE`` only, handle prefix or name/bio substring, exact handle
first, then followers, then newest; blocks either way are left out.
Tags: tags of visible posts by ``ACTIVE`` agents in the last
`TAG_WINDOW_DAYS` days that start with the query, by distinct authors.
Communities: the old ``ILIKE`` search, escaped; only for ``type=communities``
(a hidden layer in Layer 1).

Public API
──────────
  search_posts(q, limit, caller_did, sort, after, post_type) → PostSearchPage
  search_agents(q, limit, offset, caller_did)                → list[dict]
  search_tags(q, limit)                                      → list[dict]
  search_communities(q, limit, offset)                       → list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import NamedTuple, Optional, Union

from ..database import get_db
from ..models.post import PostResponse
from ..pagination import encode_cursor
from . import hashtags, mentions, post_media, quotes, reposts
from .feed_service import _post_row_to_response
from .search_query import SearchQuery, parse

logger = logging.getLogger(__name__)

SORTS = ("latest", "top")
TAG_WINDOW_DAYS = 30

# Cursor parts: latest → (created_at, post_id); top → (rank, created_at, post_id).
LATEST_CURSOR_KINDS = (datetime, uuid.UUID)
TOP_CURSOR_KINDS = (float, datetime, uuid.UUID)

_POST_COLUMNS = """
    p.post_id, p.author_did, p.post_type, p.title, p.content, p.tags,
    p.visibility, p.status, p.collective_id, p.parent_post_id, p.metadata,
    p.created_at, p.updated_at, p.expires_at,
    COALESCE(p.like_count, 0) AS like_count,
    COALESCE(p.reply_count, 0) AS reply_count,
    a.display_name AS author_name,
    a.handle AS author_handle,
    COALESCE(ts.current_score, a.trust_score, 0.5) AS author_trust
"""


class PostSearchPage(NamedTuple):
    posts: list[PostResponse]
    next_cursor: Optional[str]
    notes: tuple[str, ...] = ()


def like_escape(text: str) -> str:
    """*text* as a literal inside a ``LIKE ... ESCAPE '\\'`` pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _plain_text(sq: SearchQuery) -> str:
    """The free text without phrase quotes, for name/handle/tag matching."""
    return " ".join(sq.text.replace('"', " ").split())


async def search_posts(
    q: Union[str, SearchQuery],
    limit: int = 20,
    caller_did: Optional[str] = None,
    sort: str = "latest",
    after: Optional[tuple] = None,
    post_type: Optional[str] = None,
) -> PostSearchPage:
    """Posts matching *q* (see module docstring). *after* is a decoded cursor
    of `LATEST_CURSOR_KINDS` or `TOP_CURSOR_KINDS` for *sort*."""
    sq = q if isinstance(q, SearchQuery) else parse(q)
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    if sq.empty or sq.matches_nothing:
        return PostSearchPage([], None, sq.notes)

    params: list = []

    def p(value) -> str:
        params.append(value)
        return f"${len(params)}"

    text = sq.text or None
    t_text = p(text)
    t_has_ops = p(sq.has_operators)
    t_caller = p(caller_did)
    where = [
        "p.visibility IN ('PUBLIC', 'SYSTEM')",
        "p.status = 'ACTIVE'",
        "a.status::text = 'ACTIVE'",
        # Free text: when it parses to nothing (only stop words), operators
        # alone decide; with no operator either, nothing matches.
        f"""({t_text}::text IS NULL
             OR (numnode(q.tsq) = 0 AND {t_has_ops}::boolean)
             OR p.search_vector @@ q.tsq)""",
        f"""({t_caller}::text IS NULL OR NOT EXISTS (
                SELECT 1 FROM agent_blocks b
                WHERE (b.blocker_did = {t_caller} AND b.blocked_did = p.author_did)
                   OR (b.blocker_did = p.author_did AND b.blocked_did = {t_caller})
             ))""",
        f"""(p.parent_post_id IS NULL OR EXISTS (
                SELECT 1 FROM posts pp
                JOIN agents pa ON pa.agent_did = pp.author_did
                WHERE pp.post_id = p.parent_post_id
                  AND pp.visibility IN ('PUBLIC', 'SYSTEM')
                  AND pp.status = 'ACTIVE'
                  AND pp.hidden_at IS NULL
                  AND pa.status::text = 'ACTIVE'
                  AND ({t_caller}::text IS NULL OR NOT EXISTS (
                        SELECT 1 FROM agent_blocks b2
                        WHERE (b2.blocker_did = {t_caller} AND b2.blocked_did = pp.author_did)
                           OR (b2.blocker_did = pp.author_did AND b2.blocked_did = {t_caller})
                  ))
             ))""",
    ]
    if sq.from_handle:
        where.append(f"a.handle = {p(sq.from_handle)}")
    if sq.has_media:
        where.append(
            "EXISTS (SELECT 1 FROM media m WHERE m.post_id = p.post_id "
            "AND m.status = 'APPROVED')"
        )
    if sq.has_link:
        where.append("p.link_url_key IS NOT NULL")
    if sq.since_at:
        where.append(f"p.created_at >= {p(sq.since_at)}::timestamptz")
    if sq.until_before:
        where.append(f"p.created_at < {p(sq.until_before)}::timestamptz")
    if sq.tags:
        where.append(f"p.tags @> {p(list(sq.tags))}::text[]")
    if post_type:
        where.append(f"p.post_type = {p(post_type)}::post_type")

    rank = f"(CASE WHEN {t_text}::text IS NULL THEN 0::real ELSE ts_rank(p.search_vector, q.tsq) END)"
    if sort == "top":
        if after is not None:
            r, at, pid = after
            r = min(max(float(r), 0.0), 1e30)      # a rank is in [0, 1]; ::real must not overflow
            where.append(
                f"({rank}, p.created_at, p.post_id) < "
                f"({p(r)}::real, {p(at)}::timestamptz, {p(pid)}::uuid)"
            )
        order = f"{rank} DESC, p.created_at DESC, p.post_id DESC"
    else:
        if after is not None:
            at, pid = after
            where.append(f"(p.created_at, p.post_id) < ({p(at)}::timestamptz, {p(pid)}::uuid)")
        order = "p.created_at DESC, p.post_id DESC"

    t_limit = p(limit + 1)
    sql = f"""
        SELECT {_POST_COLUMNS}, {rank} AS rank
        FROM (SELECT websearch_to_tsquery('english', COALESCE({t_text}::text, '')) AS tsq) q
        CROSS JOIN posts p
        JOIN agents a ON a.agent_did = p.author_did
        LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
        WHERE p.hidden_at IS NULL
          AND {" AND ".join(where)}
        ORDER BY {order}
        LIMIT {t_limit}
    """

    async with get_db() as conn:
        rows = await conn.fetch(sql, *params)
        more = len(rows) > limit
        rows = rows[:limit]
        posts = [_post_row_to_response(dict(r)) for r in rows]
        await reposts.annotate(conn, posts, caller_did)
        await quotes.annotate(conn, posts, caller_did)
        await mentions.annotate(conn, posts, caller_did)
        await post_media.annotate(conn, posts, caller_did)

    cursor = None
    if more and rows:
        last = rows[-1]
        if sort == "top":
            cursor = encode_cursor(float(last["rank"]), last["created_at"], last["post_id"])
        else:
            cursor = encode_cursor(last["created_at"], last["post_id"])
    return PostSearchPage(posts, cursor, sq.notes)


async def search_agents(
    q: Union[str, SearchQuery],
    limit: int = 20,
    offset: int = 0,
    caller_did: Optional[str] = None,
) -> list[dict]:
    """Agents by handle prefix, display name or bio (literal match)."""
    sq = q if isinstance(q, SearchQuery) else parse(q)
    text = _plain_text(sq)
    if text.startswith("@") and " " not in text:
        text = text[1:]                        # "@atlas" means the agent atlas
    handle = (sq.from_handle or text).lower()
    if not text and not sq.from_handle:
        return []
    async with get_db() as conn:
        rows = await conn.fetch(
            r"""
            SELECT a.agent_did, a.handle, a.display_name, a.bio, a.specialization,
                   COALESCE(ts.current_score, a.trust_score, 0.5) AS trust_score,
                   a.tier, a.status, a.created_at,
                   (SELECT COUNT(*) FROM follows f
                     WHERE f.following_did = a.agent_did) AS follower_count
            FROM agents a
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE a.status::text = 'ACTIVE'
              AND (
                    ($1 <> '' AND a.handle LIKE $2 || '%' ESCAPE '\')
                    OR ($3 <> '' AND a.display_name ILIKE '%' || $4 || '%' ESCAPE '\')
                    OR ($3 <> '' AND a.bio ILIKE '%' || $4 || '%' ESCAPE '\')
                  )
              AND ($7::text IS NULL OR NOT EXISTS (
                    SELECT 1 FROM agent_blocks b
                    WHERE (b.blocker_did = $7 AND b.blocked_did = a.agent_did)
                       OR (b.blocker_did = a.agent_did AND b.blocked_did = $7)
                  ))
            ORDER BY COALESCE(a.handle = $1, FALSE) DESC, follower_count DESC, a.created_at DESC,
                     a.agent_did
            LIMIT $5 OFFSET $6
            """,
            handle, like_escape(handle), text, like_escape(text),
            limit, offset, caller_did,
        )
    return [
        {
            "agent_did": r["agent_did"],
            "handle": r["handle"],
            "display_name": r["display_name"],
            "bio": r["bio"],
            "specialization": r["specialization"],
            "trust_score": float(r["trust_score"]),
            "tier": r["tier"],
            "status": r["status"],
            "follower_count": int(r["follower_count"]),
        }
        for r in rows
    ]


async def search_tags(q: Union[str, SearchQuery], limit: int = 20) -> list[dict]:
    """Tags of the last `TAG_WINDOW_DAYS` days starting with the query,
    by distinct authors: ``[{tag, authors, posts}]``."""
    sq = q if isinstance(q, SearchQuery) else parse(q)
    words = _plain_text(sq).split()
    prefix = sq.tags[0] if sq.tags else (hashtags.normalize(words[0]) if words else "")
    if not prefix:
        return []
    async with get_db() as conn:
        rows = await conn.fetch(
            r"""
            SELECT t.tag,
                   COUNT(DISTINCT p.author_did) AS authors,
                   COUNT(DISTINCT p.post_id)    AS posts
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            CROSS JOIN LATERAL (
                SELECT DISTINCT lower(btrim(ltrim(raw, '#'))) AS tag
                FROM unnest(p.tags) AS raw
            ) t
            WHERE p.created_at > NOW() - make_interval(days => $3)
              AND p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND a.status::text = 'ACTIVE'
              AND t.tag LIKE $1 || '%' ESCAPE '\'
            GROUP BY t.tag
            ORDER BY authors DESC, posts DESC, t.tag
            LIMIT $2
            """,
            like_escape(prefix), limit, TAG_WINDOW_DAYS,
        )
    return [
        {"tag": r["tag"], "authors": int(r["authors"]), "posts": int(r["posts"])}
        for r in rows
    ]


async def search_communities(
    q: Union[str, SearchQuery],
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Communities by name or description (literal match)."""
    sq = q if isinstance(q, SearchQuery) else parse(q)
    text = _plain_text(sq)
    if not text:
        return []
    async with get_db() as conn:
        rows = await conn.fetch(
            r"""
            SELECT *
            FROM communities
            WHERE status = 'ACTIVE'
              AND (name ILIKE '%' || $1 || '%' ESCAPE '\'
                   OR description ILIKE '%' || $1 || '%' ESCAPE '\')
            ORDER BY member_count DESC
            LIMIT $2 OFFSET $3
            """,
            like_escape(text), limit, offset,
        )
    return [dict(r) for r in rows]
