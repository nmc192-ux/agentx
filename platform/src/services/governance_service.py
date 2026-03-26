"""
AgentX Platform — Governance Service
═════════════════════════════════════
Phase 9: On-chain-style governance with proposals, voting, and execution.

Public API
──────────
  create_proposal(caller_did, data)    → ProposalResponse
  list_proposals(status)               → list[ProposalResponse]
  vote_on_proposal(caller_did, req)    → VoteResponse
  calculate_vote_power(agent_did)      → float
  finalize_proposal(proposal_id)       → ProposalResponse
  execute_proposal(proposal_id)        → ProposalResponse

Design notes
────────────
• Vote power = SUM(active stakes) × trust_score, computed inline within the
  write transaction using a single connection to avoid stale reads.
• Agent UUID (proposer_id / voter_id) is resolved from the caller's DID
  inside each write transaction — keeping routers free of DB lookups.
• One vote per (proposal_id, voter_id) enforced by DB UNIQUE constraint
  and an app-layer pre-check (raises ValueError before hitting the DB).
• Proposal lifecycle: active → passed | failed → executed.
• finalize_proposal / execute_proposal are service-layer only — no router
  endpoints expose them (used by admin / cron processes).
• Events are fire-and-forget; failures are logged but do not fail the call.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.governance import (
    ProposalCreate,
    ProposalResponse,
    VoteRequest,
    VoteResponse,
)

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row_to_proposal(row) -> ProposalResponse:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else None
    return ProposalResponse(
        proposal_id=row["proposal_id"],
        proposer_did=row["proposer_did"],
        proposer_id=row.get("proposer_id"),
        title=row["title"],
        description=row["description"],
        proposal_type=row["proposal_type"],
        status=row["status"],
        payload=payload,
        yes_power=float(row["yes_power"]),
        no_power=float(row["no_power"]),
        voting_ends_at=row["voting_ends_at"],
        created_at=row["created_at"],
    )


def _row_to_vote(row) -> VoteResponse:
    return VoteResponse(
        vote_id=row["vote_id"],
        proposal_id=row["proposal_id"],
        voter_did=row["voter_did"],
        vote=row["vote"],
        vote_power=float(row["vote_power"]),
        created_at=row["created_at"],
    )


# ── Proposal creation ─────────────────────────────────────────────────────────

async def create_proposal(caller_did: str, data: ProposalCreate) -> ProposalResponse:
    """
    Create a new governance proposal.

    Resolves caller's agent_id from their DID inside the transaction, then
    inserts the proposal row.

    Args:
        caller_did: DID of the proposer (from AgentRecord.did).
        data:       Validated ProposalCreate payload.

    Returns:
        ProposalResponse for the newly created proposal.
    """
    voting_ends_at = datetime.now(UTC) + timedelta(days=data.voting_days)

    async with transaction() as conn:
        # Resolve DID → agent_id
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        caller_id = agent_row["agent_id"] if agent_row else None

        row = await conn.fetchrow(
            """
            INSERT INTO proposals
                (proposer_did, proposer_id, title, description, proposal_type,
                 payload, voting_ends_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            RETURNING
                proposal_id, proposer_did, proposer_id, title, description,
                proposal_type, status, payload, yes_power, no_power,
                voting_ends_at, created_at
            """,
            caller_did,
            caller_id,
            data.title,
            data.description,
            data.proposal_type,
            json.dumps(data.payload) if data.payload else None,
            voting_ends_at,
        )

    proposal = _row_to_proposal(row)

    try:
        await publish_event(
            EventType.PROPOSAL_CREATED,
            {
                "proposal_id": str(proposal.proposal_id),
                "proposer_did": caller_did,
                "title": data.title,
                "proposal_type": data.proposal_type,
            },
            source_agent_did=caller_did,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish PROPOSAL_CREATED", exc_info=True
        )

    logger.info(
        "governance_service: created proposal %s ('%s') by %s",
        proposal.proposal_id, data.title, caller_did,
    )
    return proposal


# ── Proposal listing ──────────────────────────────────────────────────────────

async def list_proposals(status: str | None = "active") -> list[ProposalResponse]:
    """
    Return proposals filtered by status.

    Args:
        status: Filter value ('active', 'passed', 'failed', 'executed', or None
                for all proposals).

    Returns:
        List of ProposalResponse objects ordered by created_at DESC.
    """
    async with get_db() as conn:
        if status is None:
            rows = await conn.fetch(
                """
                SELECT proposal_id, proposer_did, proposer_id, title, description,
                       proposal_type, status, payload, yes_power, no_power,
                       voting_ends_at, created_at
                FROM   proposals
                ORDER BY created_at DESC
                """
            )
        else:
            rows = await conn.fetch(
                """
                SELECT proposal_id, proposer_did, proposer_id, title, description,
                       proposal_type, status, payload, yes_power, no_power,
                       voting_ends_at, created_at
                FROM   proposals
                WHERE  status = $1
                ORDER BY created_at DESC
                """,
                status,
            )
    return [_row_to_proposal(r) for r in rows]


# ── Vote power calculation ─────────────────────────────────────────────────────

async def calculate_vote_power(agent_did: str) -> float:
    """
    Compute an agent's current vote power using a fresh DB connection.

    vote_power = SUM(active stake amounts) × trust_score

    Intended for external/read-only use. Within a write transaction prefer
    to compute inline (see vote_on_proposal).

    Args:
        agent_did: DID of the agent.

    Returns:
        Computed vote power as a float.
    """
    async with get_db() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id, COALESCE(trust_score, 0.0) AS trust_score FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            return 0.0

        total_stake = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM   stakes
            WHERE  agent_id = $1
              AND  released_at IS NULL
            """,
            agent_row["agent_id"],
        ) or 0

    return float(total_stake) * float(agent_row["trust_score"])


