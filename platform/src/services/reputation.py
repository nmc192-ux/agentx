from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..cache import cache_delete, trust_score_key
from ..database import get_db, transaction
from ..models.reputation import AgentTrustScoreResponse, ReputationHistoryEntry

DEFAULT_TRUST_SCORE = 0.5

EVENT_WEIGHTS = {
    "task_completed": 0.05,
    "task_success": 0.05,
    "task_failed": -0.10,
    "task_failure": -0.10,
    "service_used": 0.02,
    "peer_validation": 0.03,
    "prediction_accuracy": 0.04,
    "message_replied": 0.01,
    "spam_flag": -0.20,
    "system_penalty": -0.25,
    # Phase 3: Social-economic bridge events
    "like_received": 0.005,
    "repost_received": 0.01,
    "capability_endorsed": 0.02,
    "follow_received": 0.003,
    "trending_post": 0.03,
    "sla_violation": -0.08,
}


def _normalize_event_type(event_type: str) -> str:
    return event_type.strip().lower()


def _clamp_score(score: float) -> float:
    return round(max(0.0, min(1.0, score)), 2)


def _decode_metadata(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


async def record_event(agent_did: str, event_type: str, metadata: dict | None = None) -> None:
    normalized_type = _normalize_event_type(event_type)
    event_weight = EVENT_WEIGHTS.get(normalized_type)
    if event_weight is None:
        raise ValueError(f"Unsupported reputation event type: {event_type}")

    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise ValueError(f"Agent not found: {agent_did}")

        await conn.execute(
            """
            INSERT INTO trust_events (
                event_id,
                agent_id,
                agent_did,
                event_type,
                event_weight,
                event_value,
                metadata
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $4,
                $5::jsonb
            )
            """,
            agent_row["agent_id"],
            agent_did,
            normalized_type,
            event_weight,
            json.dumps(metadata or {}),
        )


async def recalculate_agent_trust(
    *,
    agent_id: UUID | None = None,
    agent_did: str | None = None,
) -> dict[str, int]:
    processed_events = 0
    updated_agents: set[UUID] = set()

    async with transaction() as conn:
        rows = await conn.fetch(
            """
            SELECT
                te.event_id,
                te.agent_id,
                a.agent_did,
                te.event_type,
                COALESCE(te.event_weight, te.event_value, 0.0) AS event_weight,
                te.created_at
            FROM trust_events te
            JOIN agents a ON a.agent_id = te.agent_id
            LEFT JOIN agent_reputation_history arh ON arh.event_id = te.event_id
            WHERE arh.event_id IS NULL
              AND ($1::uuid IS NULL OR te.agent_id = $1)
              AND ($2::text IS NULL OR a.agent_did = $2)
            ORDER BY te.created_at ASC, te.event_id ASC
            """,
            agent_id,
            agent_did,
        )

        current_scores: dict[UUID, float] = {}

        for row in rows:
            agent_uuid = row["agent_id"]
            if agent_uuid not in current_scores:
                current_score = await conn.fetchval(
                    """
                    SELECT COALESCE(ts.current_score, a.trust_score, $2)
                    FROM agents a
                    LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
                    WHERE a.agent_id = $1
                    """,
                    agent_uuid,
                    DEFAULT_TRUST_SCORE,
                )
                current_scores[agent_uuid] = float(current_score if current_score is not None else DEFAULT_TRUST_SCORE)

            score_before = current_scores[agent_uuid]
            score_after = _clamp_score(score_before + float(row["event_weight"]))

            await conn.execute(
                """
                INSERT INTO trust_scores (agent_id, current_score, last_updated)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (agent_id)
                DO UPDATE SET
                    current_score = EXCLUDED.current_score,
                    last_updated = EXCLUDED.last_updated
                """,
                agent_uuid,
                score_after,
            )
            await conn.execute(
                "UPDATE agents SET trust_score = $1 WHERE agent_id = $2",
                score_after,
                agent_uuid,
            )
            await conn.execute(
                """
                INSERT INTO agent_reputation_history (
                    history_id,
                    agent_id,
                    score_before,
                    score_after,
                    event_id,
                    created_at
                )
                VALUES (
                    gen_random_uuid(),
                    $1,
                    $2,
                    $3,
                    $4,
                    CURRENT_TIMESTAMP
                )
                """,
                agent_uuid,
                score_before,
                score_after,
                row["event_id"],
            )

            current_scores[agent_uuid] = score_after
            processed_events += 1
            updated_agents.add(agent_uuid)

    if updated_agents:
        async with get_db() as conn:
            did_rows = await conn.fetch(
                "SELECT agent_did FROM agents WHERE agent_id = ANY($1::uuid[])",
                list(updated_agents),
            )
        for did_row in did_rows:
            await cache_delete(trust_score_key(did_row["agent_did"]))

    return {
        "processed_events": processed_events,
        "updated_agents": len(updated_agents),
    }


async def update_trust_score(agent_did: str) -> float:
    await recalculate_agent_trust(agent_did=agent_did)
    trust = await get_agent_trust_by_did(agent_did)
    return trust.current_score


async def get_agent_trust(agent_id: UUID) -> AgentTrustScoreResponse:
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.agent_id,
                COALESCE(ts.current_score, a.trust_score, $2) AS current_score,
                ts.last_updated
            FROM agents a
            LEFT JOIN trust_scores ts ON ts.agent_id = a.agent_id
            WHERE a.agent_id = $1
            """,
            agent_id,
            DEFAULT_TRUST_SCORE,
        )
    if row is None:
        raise ValueError(f"Agent not found: {agent_id}")

    return AgentTrustScoreResponse(
        agent_id=row["agent_id"],
        current_score=float(row["current_score"]),
        last_updated=row["last_updated"],
    )


async def get_agent_trust_by_did(agent_did: str) -> AgentTrustScoreResponse:
    async with get_db() as conn:
        agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )
    if agent_id is None:
        raise ValueError(f"Agent not found: {agent_did}")
    return await get_agent_trust(agent_id)


async def get_reputation_history(agent_id: UUID, limit: int = 50) -> list[ReputationHistoryEntry]:
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_id = $1",
            agent_id,
        )
        if not exists:
            raise ValueError(f"Agent not found: {agent_id}")

        rows = await conn.fetch(
            """
            SELECT
                arh.history_id,
                arh.agent_id,
                arh.score_before,
                arh.score_after,
                arh.event_id,
                te.event_type,
                COALESCE(te.event_weight, te.event_value, 0.0) AS event_weight,
                te.metadata,
                arh.created_at
            FROM agent_reputation_history arh
            JOIN trust_events te ON te.event_id = arh.event_id
            WHERE arh.agent_id = $1
            ORDER BY arh.created_at DESC
            LIMIT $2
            """,
            agent_id,
            limit,
        )

    return [
        ReputationHistoryEntry(
            history_id=row["history_id"],
            agent_id=row["agent_id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            event_weight=float(row["event_weight"]),
            score_before=float(row["score_before"]),
            score_after=float(row["score_after"]),
            metadata=_decode_metadata(row["metadata"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
