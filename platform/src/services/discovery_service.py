"""
AgentX Platform — Agent Discovery & Capability Registry Service
═══════════════════════════════════════════════════════════════════════════════
Phase 16: Enables finding the best agents by capability, reputation, and
          performance metrics.

Public API
──────────
  register_capability(agent_id, capability, confidence)
                                              → AgentCapability
  get_agent_capabilities(agent_id)           → list[AgentCapability]
  list_agents_by_capability(capability, limit)
                                              → list[AgentDiscoveryResponse]
  search_agents_semantic(query, limit)        → list[AgentDiscoveryResponse]
  get_top_agents(limit)                       → list[AgentDiscoveryResponse]
  get_agent_metrics(agent_id)                 → AgentMetricsResponse
  update_agent_metrics(agent_id)             → AgentMetricsResponse
  calculate_agent_score(trust_score,
                         contracts_completed,
                         verification_success,
                         bounties_won)        → float   (pure, no DB)

Ranking formula
───────────────
  score = (trust_score          * 0.4)
        + (completed_norm       * 0.2)   # min(contracts_completed/100, 1.0)
        + (verification_success * 0.2)
        + (bounties_norm        * 0.2)   # min(bounties_won/10, 1.0)

Design notes
────────────
• Semantic search uses ILIKE pattern matching on capability names when no
  embeddings are loaded.  When discovery_embeddings are populated the query
  can be upgraded to cosine-similarity on JSONB float arrays.
• update_agent_metrics() is idempotent (ON CONFLICT DO UPDATE).
• All public functions are async; calculate_agent_score() is sync/pure.
• Events are fire-and-forget; DB failures in update_agent_metrics() are
  logged but never bubble up to callers.
"""
from __future__ import annotations

import logging
import math
from uuid import UUID

from ..database import get_db, transaction
from ..models.discovery import (
    AgentCapability,
    AgentDiscoveryResponse,
    AgentMetricsResponse,
)

logger = logging.getLogger(__name__)


# ── Pure helpers ───────────────────────────────────────────────────────────────

def calculate_agent_score(
    trust_score: float,
    contracts_completed: int,
    verification_success: float,
    bounties_won: int,
) -> float:
    """
    Compute the composite discovery score for an agent.

    Args:
        trust_score:          Reputation score in [0.0, 1.0].
        contracts_completed:  Raw count of completed contracts.
        verification_success: Fraction of verifications approved (0.0–1.0).
        bounties_won:         Raw count of bounties won.

    Returns:
        Composite score in [0.0, 1.0].
    """
    completed_norm  = min(contracts_completed / 100.0, 1.0)
    bounties_norm   = min(bounties_won / 10.0, 1.0)

    return (
        trust_score          * 0.4
        + completed_norm     * 0.2
        + verification_success * 0.2
        + bounties_norm      * 0.2
    )


def _score_expr() -> str:
    """Return the SQL expression for the ranking score (used in ORDER BY)."""
    return """
        (
          COALESCE(a.trust_score, 0.0) * 0.4
        + LEAST(COALESCE(am.contracts_completed, 0)::float / 100.0, 1.0) * 0.2
        + COALESCE(am.verification_success, 0.0) * 0.2
        + LEAST(COALESCE(am.bounties_won, 0)::float / 10.0, 1.0) * 0.2
        )
    """


def _row_to_discovery(row) -> AgentDiscoveryResponse:
    caps_raw = row.get("capabilities") or ""
    caps = [c.strip() for c in caps_raw.split(",") if c.strip()] if caps_raw else []

    trust_score           = float(row.get("trust_score") or 0.0)
    contracts_completed   = int(row.get("contracts_completed") or 0)
    verification_success  = float(row.get("verification_success") or 0.0)
    bounties_won          = int(row.get("bounties_won") or 0)

    return AgentDiscoveryResponse(
        agent_id=row["agent_id"],
        agent_did=row["agent_did"],
        name=row.get("display_name") or row.get("name") or row["agent_did"],
        trust_score=trust_score,
        capabilities=caps,
        score=calculate_agent_score(
            trust_score, contracts_completed, verification_success, bounties_won
        ),
        contracts_completed=contracts_completed,
        contracts_failed=int(row.get("contracts_failed") or 0),
        verification_success=verification_success,
        bounties_won=bounties_won,
        last_active=row.get("last_active"),
    )


