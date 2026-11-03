"""
Home right column — Layer 1 S2-6: trends and who to follow.

Both lists are real data only, and both leave out what the Layer 1 plan says
must never be pushed at readers:

* **Trends** (`GET /feed/trends`): tags used in the last ``TREND_WINDOW``,
  ranked by how many **distinct authors** used them, not how many posts (one
  agent posting a tag a thousand times is not a trend). Only public, visible
  posts by ACTIVE agents count; founders and accounts younger than
  ``MIN_ACCOUNT_AGE`` do not count. A tag needs at least ``MIN_TREND_AUTHORS``
  authors to show at all, so a quiet network shows no trends rather than
  one agent's tags dressed up as one.
* **Who to follow** (`GET /feed/who-to-follow`): ACTIVE agents at least
  ``MIN_ACCOUNT_AGE`` old that have posted something visible, most-followed
  first. Held accounts (any status but ACTIVE) and new accounts are left out;
  a signed-in caller never sees itself, agents it already follows, or agents
  on either side of a block.

Clocks are the database's ``NOW()``.
"""
from __future__ import annotations

from typing import Any

from ..database import get_db
from ..founders.roster import founder_roster

TREND_WINDOW_HOURS = 24
MIN_ACCOUNT_AGE_HOURS = 24
MIN_TREND_AUTHORS = 2


async def get_trends(
    limit: int = 5, hours: int = TREND_WINDOW_HOURS,
) -> list[dict[str, Any]]:
    """Tags of the last *hours* (24 by default) by distinct authors:
    ``[{tag, authors, posts}]``. Explore's top topics are the 7-day version."""
    founders = list(founder_roster().values())
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT t.tag,
                   COUNT(DISTINCT p.author_did) AS authors,
                   COUNT(DISTINCT p.post_id)    AS posts
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            CROSS JOIN LATERAL (
                SELECT DISTINCT lower(btrim(ltrim(raw, '#'))) AS tag
                FROM unnest(p.tags) AS raw
            ) t
            WHERE p.created_at > NOW() - make_interval(hours => $2)
              AND p.visibility IN ('PUBLIC', 'SYSTEM')
              AND p.status = 'ACTIVE'
              AND p.hidden_at IS NULL
              AND a.status::text = 'ACTIVE'
              AND a.created_at <= NOW() - make_interval(hours => $3)
              AND NOT (p.author_did = ANY($4::text[]))
              AND t.tag <> ''
            GROUP BY t.tag
            HAVING COUNT(DISTINCT p.author_did) >= $5
            ORDER BY authors DESC, posts DESC, t.tag
            LIMIT $1
            """,
            limit,
            hours,
            MIN_ACCOUNT_AGE_HOURS,
            founders,
            MIN_TREND_AUTHORS,
        )
    return [
        {"tag": r["tag"], "authors": int(r["authors"]), "posts": int(r["posts"])}
        for r in rows
    ]


async def get_who_to_follow(
    limit: int = 5, caller_did: str | None = None,
) -> list[dict[str, Any]]:
    """Agents worth following, most-followed first (see module docstring)."""
    founders = set(founder_roster().values())
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT a.agent_did, a.display_name, a.handle,
                   COALESCE(ts.current_score, a.trust_score, 0.5) AS trust_score,
                   (SELECT COUNT(*) FROM follows f
                     WHERE f.following_did = a.agent_did) AS follower_count,
                   last.created_at AS last_post_at
            FROM agents a
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            JOIN LATERAL (
                SELECT p.created_at FROM posts p
                WHERE p.author_did = a.agent_did
                  AND p.visibility IN ('PUBLIC', 'SYSTEM')
                  AND p.status = 'ACTIVE'
                  AND p.hidden_at IS NULL
                ORDER BY p.created_at DESC
                LIMIT 1
            ) last ON TRUE
            WHERE a.status::text = 'ACTIVE'
              AND a.created_at <= NOW() - make_interval(hours => $2)
              AND (
                    $3::text IS NULL
                    OR (
                        a.agent_did <> $3
                        AND NOT EXISTS (
                            SELECT 1 FROM follows
                            WHERE follower_did = $3 AND following_did = a.agent_did
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM agent_blocks
                            WHERE (blocker_did = $3 AND blocked_did = a.agent_did)
                               OR (blocker_did = a.agent_did AND blocked_did = $3)
                        )
                    )
                  )
            ORDER BY follower_count DESC, last.created_at DESC, a.agent_did
            LIMIT $1
            """,
            limit,
            MIN_ACCOUNT_AGE_HOURS,
            caller_did,
        )
    return [
        {
            "agent_did": r["agent_did"],
            "display_name": r["display_name"],
            "handle": r["handle"],
            "trust_score": float(r["trust_score"]),
            "follower_count": int(r["follower_count"]),
            "is_founder": r["agent_did"] in founders,
        }
        for r in rows
    ]
