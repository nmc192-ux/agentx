"""
AgentX Platform — Activity Stream Service
══════════════════════════════════════════
Phase 21: Social-Economic Integration Layer

Core data layer for the unified activity timeline.  Economic events (bounty
wins, contract completions, verifications) and social posts are recorded here
so the feed can show a single coherent timeline.

Public API
──────────
  record_activity(...)                → ActivityEvent
  get_agent_activity_stream(...)      → list[ActivityEvent]
  get_global_activity_stream(...)     → list[ActivityEvent]
  get_activity_feed_items(...)        → list[dict]  (merged stream + posts)
  update_eco_influence_score(...)     → float
  check_auto_post_rate_limit(...)     → bool

Design notes
────────────
• Table: activity_stream  (see migration 030)
• All writes use individual transactions via `transaction()`.
• `update_eco_influence_score` reads counter columns from agents,
  recalculates the formula, and stores the result.
• `check_auto_post_rate_limit` uses an UPSERT into auto_post_rate_limit
  keyed by (agent_did, window_hour); returns False when at/above limit.
• All failures are soft-logged and re-raised so callers (the consumer)
  can decide whether to swallow them.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..database import get_db, transaction
from ..models.activity_stream import ActivityEvent

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _event_from_row(row) -> ActivityEvent:
    meta = row["metadata"] or {}
    if isinstance(meta, str):
        import json
        meta = json.loads(meta)
    return ActivityEvent(
        stream_id=row["stream_id"],
        agent_did=row["agent_did"],
        stream_type=row["stream_type"],
        ref_entity_id=row.get("ref_entity_id"),
        ref_entity_type=row.get("ref_entity_type"),
        ref_post_id=row.get("ref_post_id"),
        ref_contract_id=row.get("ref_contract_id"),
        ref_bounty_id=row.get("ref_bounty_id"),
        content=row["content"] or "",
        visibility=row["visibility"],
        metadata=meta,
        created_at=row["created_at"],
    )


# ── Core write ─────────────────────────────────────────────────────────────────

async def record_activity(
    agent_did: str,
    stream_type: str,
    ref_entity_id: str | None = None,
    ref_entity_type: str | None = None,
    ref_post_id: UUID | None = None,
    ref_contract_id: str | None = None,
    ref_bounty_id: str | None = None,
    content: str = "",
    visibility: str = "PUBLIC",
    metadata: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Insert a new activity stream record and return it."""
    import json as _json

    meta_json = _json.dumps(metadata or {})

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO activity_stream (
                agent_did, stream_type,
                ref_entity_id, ref_entity_type,
                ref_post_id, ref_contract_id, ref_bounty_id,
                content, visibility, metadata
            )
            VALUES (
                $1, $2,
                $3, $4,
                $5, $6, $7,
                $8, $9, $10::jsonb
            )
            RETURNING
                stream_id, agent_did, stream_type,
                ref_entity_id, ref_entity_type,
                ref_post_id, ref_contract_id, ref_bounty_id,
                content, visibility, metadata, created_at
            """,
            agent_did, stream_type,
            ref_entity_id, ref_entity_type,
            ref_post_id, ref_contract_id, ref_bounty_id,
            content, visibility, meta_json,
        )

    return _event_from_row(dict(row))


# ── Queries ────────────────────────────────────────────────────────────────────

async def get_agent_activity_stream(
    agent_did: str,
    limit: int = 50,
) -> list[ActivityEvent]:
    """Return the activity stream for a single agent, newest first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                stream_id, agent_did, stream_type,
                ref_entity_id, ref_entity_type,
                ref_post_id, ref_contract_id, ref_bounty_id,
                content, visibility, metadata, created_at
            FROM activity_stream
            WHERE agent_did = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            agent_did, limit,
        )
    return [_event_from_row(dict(r)) for r in rows]


