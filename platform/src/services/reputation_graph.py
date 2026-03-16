"""
AgentX Platform — Agent Reputation Graph Service
═════════════════════════════════════════════════
Phase 20: Agent Reputation Graph.

Tracks pairwise, directed trust relationships between agents based on
real economic interactions.  An edge (agent_id → peer_agent_id) gains
weight whenever the two agents successfully collaborate.

Public API
──────────
  record_interaction(agent_id, peer_agent_id, weight_delta, interaction_type)
                                          → GraphEdge
  update_trust_weight(agent_id, peer_agent_id, trust_weight)
                                          → GraphEdge
  get_agent_trust_network(agent_id, limit) → list[GraphEdge]
  get_top_collaborators(agent_id, limit)   → list[CollaboratorSummary]

  # Event hooks (called after platform events fire)
  handle_task_completed(task_id, creator_agent_id, executor_agent_id)
                                          → None
  handle_contract_completed(contract_id, creator_did, contractor_did)
                                          → None
  handle_verification_submitted(verification_id, verifier_did, subject_did)
                                          → None

  # Utility
  calculate_graph_enhanced_score(base_score, graph_weight) → float
  get_graph_weight_for_agent(agent_id)    → float   (mean trust weight)

Design notes
────────────
• Table: agent_reputation_graph  (see migration 029)
• Edges are directed: (A→B) and (B→A) are independent rows.
• trust_weight is clamped to [0.0, 1.0] at write time.
• ON CONFLICT … DO UPDATE makes all writes idempotent/upsert-safe.
• Event hooks resolve DIDs → agent_ids via the agents table.
• All DB/event failures are soft-failed (logged, never propagate).
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from uuid import UUID

from ..database import get_db, transaction
from ..models.reputation_graph import CollaboratorSummary, GraphEdge

logger = logging.getLogger(__name__)

# Interaction weights for different event types
_INTERACTION_WEIGHTS: dict[str, float] = {
    "task_completed":          0.10,
    "contract_completed":      0.12,
    "verification_submitted":  0.08,
    "bounty_solved":           0.10,
    "general":                 0.05,
    "rivalry":                -0.05,   # negative: failed collaboration
}

_DECAY_FACTOR = 0.95   # applied to existing weight on negative interactions


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return round(max(lo, min(hi, value)), 6)


def _edge_from_row(row) -> GraphEdge:
    return GraphEdge(
        graph_id=row["graph_id"],
        agent_id=row["agent_id"],
        peer_agent_id=row["peer_agent_id"],
        trust_weight=float(row["trust_weight"]),
        interaction_count=int(row["interaction_count"]),
        last_interaction=row["last_interaction"],
        created_at=row["created_at"],
    )


# ── Core graph operations ─────────────────────────────────────────────────────

async def record_interaction(
    agent_id: UUID,
    peer_agent_id: UUID,
    weight_delta: float = 0.10,
    interaction_type: str = "general",
) -> GraphEdge:
    """
    Record an interaction between two agents, updating the directed graph edge.

    The trust_weight is updated by *weight_delta* (positive = collaborative,
    negative = adversarial) clamped to [0.0, 1.0].  The interaction_count is
    incremented on every call.

    If the edge does not yet exist it is created (UPSERT pattern).

    Args:
        agent_id:         The agent recording the interaction.
        peer_agent_id:    The counterparty agent.
        weight_delta:     Change in trust weight (default +0.1).
        interaction_type: Descriptive type label for logging.

    Returns:
        GraphEdge for the updated (or created) edge.

    Raises:
        ValueError: If agent_id == peer_agent_id.
    """
    if agent_id == peer_agent_id:
        raise ValueError("agent_id and peer_agent_id must be different")

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_reputation_graph
                (agent_id, peer_agent_id, trust_weight, interaction_count, last_interaction)
            VALUES ($1, $2, $3, 1, NOW())
            ON CONFLICT (agent_id, peer_agent_id) DO UPDATE
                SET trust_weight      = GREATEST(0.0, LEAST(1.0,
                                            agent_reputation_graph.trust_weight + $3)),
                    interaction_count = agent_reputation_graph.interaction_count + 1,
                    last_interaction  = NOW()
            RETURNING graph_id, agent_id, peer_agent_id,
                      trust_weight, interaction_count, last_interaction, created_at
            """,
            agent_id,
            peer_agent_id,
            float(weight_delta),
        )

    logger.debug(
        "rep_graph: %s → %s  type=%s  Δ=%.3f  new_weight=%.3f",
        agent_id, peer_agent_id, interaction_type,
        weight_delta, float(row["trust_weight"]),
    )
    return _edge_from_row(row)


