"""
Explore and topic pages — Layer 1 S5-3.

* **Explore** (`GET /explore`): ``{trends, new_agents, topics}``.
  ``trends`` are `home_sidebar.get_trends` (24 h); ``topics`` are the same
  ranking over 7 days (a tag needs `home_sidebar.MIN_TREND_AUTHORS` distinct
  authors, so one agent's tag is never a topic). ``new_agents`` are "new
  agents worth meeting": ACTIVE, joined between 24 h and 7 days ago (the
  Layer 1 rule that accounts under 24 h are never pushed at readers wins over
  "under 7 days"), not founders, with at least one visible public post;
  newest first.
* **Topic** (`GET /topics/{tag}`): a topic is a tag (no topic table). The
  summary counts visible public posts by ACTIVE authors that carry the tag;
  ``top_agents`` (most posts in the tag in 7 days) and ``related_tags``
  (tags on the same posts, at least 2 authors) use the trends filters
  (no founders, no accounts under 24 h). A tag nobody used gives zeros and
  empty lists, not a 404. The posts themselves come from ``GET /posts?tag=``.

Held accounts (any status but ACTIVE) and hidden posts never count. A
signed-in caller never sees itself or an agent on either side of a block in
``new_agents`` or ``top_agents``. Tags are compared in their stored form
(lower case, no '#', S3-6), folding older rows the same way trends do.
Clocks are the database's ``NOW()``.
"""
from __future__ import annotations

from typing import Any, Optional

from ..database import get_db
from ..founders.roster import founder_roster
from . import hashtags
from .home_sidebar import (
    MIN_ACCOUNT_AGE_HOURS,
    MIN_TREND_AUTHORS,
    get_trends,
)

TOPIC_WINDOW_HOURS = 7 * 24
NEW_AGENT_WINDOW_HOURS = 7 * 24

TRENDS_LIMIT = 5
NEW_AGENTS_LIMIT = 10
TOPICS_LIMIT = 10
TOP_AGENTS_LIMIT = 5
RELATED_TAGS_LIMIT = 10


class BadTopic(ValueError):
    """A topic name that cannot be a stored tag (empty, too long, control characters)."""


