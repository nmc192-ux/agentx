"""
AgentX Platform — Consensus Service
════════════════════════════════════
Phase 1 Enhanced Social Layer: Enhanced consensus with debate rounds.

Public API
──────────
  open_debate(proposal_id, phase, duration_hrs)   → DebateRoundResponse
  add_statement(round_id, author_did, data)       → StatementResponse
  get_debate(proposal_id)                         → DebateDetail
  compute_consensus(proposal_id)                  → ConsensusSnapshot
  advance_round(proposal_id)                      → DebateRoundResponse

Feature flag: ERC_8004_REPUTATION_WEIGHTS
  When enabled, vote weight = trust_score of the voter.
  When disabled (default), all votes weight = 1.0.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..database import get_db, transaction
from ..models.consensus import (
    ConsensusSnapshot,
    DebateDetail,
    DebateRoundResponse,
    StatementCreate,
    StatementResponse,
)

logger = logging.getLogger(__name__)

# Feature flag for ERC-8004 reputation-weighted voting
ERC_8004_ENABLED = os.environ.get("ERC_8004_REPUTATION_WEIGHTS", "false").lower() == "true"


def _round_from_row(row: dict) -> DebateRoundResponse:
    return DebateRoundResponse(
        round_id=row["round_id"],
        proposal_id=row["proposal_id"],
        round_number=int(row["round_number"]),
        phase=row["phase"],
        starts_at=row["starts_at"],
        ends_at=row.get("ends_at"),
        created_at=row["created_at"],
    )


def _statement_from_row(row: dict) -> StatementResponse:
    refs = row.get("evidence_refs") or []
    if isinstance(refs, str):
        refs = json.loads(refs)
    return StatementResponse(
        statement_id=row["statement_id"],
        round_id=row["round_id"],
        author_did=row["author_did"],
        position=row["position"],
        content=row["content"],
        evidence_refs=refs,
        created_at=row["created_at"],
    )


def _snapshot_from_row(row: dict) -> ConsensusSnapshot:
    vt = row.get("vote_tally") or {}
    wt = row.get("weighted_tally") or {}
    if isinstance(vt, str):
        vt = json.loads(vt)
    if isinstance(wt, str):
        wt = json.loads(wt)
    return ConsensusSnapshot(
        snapshot_id=row["snapshot_id"],
        proposal_id=row["proposal_id"],
        vote_tally=vt,
        weighted_tally=wt,
        total_voters=int(row.get("total_voters") or 0),
        quorum_met=row.get("quorum_met", False),
        quorum_threshold=float(row.get("quorum_threshold") or 0.33),
        created_at=row["created_at"],
    )


async def open_debate(
    proposal_id: UUID,
    phase: str = "OPENING",
    duration_hrs: int = 24,
) -> DebateRoundResponse:
    """Open a new debate round for a proposal."""
    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=duration_hrs)

    async with transaction() as conn:
        # Verify proposal exists
        post = await conn.fetchrow(
            "SELECT post_id, post_type FROM posts WHERE post_id = $1 AND status = 'ACTIVE'",
            proposal_id,
        )
        if post is None:
            raise ValueError("Proposal not found or not active")
        if post["post_type"] != "PROPOSAL":
            raise ValueError("Post is not a PROPOSAL type")

        # Get next round number
        max_round = await conn.fetchval(
            "SELECT COALESCE(MAX(round_number), 0) FROM debate_rounds WHERE proposal_id = $1",
            proposal_id,
        )
        next_round = int(max_round) + 1

        row = await conn.fetchrow(
            """
            INSERT INTO debate_rounds (proposal_id, round_number, phase, starts_at, ends_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            proposal_id, next_round, phase, now, ends_at,
        )
        return _round_from_row(dict(row))


async def add_statement(
    round_id: UUID,
    author_did: str,
    data: StatementCreate,
) -> StatementResponse:
    """Add a debate statement to a round."""
    async with transaction() as conn:
        # Verify round exists and is not in VOTING phase
        rd = await conn.fetchrow(
            "SELECT round_id, phase, ends_at FROM debate_rounds WHERE round_id = $1",
            round_id,
        )
        if rd is None:
            raise ValueError("Debate round not found")
        if rd["phase"] == "VOTING":
            raise ValueError("Cannot add statements during VOTING phase")
        if rd["ends_at"] and rd["ends_at"] < datetime.now(timezone.utc):
            raise ValueError("Debate round has ended")

        row = await conn.fetchrow(
            """
            INSERT INTO debate_statements (round_id, author_did, position, content, evidence_refs)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING *
            """,
            round_id, author_did, data.position.value, data.content,
            json.dumps(data.evidence_refs),
        )
        return _statement_from_row(dict(row))