# ── Voting ────────────────────────────────────────────────────────────────────

async def vote_on_proposal(caller_did: str, req: VoteRequest) -> VoteResponse:
    """
    Cast a vote on an active proposal.

    Resolves caller's agent_id from their DID inside the transaction, then
    validates the proposal state, computes vote power, and inserts the vote.

    Args:
        caller_did: DID of the voter (from AgentRecord.did).
        req:        VoteRequest containing proposal_id and vote direction.

    Returns:
        VoteResponse for the recorded vote.

    Raises:
        ValueError: Agent not found, proposal not found, not active,
                    already voted, or voting closed.
    """
    async with transaction() as conn:
        # 1. Resolve voter DID → agent_id
        voter_row = await conn.fetchrow(
            "SELECT agent_id, COALESCE(trust_score, 0.0) AS trust_score FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if voter_row is None:
            raise ValueError(f"Agent not found: {caller_did}")
        caller_id   = voter_row["agent_id"]
        trust_score = float(voter_row["trust_score"])

        # 2. Look up the proposal
        proposal = await conn.fetchrow(
            """
            SELECT proposal_id, status, voting_ends_at
            FROM   proposals
            WHERE  proposal_id = $1
            """,
            req.proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {req.proposal_id}")
        if proposal["status"] != "active":
            raise ValueError(
                f"Proposal {req.proposal_id} is not active (status={proposal['status']})"
            )
        if datetime.now(UTC) > proposal["voting_ends_at"].replace(tzinfo=UTC):
            raise ValueError(f"Voting period closed for proposal {req.proposal_id}")

        # 3. Check for duplicate vote (app-layer guard before DB UNIQUE fires)
        existing_vote = await conn.fetchval(
            """
            SELECT vote_id FROM governance_votes
            WHERE  proposal_id = $1 AND voter_id = $2
            """,
            req.proposal_id,
            caller_id,
        )
        if existing_vote is not None:
            raise ValueError(
                f"Agent {caller_did} has already voted on proposal {req.proposal_id}"
            )

        # 4. Compute vote power inline (trust fetched with voter_row above)
        total_stake = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM   stakes
            WHERE  agent_id = $1 AND released_at IS NULL
            """,
            caller_id,
        ) or 0

        vote_power = float(total_stake) * trust_score

        # 5. Insert vote
        vote_row = await conn.fetchrow(
            """
            INSERT INTO governance_votes
                (proposal_id, voter_id, voter_did, vote, vote_power)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING vote_id, proposal_id, voter_did, vote, vote_power, created_at
            """,
            req.proposal_id,
            caller_id,
            caller_did,
            req.vote,
            vote_power,
        )

        # 6. Update running tallies on proposal
        if req.vote == "yes":
            await conn.execute(
                """
                UPDATE proposals
                   SET yes_power = yes_power + $1
                 WHERE proposal_id = $2
                """,
                vote_power,
                req.proposal_id,
            )
        elif req.vote == "no":
            await conn.execute(
                """
                UPDATE proposals
                   SET no_power = no_power + $1
                 WHERE proposal_id = $2
                """,
                vote_power,
                req.proposal_id,
            )
        # abstain: tallies unchanged (vote is still recorded)

    vote = _row_to_vote(vote_row)

    try:
        await publish_event(
            EventType.VOTE_CAST,
            {
                "vote_id": str(vote.vote_id),
                "proposal_id": str(vote.proposal_id),
                "voter_did": caller_did,
                "vote": req.vote,
                "vote_power": vote_power,
            },
            source_agent_did=caller_did,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish VOTE_CAST", exc_info=True
        )

    logger.info(
        "governance_service: vote %s cast by %s on proposal %s (power=%.4f)",
        req.vote, caller_did, req.proposal_id, vote_power,
    )
    return vote


# ── Finalization ──────────────────────────────────────────────────────────────

async def finalize_proposal(proposal_id: UUID) -> ProposalResponse:
    """
    Finalize an active proposal whose voting period has closed.

    Determines outcome by yes_power vs no_power and transitions status to
    'passed' or 'failed'. Idempotent if already finalized.

    Args:
        proposal_id: UUID of the proposal to finalize.

    Returns:
        Updated ProposalResponse.

    Raises:
        ValueError: Proposal not found.
    """
    async with transaction() as conn:
        proposal = await conn.fetchrow(
            """
            SELECT proposal_id, status, yes_power, no_power, voting_ends_at
            FROM   proposals
            WHERE  proposal_id = $1
            """,
            proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")

        if proposal["status"] != "active":
            # Already finalized — re-fetch full row and return
            row = await conn.fetchrow(
                """
                SELECT proposal_id, proposer_did, proposer_id, title, description,
                       proposal_type, status, payload, yes_power, no_power,
                       voting_ends_at, created_at
                FROM   proposals
                WHERE  proposal_id = $1
                """,
                proposal_id,
            )
            return _row_to_proposal(row)

        yes_power = float(proposal["yes_power"])
        no_power  = float(proposal["no_power"])
        new_status = "passed" if yes_power > no_power else "failed"

        row = await conn.fetchrow(
            """
            UPDATE proposals
               SET status = $1
             WHERE proposal_id = $2
            RETURNING
                proposal_id, proposer_did, proposer_id, title, description,
                proposal_type, status, payload, yes_power, no_power,
                voting_ends_at, created_at
            """,
            new_status,
            proposal_id,
        )

    logger.info(
        "governance_service: finalized proposal %s → %s (yes=%.4f, no=%.4f)",
        proposal_id, new_status, yes_power, no_power,
    )
    return _row_to_proposal(row)


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_proposal(proposal_id: UUID) -> ProposalResponse:
    """
    Execute a passed proposal (transition to 'executed' status).

    In Phase 9 execution is a status transition only; payload-driven
    side-effects can be added in future phases.

    Args:
        proposal_id: UUID of the proposal to execute.

    Returns:
        Updated ProposalResponse.

    Raises:
        ValueError: Proposal not found or not in 'passed' status.
    """
    async with transaction() as conn:
        proposal = await conn.fetchrow(
            "SELECT status FROM proposals WHERE proposal_id = $1",
            proposal_id,
        )
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal["status"] != "passed":
            raise ValueError(
                f"Proposal {proposal_id} cannot be executed (status={proposal['status']})"
            )

        row = await conn.fetchrow(
            """
            UPDATE proposals
               SET status = 'executed'
             WHERE proposal_id = $1
            RETURNING
                proposal_id, proposer_did, proposer_id, title, description,
                proposal_type, status, payload, yes_power, no_power,
                voting_ends_at, created_at
            """,
            proposal_id,
        )

    result = _row_to_proposal(row)

    try:
        await publish_event(
            EventType.PROPOSAL_EXECUTED,
            {
                "proposal_id": str(proposal_id),
                "yes_power": result.yes_power,
                "no_power": result.no_power,
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "governance_service: failed to publish PROPOSAL_EXECUTED", exc_info=True
        )

    logger.info("governance_service: executed proposal %s", proposal_id)
    return result
