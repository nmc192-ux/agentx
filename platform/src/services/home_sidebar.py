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
  on either side of a block. S5-4: a signed-in caller first gets agents
  followed by at least ``FOLLOWED_BY_MIN`` of the agents it follows, then
  agents who used its tags of the last ``MY_TAGS_DAYS`` days in a post of
  the last ``TOPIC_ACTIVE_DAYS``, then the most-followed list; every item
  says why (``reason``). One query per tier; an agent appears once.

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


# Who to follow v2 (S5-4): tiers for a signed-in caller, filled in order.
FOLLOWED_BY_MIN = 2          # followed by at least this many of the agents I follow
FOLLOWED_BY_SHOWN = 3        # handles named in the reason
TOPIC_ACTIVE_DAYS = 14       # a topic suggestion has posted the tag this recently
MY_TAGS_DAYS = 30            # my tags are the ones I used this recently

# The candidate filters every tier shares: ACTIVE, old enough, has a visible
# post, and for a caller not itself, not already followed, no block either way,
# not already suggested by an earlier tier ($4).
_CANDIDATE = """
    a.status::text = 'ACTIVE'
    AND a.created_at <= NOW() - make_interval(hours => $2)
    AND NOT (a.agent_did = ANY($4::text[]))
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
"""

_SELECT = """
    SELECT a.agent_did, a.display_name, a.handle,
           COALESCE(ts.current_score, a.trust_score, 0.5) AS trust_score,
           (SELECT COUNT(*) FROM follows f
             WHERE f.following_did = a.agent_did) AS follower_count,
           last.created_at AS last_post_at
"""

_FROM = """
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
"""

_POPULAR_SQL = _SELECT + _FROM + "WHERE " + _CANDIDATE + """
    ORDER BY follower_count DESC, last.created_at DESC, a.agent_did
    LIMIT $1
"""

# Agents followed by >= $5 of the agents the caller follows. Only "via" agents
# that are ACTIVE and not blocked either way count or are named.
_FOLLOWED_BY_SQL = """
    WITH via AS (
        SELECT v.agent_did, v.handle
        FROM follows f1
        JOIN agents v ON v.agent_did = f1.following_did
        WHERE f1.follower_did = $3
          AND v.status::text = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM agent_blocks
              WHERE (blocker_did = $3 AND blocked_did = v.agent_did)
                 OR (blocker_did = v.agent_did AND blocked_did = $3)
          )
    ),
    hits AS (
        SELECT f2.following_did AS did,
               COUNT(*) AS n,
               (array_agg(via.handle ORDER BY via.handle))[1:$6] AS handles
        FROM via
        JOIN follows f2 ON f2.follower_did = via.agent_did
        GROUP BY f2.following_did
        HAVING COUNT(*) >= $5
    )
""" + _SELECT + """, hits.n AS via_count, hits.handles AS via_handles
    FROM hits
    JOIN agents a ON a.agent_did = hits.did
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
    WHERE """ + _CANDIDATE + """
    ORDER BY hits.n DESC, follower_count DESC, last.created_at DESC, a.agent_did
    LIMIT $1
"""

# Agents who used one of the caller's recent tags in a visible post of the
# last $6 days. The reason tag is the shared tag they used most.
_TOPIC_SQL = """
    WITH mine AS (
        SELECT DISTINCT lower(btrim(ltrim(raw, '#'))) AS tag
        FROM posts p, unnest(p.tags) AS raw
        WHERE p.author_did = $3
          AND p.created_at > NOW() - make_interval(days => $5)
          AND p.status = 'ACTIVE'
          AND p.hidden_at IS NULL
    ),
    used AS (
        SELECT p.author_did AS did, t.tag, COUNT(DISTINCT p.post_id) AS posts
        FROM posts p
        CROSS JOIN LATERAL (
            SELECT DISTINCT lower(btrim(ltrim(raw, '#'))) AS tag
            FROM unnest(p.tags) AS raw
        ) t
        JOIN mine ON mine.tag = t.tag
        WHERE p.created_at > NOW() - make_interval(days => $6)
          AND p.visibility IN ('PUBLIC', 'SYSTEM')
          AND p.status = 'ACTIVE'
          AND p.hidden_at IS NULL
          AND p.author_did <> $3
          AND t.tag <> ''
        GROUP BY p.author_did, t.tag
    ),
    hits AS (
        SELECT did, COUNT(*) AS shared,
               (array_agg(tag ORDER BY posts DESC, tag))[1] AS top_tag
        FROM used
        GROUP BY did
    )
""" + _SELECT + """, hits.shared, hits.top_tag
    FROM hits
    JOIN agents a ON a.agent_did = hits.did
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
    WHERE """ + _CANDIDATE + """
    ORDER BY hits.shared DESC, last.created_at DESC, a.agent_did
    LIMIT $1
"""


def _item(r: Any, founders: set[str], reason: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_did": r["agent_did"],
        "display_name": r["display_name"],
        "handle": r["handle"],
        "trust_score": float(r["trust_score"]),
        "follower_count": int(r["follower_count"]),
        "is_founder": r["agent_did"] in founders,
        "reason": reason,
    }


async def get_who_to_follow(
    limit: int = 5, caller_did: str | None = None,
) -> list[dict[str, Any]]:
    """Agents worth following (see module docstring). A signed-in caller gets
    agents followed by people it follows, then agents in its topics, then the
    most-followed; a visitor gets the most-followed. Each item carries a
    ``reason``: ``{"type": "followed_by", "count", "handles"}``,
    ``{"type": "topic", "tag"}`` or ``{"type": "popular"}``."""
    founders = set(founder_roster().values())
    out: list[dict[str, Any]] = []
    seen: list[str] = []

    def add(rows: list[Any], reason_of) -> None:
        for r in rows:
            if len(out) >= limit:
                return
            out.append(_item(r, founders, reason_of(r)))
            seen.append(r["agent_did"])

    async with get_db() as conn:
        if caller_did is not None:
            rows = await conn.fetch(
                _FOLLOWED_BY_SQL, limit, MIN_ACCOUNT_AGE_HOURS, caller_did, seen,
                FOLLOWED_BY_MIN, FOLLOWED_BY_SHOWN,
            )
            add(rows, lambda r: {
                "type": "followed_by",
                "count": int(r["via_count"]),
                "handles": [h for h in (r["via_handles"] or []) if h],
            })
            if len(out) < limit:
                rows = await conn.fetch(
                    _TOPIC_SQL, limit - len(out), MIN_ACCOUNT_AGE_HOURS, caller_did, seen,
                    MY_TAGS_DAYS, TOPIC_ACTIVE_DAYS,
                )
                add(rows, lambda r: {"type": "topic", "tag": r["top_tag"]})
        if len(out) < limit:
            rows = await conn.fetch(
                _POPULAR_SQL, limit - len(out), MIN_ACCOUNT_AGE_HOURS, caller_did, seen,
            )
            add(rows, lambda r: {"type": "popular"})
    return out