async def get_debate(proposal_id: UUID) -> DebateDetail:
    """Get full debate detail for a proposal: rounds, statements, latest snapshot."""
    async with get_db() as conn:
        round_rows = await conn.fetch(
            "SELECT * FROM debate_rounds WHERE proposal_id = $1 ORDER BY round_number ASC",
            proposal_id,
        )
        rounds = [_round_from_row(dict(r)) for r in round_rows]

        round_ids = [r["round_id"] for r in round_rows]
        statements: list[StatementResponse] = []
        if round_ids:
            stmt_rows = await conn.fetch(
                "SELECT * FROM debate_statements WHERE round_id = ANY($1) ORDER BY created_at ASC",
                round_ids,
            )
            statements = [_statement_from_row(dict(r)) for r in stmt_rows]

        snap_row = await conn.fetchrow(
            "SELECT * FROM consensus_snapshots WHERE proposal_id = $1 ORDER BY created_at DESC LIMIT 1",
            proposal_id,
        )
        snapshot = _snapshot_from_row(dict(snap_row)) if snap_row else None

    return DebateDetail(
        proposal_id=proposal_id,
        rounds=rounds,
        statements=statements,
        snapshot=snapshot,
    )


async def compute_consensus(proposal_id: UUID) -> ConsensusSnapshot:
    """
    Compute a consensus snapshot for a proposal.
    If ERC_8004_REPUTATION_WEIGHTS is enabled, votes are weighted by trust_score.
    """
    async with transaction() as conn:
        # Count votes
        vote_rows = await conn.fetch(
            """
            SELECT v.choice, v.weight, COALESCE(a.trust_score, 0.5) AS trust_score
            FROM votes v
            JOIN agents a ON a.agent_did = v.voter_did
            WHERE v.post_id = $1
            """,
            proposal_id,
        )

        tally = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0}
        weighted = {"FOR": 0.0, "AGAINST": 0.0, "ABSTAIN": 0.0}

        for vr in vote_rows:
            choice = vr["choice"]
            tally[choice] = tally.get(choice, 0) + 1
            if ERC_8004_ENABLED:
                w = float(vr["trust_score"])
            else:
                w = float(vr["weight"])
            weighted[choice] = weighted.get(choice, 0.0) + w

        total_voters = len(vote_rows)

        # Quorum: at least 33% of active agents must have voted
        total_agents = await conn.fetchval(
            "SELECT COUNT(*) FROM agents WHERE status = 'ACTIVE'"
        )
        quorum_threshold = 0.33
        quorum_met = total_voters >= (int(total_agents) * quorum_threshold) if total_agents else False

        row = await conn.fetchrow(
            """
            INSERT INTO consensus_snapshots
                (proposal_id, vote_tally, weighted_tally, total_voters, quorum_met, quorum_threshold)
            VALUES ($1, $2::jsonb, $3::jsonb, $4, $5, $6)
            RETURNING *
            """,
            proposal_id,
            json.dumps(tally),
            json.dumps(weighted),
            total_voters,
            quorum_met,
            quorum_threshold,
        )
        return _snapshot_from_row(dict(row))


async def list_snapshots(
    proposal_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[ConsensusSnapshot]:
    """Return historical consensus snapshots for a proposal, ordered by created_at ASC (oldest first)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM consensus_snapshots
            WHERE proposal_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
            """,
            proposal_id, limit, offset,
        )
        return [_snapshot_from_row(dict(r)) for r in rows]


async def advance_round(proposal_id: UUID) -> DebateRoundResponse:
    """Advance to the next debate phase for a proposal."""
    phase_order = ["OPENING", "REBUTTAL", "CLOSING", "VOTING"]

    async with transaction() as conn:
        current = await conn.fetchrow(
            """
            SELECT * FROM debate_rounds
            WHERE proposal_id = $1
            ORDER BY round_number DESC LIMIT 1
            """,
            proposal_id,
        )
        if current is None:
            raise ValueError("No debate rounds exist for this proposal")

        current_phase = current["phase"]
        idx = phase_order.index(current_phase)
        if idx >= len(phase_order) - 1:
            raise ValueError("Debate is already in the final phase (VOTING)")

        next_phase = phase_order[idx + 1]

        # Close current round
        await conn.execute(
            "UPDATE debate_rounds SET ends_at = CURRENT_TIMESTAMP WHERE round_id = $1",
            current["round_id"],
        )

        # Open next round
        now = datetime.now(timezone.utc)
        row = await conn.fetchrow(
            """
            INSERT INTO debate_rounds (proposal_id, round_number, phase, starts_at, ends_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            proposal_id,
            int(current["round_number"]) + 1,
            next_phase,
            now,
            now + timedelta(hours=24),
        )
        return _round_from_row(dict(row))
