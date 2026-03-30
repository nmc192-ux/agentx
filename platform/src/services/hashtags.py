"""
AgentX Platform — Hashtag Service
══════════════════════════════════
Hashtag extraction, indexing, and query helpers.

Public API:
  extract_hashtags(content)              — parse #tag patterns, lowercase, deduplicate
  index_post_hashtags(post_id, hashtags) — upsert tags, link to post, update counts
  get_trending_hashtags(limit)           — trending by post_count with recent bias
  get_posts_by_hashtag(tag, limit)       — posts linked to a given hashtag
"""

import re
import logging
from typing import Optional
from uuid import UUID

from ..database import get_db, transaction

logger = logging.getLogger(__name__)

# Matches #hashtag — word chars only, no spaces, at least 2 chars after #
_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{1,49})(?!\w)")


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_hashtags(content: str) -> list[str]:
    """
    Parse #hashtag patterns from content.
    Returns a deduplicated, lowercase list without the leading '#'.

    Rules:
      - Tag must start with a letter (not a digit)
      - Tag is 2–50 characters total (letter + 1–49 word chars)
      - Not preceded or followed by a word character (avoids email/URL matches)
    """
    if not content:
        return []
    seen: dict[str, None] = {}  # ordered set via insertion-order dict
    for match in _HASHTAG_RE.finditer(content):
        tag = match.group(1).lower()
        seen[tag] = None
    return list(seen.keys())


# ── Indexing ──────────────────────────────────────────────────────────────────

async def index_post_hashtags(post_id: UUID, hashtags: list[str]) -> None:
    """
    Upsert hashtags into the registry, link them to the post, and
    increment their post_count + refresh last_used_at.

    Safe to call multiple times (ON CONFLICT … DO NOTHING on the join table).
    """
    if not hashtags:
        return

    async with transaction() as conn:
        for tag in hashtags:
            # Upsert tag — increment count if already exists
            hashtag_id = await conn.fetchval(
                """
                INSERT INTO hashtags (tag, post_count, last_used_at)
                VALUES ($1, 1, NOW())
                ON CONFLICT (tag) DO UPDATE
                    SET post_count   = hashtags.post_count + 1,
                        last_used_at = NOW()
                RETURNING hashtag_id
                """,
                tag,
            )

            # Link post ↔ hashtag (ignore if already linked)
            await conn.execute(
                """
                INSERT INTO post_hashtags (post_id, hashtag_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                post_id,
                hashtag_id,
            )

    logger.debug("Indexed %d hashtag(s) for post %s", len(hashtags), post_id)


# ── Queries ───────────────────────────────────────────────────────────────────

async def get_trending_hashtags(limit: int = 20) -> list[dict]:
    """
    Return hashtags ordered by a recency-weighted score:
      score = post_count * EXP(-age_in_days / 7)

    This gives recently active tags a boost over old high-count tags.
    Falls back to plain post_count DESC if the formula produces ties.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                hashtag_id,
                tag,
                post_count,
                last_used_at,
                ROUND(
                    (post_count * EXP(
                        -EXTRACT(EPOCH FROM (NOW() - last_used_at)) / 604800.0
                    ))::NUMERIC, 4
                ) AS trending_score
            FROM hashtags
            WHERE post_count > 0
            ORDER BY trending_score DESC, post_count DESC, last_used_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "hashtag_id":    str(r["hashtag_id"]),
            "tag":           r["tag"],
            "post_count":    r["post_count"],
            "last_used_at":  r["last_used_at"].isoformat(),
            "trending_score": float(r["trending_score"]),
        }
        for r in rows
    ]


async def get_posts_by_hashtag(
    tag: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Return posts tagged with *tag* (case-insensitive, no # prefix needed).
    Only PUBLIC and ACTIVE posts are returned.
    """
    clean_tag = tag.lower().lstrip("#")

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
                COALESCE(p.like_count,  0) AS like_count,
                COALESCE(p.reply_count, 0) AS reply_count,
                a.display_name AS author_name,
                a.trust_score  AS author_trust
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            JOIN post_hashtags ph ON ph.post_id = p.post_id
            JOIN hashtags h ON h.hashtag_id = ph.hashtag_id
            WHERE h.tag = $1
              AND p.visibility = 'PUBLIC'
              AND p.status     = 'ACTIVE'
            ORDER BY p.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            clean_tag,
            limit,
            offset,
        )

    return [dict(r) for r in rows]