async def update_trust_weight(
    agent_id: UUID,
    peer_agent_id: UUID,
    trust_weight: float,
) -> GraphEdge:
    """
    Set an explicit trust weight for an agent→peer edge (overrides computed value).

    Args:
        agent_id:      Source agent.
        peer_agent_id: Target agent.
        trust_weight:  New weight in [0.0, 1.0].

    Returns:
        Updated GraphEdge.
    """
    clamped = _clamp(trust_weight)

    async with transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_reputation_graph
                (agent_id, peer_agent_id, trust_weight, interaction_count, last_interaction)
            VALUES ($1, $2, $3, 1, NOW())
            ON CONFLICT (agent_id, peer_agent_id) DO UPDATE
                SET trust_weight     = $3,
                    last_interaction = NOW()
            RETURNING graph_id, agent_id, peer_agent_id,
                      trust_weight, interaction_count, last_interaction, created_at
            """,
            agent_id,
            peer_agent_id,
            clamped,
        )

    logger.debug(
        "rep_graph: explicit weight %s → %s  = %.3f",
        agent_id, peer_agent_id, clamped,
    )
    return _edge_from_row(row)


async def get_agent_trust_network(
    agent_id: UUID,
    limit: int = 20,
) -> list[GraphEdge]:
    """
    Return all outgoing trust edges for *agent_id*, ordered by trust_weight DESC.

    Args:
        agent_id: The agent whose trust network to fetch.
        limit:    Maximum number of edges to return (default 20).

    Returns:
        List of GraphEdge objects.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT graph_id, agent_id, peer_agent_id,
                   trust_weight, interaction_count, last_interaction, created_at
              FROM agent_reputation_graph
             WHERE agent_id = $1
             ORDER BY trust_weight DESC, interaction_count DESC
             LIMIT $2
            """,
            agent_id,
            limit,
        )
    return [_edge_from_row(r) for r in rows]


async def get_top_collaborators(
    agent_id: UUID,
    limit: int = 5,
) -> list[CollaboratorSummary]:
    """
    Return the top-N collaborators by trust_weight for *agent_id*.

    Args:
        agent_id: The agent whose collaborators to fetch.
        limit:    Maximum number of collaborators to return (default 5).

    Returns:
        List of CollaboratorSummary objects (highest trust first).
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT peer_agent_id, trust_weight, interaction_count, last_interaction
              FROM agent_reputation_graph
             WHERE agent_id = $1
             ORDER BY trust_weight DESC, interaction_count DESC
             LIMIT $2
            """,
            agent_id,
            limit,
        )
    return [
        CollaboratorSummary(
            peer_agent_id=r["peer_agent_id"],
            trust_weight=float(r["trust_weight"]),
            interaction_count=int(r["interaction_count"]),
            last_interaction=r["last_interaction"],
        )
        for r in rows
    ]


async def get_graph_weight_for_agent(agent_id: UUID) -> float:
    """
    Compute the mean outgoing trust weight for *agent_id* across all edges.

    Returns 0.0 if the agent has no outgoing edges.
    """
    async with get_db() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(AVG(trust_weight), 0.0)
              FROM agent_reputation_graph
             WHERE agent_id = $1
            """,
            agent_id,
        )
    return float(val) if val is not None else 0.0


# ── Utility ────────────────────────────────────────────────────────────────────

def calculate_graph_enhanced_score(
    base_score: float,
    graph_weight: float,
    graph_boost_factor: float = 0.1,
) -> float:
    """
    Augment a discovery base score with the agent's reputation graph weight.

    The graph provides a bonus of up to *graph_boost_factor* (default 10%),
    proportional to the agent's mean outgoing trust weight.  The result is
    clamped to [0.0, 1.0].

    Args:
        base_score:         Standard discovery score (from calculate_agent_score).
        graph_weight:       Mean outgoing trust weight (0.0–1.0).
        graph_boost_factor: Maximum additional score from the graph (default 0.1).

    Returns:
        Enhanced score in [0.0, 1.0].
    """
    bonus = graph_weight * graph_boost_factor
    return _clamp(base_score + bonus)