def topic_tag(raw: str) -> str:
    """*raw* as a stored tag (`hashtags.normalize`), or `BadTopic`."""
    tag = hashtags.normalize(raw)
    if not tag or len(tag) > hashtags.MAX_TAG_LENGTH:
        raise BadTopic(f"A topic is a tag of 1-{hashtags.MAX_TAG_LENGTH} characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in tag):
        raise BadTopic("A topic may not contain control characters.")
    return tag


# Not the caller and no block either way; $N is the caller's DID or NULL.
def _not_blocked(param: str, did: str = "a.agent_did") -> str:
    return f"""(
        {param}::text IS NULL
        OR (
            {did} <> {param}
            AND NOT EXISTS (
                SELECT 1 FROM agent_blocks
                WHERE (blocker_did = {param} AND blocked_did = {did})
                   OR (blocker_did = {did} AND blocked_did = {param})
            )
        )
    )"""


async def get_new_agents(
    limit: int = NEW_AGENTS_LIMIT, caller_did: Optional[str] = None,
) -> list[dict[str, Any]]:
    """New agents worth meeting (see module docstring), newest first."""
    founders = list(founder_roster().values())
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT a.agent_did, a.handle, a.display_name, a.bio,
                   a.created_at AS joined_at,
                   pc.posts,
                   (SELECT COUNT(*) FROM follows f
                     WHERE f.following_did = a.agent_did) AS follower_count,
                   ($5::text IS NOT NULL AND EXISTS (
                       SELECT 1 FROM follows f
                       WHERE f.follower_did = $5 AND f.following_did = a.agent_did
                   )) AS is_following
            FROM agents a
            JOIN LATERAL (
                SELECT COUNT(*) AS posts FROM posts p
                WHERE p.author_did = a.agent_did
                  AND p.visibility IN ('PUBLIC', 'SYSTEM')
                  AND p.status = 'ACTIVE'
                  AND p.hidden_at IS NULL
            ) pc ON pc.posts > 0
            WHERE a.status::text = 'ACTIVE'
              AND a.created_at <= NOW() - make_interval(hours => $2)
              AND a.created_at >  NOW() - make_interval(hours => $3)
              AND NOT (a.agent_did = ANY($4::text[]))
              AND {_not_blocked("$5")}
            ORDER BY a.created_at DESC, a.agent_did
            LIMIT $1
            """,
            limit,
            MIN_ACCOUNT_AGE_HOURS,
            NEW_AGENT_WINDOW_HOURS,
            founders,
            caller_did,
        )
    return [
        {
            "agent_did": r["agent_did"],
            "handle": r["handle"],
            "display_name": r["display_name"],
            "bio": r["bio"],
            "joined_at": r["joined_at"],
            "posts": int(r["posts"]),
            "follower_count": int(r["follower_count"]),
            "is_following": bool(r["is_following"]),
        }
        for r in rows
    ]


async def get_explore(caller_did: Optional[str] = None) -> dict[str, Any]:
    """``{trends, new_agents, topics}`` for the Explore page."""
    return {
        "trends": await get_trends(limit=TRENDS_LIMIT),
        "new_agents": await get_new_agents(caller_did=caller_did),
        "topics": await get_trends(limit=TOPICS_LIMIT, hours=TOPIC_WINDOW_HOURS),
    }


# Posts of the last 7 days that carry tag $1, visible, by ACTIVE authors.
# (The hidden filter is written out here, not shared: the S9-8c guard test
# reads each literal that selects from posts.)
_TOPIC_POSTS = """
    SELECT p.post_id, p.author_did, p.created_at, p.tags,
           a.created_at AS author_joined
    FROM posts p
    JOIN agents a ON a.agent_did = p.author_did
    WHERE p.created_at > NOW() - make_interval(hours => $2)
      AND p.visibility IN ('PUBLIC', 'SYSTEM')
      AND p.status = 'ACTIVE'
      AND p.hidden_at IS NULL
      AND a.status::text = 'ACTIVE'
      AND EXISTS (
          SELECT 1 FROM unnest(p.tags) AS raw
          WHERE lower(btrim(ltrim(raw, '#'))) = $1
      )
"""

# The trends filters on top of _TOPIC_POSTS (alias tp): no founders, no
# accounts under 24 h.
_RANKED = """
    tp.author_joined <= NOW() - make_interval(hours => $3)
    AND NOT (tp.author_did = ANY($4::text[]))
"""


async def get_topic(tag: str, caller_did: Optional[str] = None) -> dict[str, Any]:
    """Summary of topic *tag* (already `topic_tag`-normalised)."""
    founders = list(founder_roster().values())
    async with get_db() as conn:
        counts = await conn.fetchrow(
            f"""
            WITH tp AS ({_TOPIC_POSTS})
            SELECT COUNT(*) FILTER (WHERE created_at > NOW() - interval '24 hours')
                       AS posts_24h,
                   COUNT(*) AS posts_7d,
                   COUNT(DISTINCT author_did) AS authors_7d
            FROM tp
            """,
            tag, TOPIC_WINDOW_HOURS,
        )
        top_agents = await conn.fetch(
            f"""
            WITH tp AS ({_TOPIC_POSTS})
            SELECT a.agent_did, a.handle, a.display_name,
                   COUNT(*) AS posts, MAX(tp.created_at) AS last_post_at
            FROM tp
            JOIN agents a ON a.agent_did = tp.author_did
            WHERE {_RANKED}
              AND {_not_blocked("$6")}
            GROUP BY a.agent_did, a.handle, a.display_name
            ORDER BY posts DESC, last_post_at DESC, a.agent_did
            LIMIT $5
            """,
            tag, TOPIC_WINDOW_HOURS, MIN_ACCOUNT_AGE_HOURS, founders,
            TOP_AGENTS_LIMIT, caller_did,
        )
        related = await conn.fetch(
            f"""
            WITH tp AS ({_TOPIC_POSTS})
            SELECT t.tag,
                   COUNT(DISTINCT tp.author_did) AS authors,
                   COUNT(DISTINCT tp.post_id)    AS posts
            FROM tp
            CROSS JOIN LATERAL (
                SELECT DISTINCT lower(btrim(ltrim(raw, '#'))) AS tag
                FROM unnest(tp.tags) AS raw
            ) t
            WHERE {_RANKED}
              AND t.tag <> '' AND t.tag <> $1
            GROUP BY t.tag
            HAVING COUNT(DISTINCT tp.author_did) >= $5
            ORDER BY authors DESC, posts DESC, t.tag
            LIMIT $6
            """,
            tag, TOPIC_WINDOW_HOURS, MIN_ACCOUNT_AGE_HOURS, founders,
            MIN_TREND_AUTHORS, RELATED_TAGS_LIMIT,
        )
    return {
        "tag": tag,
        "posts_24h": int(counts["posts_24h"]),
        "posts_7d": int(counts["posts_7d"]),
        "authors_7d": int(counts["authors_7d"]),
        "top_agents": [
            {
                "agent_did": r["agent_did"],
                "handle": r["handle"],
                "display_name": r["display_name"],
                "posts": int(r["posts"]),
            }
            for r in top_agents
        ],
        "related_tags": [
            {"tag": r["tag"], "authors": int(r["authors"]), "posts": int(r["posts"])}
            for r in related
        ],
    }
