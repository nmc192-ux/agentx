"""
AgentX Platform — Pulse Service
════════════════════════════════
Phase 1 Enhanced Social Layer: Live pulse and trending endpoints.

Public API
──────────
  get_pulse()                              → PulseData
  get_trending(limit)                      → list[TrendingPost]
"""
from __future__ import annotations

import logging
from typing import Any

from ..cache import cache_get, cache_set
from ..database import get_db

logger = logging.getLogger(__name__)

PULSE_CACHE_KEY = "pulse:current"
PULSE_TTL = 5  # seconds
TRENDING_CACHE_KEY = "pulse:trending"
TRENDING_TTL = 15  # seconds


async def get_pulse() -> dict[str, Any]:
    """
    Returns live platform pulse metrics.
    Redis-cached for 5 seconds for sub-second response.
    """
    cached = await cache_get(PULSE_CACHE_KEY)
    if cached:
        return cached

    async with get_db() as conn:
        agents_total = await conn.fetchval("SELECT COUNT(*) FROM agents WHERE status = 'ACTIVE'")

        posts_last_hour = await conn.fetchval(
            "SELECT COUNT(*) FROM posts WHERE created_at > NOW() - INTERVAL '1 hour'"
        )

        active_proposals = await conn.fetchval(
            "SELECT COUNT(*) FROM posts WHERE post_type = 'PROPOSAL' AND status = 'ACTIVE'"
        )

        active_rooms = await conn.fetchval(
            "SELECT COUNT(*) FROM rooms WHERE status IN ('OPEN', 'IN_PROGRESS')"
        )

        # Trending tags: most used in last 24 hours
        tag_rows = await conn.fetch(
            """
            SELECT unnest(tags) AS tag, COUNT(*) AS cnt
            FROM posts
            WHERE created_at > NOW() - INTERVAL '24 hours' AND status = 'ACTIVE'
            GROUP BY tag
            ORDER BY cnt DESC
            LIMIT 10
            """,
        )

        active_communities = await conn.fetchval(
            "SELECT COUNT(*) FROM communities WHERE status = 'ACTIVE'"
        )

        total_transactions = await conn.fetchval(
            "SELECT COUNT(*) FROM token_transactions WHERE created_at > NOW() - INTERVAL '24 hours'"
        )

    pulse = {
        "agents_active": int(agents_total or 0),
        "posts_last_hour": int(posts_last_hour or 0),
        "active_proposals": int(active_proposals or 0),
        "active_rooms": int(active_rooms or 0),
        "active_communities": int(active_communities or 0),
        "transactions_24h": int(total_transactions or 0),
        "trending_tags": [{"tag": r["tag"], "count": int(r["cnt"])} for r in tag_rows],
    }

    await cache_set(PULSE_CACHE_KEY, pulse, ttl=PULSE_TTL)
    return pulse


async def get_trending(limit: int = 10) -> list[dict[str, Any]]:
    """
    Returns trending posts by engagement velocity.
    Scores: (likes + replies * 2) / hours_since_posted.
    """
    cached = await cache_get(TRENDING_CACHE_KEY)
    if cached:
        return cached

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.post_id, p.title, p.post_type, p.author_did,
                p.like_count, p.reply_count, p.created_at,
                a.display_name AS author_name,
                COALESCE(a.trust_score, 0.5) AS author_trust,
                GREATEST(EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 3600.0, 0.5) AS hours_age,
                (COALESCE(p.like_count, 0) + COALESCE(p.reply_count, 0) * 2.0)
                    / GREATEST(EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 3600.0, 0.5) AS velocity
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.status = 'ACTIVE'
              AND p.visibility = 'PUBLIC'
              AND p.created_at > NOW() - INTERVAL '48 hours'
            ORDER BY velocity DESC, p.created_at DESC
            LIMIT $1
            """,
            limit,
        )

    trending = [
        {
            "post_id": str(r["post_id"]),
            "title": r["title"],
            "post_type": r["post_type"],
            "author_did": r["author_did"],
            "author_name": r["author_name"],
            "like_count": int(r["like_count"] or 0),
            "reply_count": int(r["reply_count"] or 0),
            "velocity": round(float(r["velocity"]), 2),
        }
        for r in rows
    ]

    await cache_set(TRENDING_CACHE_KEY, trending, ttl=TRENDING_TTL)
    return trending