def _row_to_metrics(row) -> AgentMetricsResponse:
    return AgentMetricsResponse(
        agent_id=row["agent_id"],
        contracts_completed=int(row.get("contracts_completed") or 0),
        contracts_failed=int(row.get("contracts_failed") or 0),
        verification_success=float(row.get("verification_success") or 0.0),
        bounties_won=int(row.get("bounties_won") or 0),
        last_active=row.get("last_active"),
    )


# ── Capability registration ────────────────────────────────────────────────────

async def register_capability(
    agent_id: UUID,
    capability: str,
    confidence: float = 1.0,
) -> AgentCapability:
    """
    Register (or update) a capability for an agent.

    Uses ON CONFLICT (agent_id, capability) DO UPDATE so calling twice is safe.

    Args:
        agent_id:   UUID of the agent declaring the capability.
        capability: Capability name (e.g. "collect_data", "analyse_data").
        confidence: Declared confidence level in [0.0, 1.0].

    Returns:
        AgentCapability with registry_id, capability, confidence, created_at.

    Raises:
        ValueError: agent not found.
    """
    async with transaction() as conn:
        # Verify agent exists
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_id = $1", agent_id
        )
        if not exists:
            raise ValueError(f"Agent not found: {agent_id}")

        row = await conn.fetchrow(
            """
            INSERT INTO agent_capabilities_registry
                (agent_id, capability, confidence)
            VALUES ($1, $2, $3)
            ON CONFLICT (agent_id, capability)
                DO UPDATE SET confidence = EXCLUDED.confidence
            RETURNING registry_id, agent_id, capability, confidence, created_at
            """,
            agent_id,
            capability,
            confidence,
        )

    return AgentCapability(
        registry_id=row["registry_id"],
        agent_id=row["agent_id"],
        capability=row["capability"],
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
    )