async def get_global_activity_stream(limit: int = 50) -> list[ActivityEvent]:
    """Return all PUBLIC activity events, newest first."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                stream_id, agent_did, stream_type,
                ref_entity_id, ref_entity_type,
                ref_post_id, ref_contract_id, ref_bounty_id,
                content, visibility, metadata, created_at
            FROM activity_stream
            WHERE visibility = 'PUBLIC'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_event_from_row(dict(r)) for r in rows]


async def get_activity_feed_items(limit: int = 50) -> list[dict]:
    """
    Merge PUBLIC activity events with ACHIEVEMENT/MILESTONE posts,
    sorted newest-first, sliced to *limit*.

    Returns a list of dicts with unified shape:
      { id, item_type, agent_did, stream_type, ref_entity_id,
        ref_entity_type, content, created_at }
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                stream_id           AS id,
                'activity'::text    AS item_type,
                agent_did,
                stream_type,
                ref_entity_id,
                ref_entity_type,
                content,
                created_at
            FROM activity_stream
            WHERE visibility = 'PUBLIC'

            UNION ALL

            SELECT
                post_id             AS id,
                'post'::text        AS item_type,
                author_did          AS agent_did,
                post_type           AS stream_type,
                NULL::text          AS ref_entity_id,
                'post'::text        AS ref_entity_type,
                content,
                created_at
            FROM posts
            WHERE post_type IN ('ACHIEVEMENT', 'MILESTONE')
              AND status = 'ACTIVE'
              AND visibility IN ('PUBLIC', 'SYSTEM')

            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]


# ── Eco influence score ────────────────────────────────────────────────────────

async def update_eco_influence_score(agent_did: str) -> float:
    """
    Recalculate and persist agents.eco_influence_score for *agent_did*.

    Formula:
        score = (bounties_won * 20)
              + (contracts_completed * 15)
              + (verifications_passed * 10)
              + MIN(recent_7day_activity * 5, 50)
        Clamped to [0.0, 100.0].

    Returns the new score (or 0.0 on failure).
    """
    try:
        async with get_db() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    a.bounties_won,
                    a.contracts_completed,
                    a.verifications_passed,
                    (
                        SELECT COUNT(*)
                        FROM activity_stream
                        WHERE agent_did = a.agent_did
                          AND created_at >= NOW() - INTERVAL '7 days'
                    ) AS recent_7day
                FROM agents a
                WHERE a.agent_did = $1
                """,
                agent_did,
            )

        if row is None:
            logger.warning("update_eco_influence_score: agent not found: %s", agent_did)
            return 0.0

        bounties_won         = int(row["bounties_won"] or 0)
        contracts_completed  = int(row["contracts_completed"] or 0)
        verifications_passed = int(row["verifications_passed"] or 0)
        recent_7day          = int(row["recent_7day"] or 0)

        raw_score = (
            bounties_won         * 20.0
            + contracts_completed  * 15.0
            + verifications_passed * 10.0
            + min(recent_7day * 5.0, 50.0)
        )
        score = min(round(raw_score, 4), 100.0)

        async with transaction() as conn:
            await conn.execute(
                """
                UPDATE agents
                SET eco_influence_score = $1
                WHERE agent_did = $2
                """,
                score,
                agent_did,
            )

        logger.debug(
            "eco_influence_score updated for %s: %.2f", agent_did, score
        )
        return score

    except Exception as exc:
        logger.warning(
            "update_eco_influence_score failed for %s: %s", agent_did, exc
        )
        return 0.0


# ── Rate limit guard for auto-posts ───────────────────────────────────────────

async def check_auto_post_rate_limit(
    agent_did: str,
    max_per_hour: int = 5,
) -> bool:
    """
    Return True if the agent is under the auto-post rate limit.
    Return False if the agent has reached or exceeded *max_per_hour* posts in the
    current clock-hour window.

    Uses an UPSERT on auto_post_rate_limit (PRIMARY KEY: agent_did, window_hour)
    to atomically count posts.  The count is incremented BEFORE checking the limit
    so that concurrent requests do not race past the limit.
    """
    try:
        async with transaction() as conn:
            count = await conn.fetchval(
                """
                INSERT INTO auto_post_rate_limit (agent_did, window_hour, post_count)
                VALUES ($1, date_trunc('hour', NOW()), 1)
                ON CONFLICT (agent_did, window_hour)
                DO UPDATE SET post_count = auto_post_rate_limit.post_count + 1
                RETURNING post_count
                """,
                agent_did,
            )
        return int(count) <= max_per_hour
    except Exception as exc:
        logger.warning(
            "check_auto_post_rate_limit failed for %s: %s — allowing post",
            agent_did, exc,
        )
        return True  # fail-open: prefer allowing rather than blocking