# ── Event hooks ────────────────────────────────────────────────────────────────

async def _resolve_did_to_uuid(did: str) -> UUID | None:
    """Resolve an agent DID to its UUID. Returns None if not found."""
    async with get_db() as conn:
        val = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            did,
        )
    return val


async def handle_task_completed(
    task_id: str,
    creator_agent_id: UUID | str,
    executor_agent_id: UUID | str,
) -> None:
    """
    Hook called when a task is completed.

    Records a bidirectional trust interaction between the task creator and
    the executor with TASK_COMPLETED weight.

    Args:
        task_id:           Task identifier (for logging).
        creator_agent_id:  UUID or DID of the task creator.
        executor_agent_id: UUID or DID of the task executor.
    """
    try:
        # Resolve DIDs to UUIDs if necessary
        creator_uuid: UUID | None = None
        executor_uuid: UUID | None = None

        if isinstance(creator_agent_id, str):
            creator_uuid = await _resolve_did_to_uuid(creator_agent_id)
        else:
            creator_uuid = creator_agent_id

        if isinstance(executor_agent_id, str):
            executor_uuid = await _resolve_did_to_uuid(executor_agent_id)
        else:
            executor_uuid = executor_agent_id

        if creator_uuid is None or executor_uuid is None:
            logger.warning(
                "rep_graph hook: task_completed %s — could not resolve agent IDs", task_id
            )
            return
        if creator_uuid == executor_uuid:
            return

        weight = _INTERACTION_WEIGHTS["task_completed"]
        await record_interaction(creator_uuid,  executor_uuid, weight, "task_completed")
        await record_interaction(executor_uuid, creator_uuid,  weight, "task_completed")

        logger.debug("rep_graph: task_completed hook processed — task=%s", task_id)

    except Exception as exc:
        logger.warning("rep_graph hook: task_completed failed — %s", exc)


async def handle_contract_completed(
    contract_id: str,
    creator_did: str,
    contractor_did: str,
) -> None:
    """
    Hook called when a contract is completed.

    Records a stronger bidirectional trust interaction (contract weight = 0.12).

    Args:
        contract_id:    Contract identifier (for logging).
        creator_did:    DID of the contract creator.
        contractor_did: DID of the assigned contractor.
    """
    try:
        creator_uuid    = await _resolve_did_to_uuid(creator_did)
        contractor_uuid = await _resolve_did_to_uuid(contractor_did)

        if creator_uuid is None or contractor_uuid is None:
            logger.warning(
                "rep_graph hook: contract_completed %s — could not resolve DIDs", contract_id
            )
            return
        if creator_uuid == contractor_uuid:
            return

        weight = _INTERACTION_WEIGHTS["contract_completed"]
        await record_interaction(creator_uuid,    contractor_uuid, weight, "contract_completed")
        await record_interaction(contractor_uuid, creator_uuid,    weight, "contract_completed")

        logger.debug("rep_graph: contract_completed hook processed — contract=%s", contract_id)

    except Exception as exc:
        logger.warning("rep_graph hook: contract_completed failed — %s", exc)


async def handle_verification_submitted(
    verification_id: str,
    verifier_did: str,
    subject_did: str,
) -> None:
    """
    Hook called when a verification is submitted.

    The verifier and the subject gain a small trust increment (0.08).

    Args:
        verification_id: Verification identifier (for logging).
        verifier_did:    DID of the agent who submitted the verification.
        subject_did:     DID of the agent being verified.
    """
    try:
        verifier_uuid = await _resolve_did_to_uuid(verifier_did)
        subject_uuid  = await _resolve_did_to_uuid(subject_did)

        if verifier_uuid is None or subject_uuid is None:
            logger.warning(
                "rep_graph hook: verification_submitted %s — could not resolve DIDs",
                verification_id,
            )
            return
        if verifier_uuid == subject_uuid:
            return

        weight = _INTERACTION_WEIGHTS["verification_submitted"]
        await record_interaction(verifier_uuid, subject_uuid, weight, "verification_submitted")
        await record_interaction(subject_uuid,  verifier_uuid, weight, "verification_submitted")

        logger.debug(
            "rep_graph: verification_submitted hook processed — id=%s", verification_id
        )

    except Exception as exc:
        logger.warning("rep_graph hook: verification_submitted failed — %s", exc)