async def get_agent_capabilities(agent_id: UUID) -> list[AgentCapability]:
    """
    Return all capability registrations for an agent.

    Args:
        agent_id: UUID of the agent.

    Returns:
        List of AgentCapability, newest first.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT registry_id, agent_id, capability, confidence, created_at
            FROM   agent_capabilities_registry
            WHERE  agent_id = $1
            ORDER  BY created_at DESC
            """,
            agent_id,
        )
    return [
        AgentCapability(
            registry_id=r["registry_id"],
            agent_id=r["agent_id"],
            capability=r["capability"],
            confidence=float(r["confidence"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── Discovery queries ──────────────────────────────────────────────────────────

async def list_agents_by_capability(
    capability: str,
    limit: int = 10,
) -> list[AgentDiscoveryResponse]:
    """
    Find agents that have registered a specific capability, ranked by score.

    Args:
        capability: Exact capability name to look up.
        limit:      Maximum number of results (default 10).

    Returns:
        List of AgentDiscoveryResponse ordered by composite score (best first).
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                a.agent_id,
                a.agent_did,
                a.name,
                COALESCE(a.display_name, a.name, a.agent_did) AS display_name,
                COALESCE(a.trust_score, 0.0)              AS trust_score,
                STRING_AGG(acr2.capability, ',')           AS capabilities,
                COALESCE(am.contracts_completed, 0)        AS contracts_completed,
                COALESCE(am.contracts_failed,   0)         AS contracts_failed,
                COALESCE(am.verification_success, 0.0)     AS verification_success,
                COALESCE(am.bounties_won, 0)               AS bounties_won,
                am.last_active
            FROM   agent_capabilities_registry acr
            JOIN   agents a    ON a.agent_id  = acr.agent_id
            LEFT   JOIN agent_metrics am ON am.agent_id = a.agent_id
            LEFT   JOIN agent_capabilities_registry acr2
                         ON acr2.agent_id = a.agent_id
            WHERE  acr.capability = $1
            GROUP  BY a.agent_id, a.agent_did, a.name, a.display_name, a.trust_score,
                      am.contracts_completed, am.contracts_failed,
                      am.verification_success, am.bounties_won, am.last_active
            ORDER  BY {_score_expr()} DESC
            LIMIT  $2
            """,
            capability,
            limit,
        )

    return [_row_to_discovery(r) for r in rows]


async def search_agents_semantic(
    query: str,
    limit: int = 10,
) -> list[AgentDiscoveryResponse]:
    """
    Find agents by semantic similarity to the query string.

    Implementation: Uses ILIKE substring matching on capability names, ranked
    by composite score.  When discovery_embeddings are populated this can be
    upgraded to cosine-similarity ranking without changing the API.

    Args:
        query: Natural-language capability description.
        limit: Maximum number of results (default 10).

    Returns:
        List of AgentDiscoveryResponse ordered by composite score (best first).
    """
    pattern = f"%{query.lower()}%"

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                a.agent_id,
                a.agent_did,
                a.name,
                COALESCE(a.trust_score, 0.0)              AS trust_score,
                STRING_AGG(DISTINCT acr.capability, ',')  AS capabilities,
                COALESCE(am.contracts_completed, 0)        AS contracts_completed,
                COALESCE(am.contracts_failed,   0)         AS contracts_failed,
                COALESCE(am.verification_success, 0.0)     AS verification_success,
                COALESCE(am.bounties_won, 0)               AS bounties_won,
                am.last_active
            FROM   agent_capabilities_registry acr
            JOIN   agents a    ON a.agent_id  = acr.agent_id
            LEFT   JOIN agent_metrics am ON am.agent_id = a.agent_id
            WHERE  LOWER(acr.capability) LIKE $1
            GROUP  BY a.agent_id, a.agent_did, a.name, a.trust_score,
                      am.contracts_completed, am.contracts_failed,
                      am.verification_success, am.bounties_won, am.last_active
            ORDER  BY {_score_expr()} DESC
            LIMIT  $2
            """,
            pattern,
            limit,
        )

    return [_row_to_discovery(r) for r in rows]


async def get_top_agents(limit: int = 10) -> list[AgentDiscoveryResponse]:
    """
    Return the highest-scoring agents in the network, regardless of capability.

    Args:
        limit: Maximum number of results (default 10).

    Returns:
        List of AgentDiscoveryResponse ordered by composite score (best first).
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                a.agent_id,
                a.agent_did,
                a.name,
                COALESCE(a.display_name, a.name, a.agent_did) AS display_name,
                COALESCE(a.trust_score, 0.0)              AS trust_score,
                STRING_AGG(DISTINCT acr.capability, ',')  AS capabilities,
                COALESCE(am.contracts_completed, 0)        AS contracts_completed,
                COALESCE(am.contracts_failed,   0)         AS contracts_failed,
                COALESCE(am.verification_success, 0.0)     AS verification_success,
                COALESCE(am.bounties_won, 0)               AS bounties_won,
                am.last_active
            FROM   agents a
            LEFT   JOIN agent_metrics am ON am.agent_id = a.agent_id
            LEFT   JOIN agent_capabilities_registry acr ON acr.agent_id = a.agent_id
            GROUP  BY a.agent_id, a.agent_did, a.name, a.display_name, a.trust_score,
                      am.contracts_completed, am.contracts_failed,
                      am.verification_success, am.bounties_won, am.last_active
            ORDER  BY {_score_expr()} DESC
            LIMIT  $1
            """,
            limit,
        )

    return [_row_to_discovery(r) for r in rows]


# ── Metrics ────────────────────────────────────────────────────────────────────

async def get_agent_metrics(agent_id: UUID) -> AgentMetricsResponse:
    """
    Return stored performance metrics for an agent.

    If no metrics row exists yet, returns a zero-filled response so callers
    can always rely on getting a valid object back.

    Args:
        agent_id: UUID of the agent.

    Returns:
        AgentMetricsResponse (possibly with all zeros if never updated).

    Raises:
        ValueError: Agent not found.
    """
    async with get_db() as conn:
        # Verify agent exists first
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_id = $1", agent_id
        )
        if not exists:
            raise ValueError(f"Agent not found: {agent_id}")

        row = await conn.fetchrow(
            """
            SELECT agent_id, contracts_completed, contracts_failed,
                   verification_success, bounties_won, last_active
            FROM   agent_metrics
            WHERE  agent_id = $1
            """,
            agent_id,
        )

    if row is None:
        return AgentMetricsResponse(agent_id=agent_id)

    return _row_to_metrics(row)


async def update_agent_metrics(agent_id: UUID) -> AgentMetricsResponse:
    """
    Recompute and persist performance metrics for an agent.

    Reads live counts from contracts, verifications, and bounty_rewards.
    Uses INSERT … ON CONFLICT DO UPDATE to stay idempotent.

    Soft-fail: query errors are logged but never re-raised so event consumers
    can always ACK their message.

    Args:
        agent_id: UUID of the agent to refresh.

    Returns:
        AgentMetricsResponse with updated counts.
    """
    try:
        async with transaction() as conn:
            # ── contracts_completed ───────────────────────────────────────────
            completed = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM   contracts
                WHERE  assigned_agent_id = $1
                  AND  status = 'completed'
                """,
                agent_id,
            ) or 0

            # ── contracts_failed ──────────────────────────────────────────────
            failed = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM   contracts
                WHERE  assigned_agent_id = $1
                  AND  status IN ('failed', 'disputed')
                """,
                agent_id,
            ) or 0

            # ── verification_success rate ─────────────────────────────────────
            ver_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE v.status = 'approved')  AS approved,
                    COUNT(*)                                        AS total
                FROM   verifications v
                JOIN   contracts c ON c.contract_id = v.contract_id
                WHERE  c.assigned_agent_id = $1
                """,
                agent_id,
            )
            if ver_row and ver_row["total"]:
                ver_success = float(ver_row["approved"]) / float(ver_row["total"])
            else:
                ver_success = 0.0

            # ── bounties_won ──────────────────────────────────────────────────
            bounties = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM   bounty_rewards
                WHERE  recipient_id = $1
                """,
                agent_id,
            ) or 0

            # ── upsert ───────────────────────────────────────────────────────
            row = await conn.fetchrow(
                """
                INSERT INTO agent_metrics
                    (agent_id, contracts_completed, contracts_failed,
                     verification_success, bounties_won, last_active)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (agent_id) DO UPDATE
                    SET contracts_completed  = EXCLUDED.contracts_completed,
                        contracts_failed     = EXCLUDED.contracts_failed,
                        verification_success = EXCLUDED.verification_success,
                        bounties_won         = EXCLUDED.bounties_won,
                        last_active          = NOW()
                RETURNING agent_id, contracts_completed, contracts_failed,
                          verification_success, bounties_won, last_active
                """,
                agent_id,
                int(completed),
                int(failed),
                ver_success,
                int(bounties),
            )

        logger.info(
            "discovery_service: metrics updated for agent %s "
            "(completed=%d, failed=%d, ver=%.2f, bounties=%d)",
            agent_id, completed, failed, ver_success, bounties,
        )
        return _row_to_metrics(row)

    except Exception:
        logger.warning(
            "discovery_service: failed to update metrics for agent %s",
            agent_id, exc_info=True,
        )
        return AgentMetricsResponse(agent_id=agent_id)
