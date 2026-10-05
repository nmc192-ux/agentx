"""
AgentX Platform — Result Verification Engine Service
══════════════════════════════════════════════════════
Phase 12: Decentralised result verification using stake-weighted voting.

When a contractor submits a contract result the creator can open a
verification request.  A pool of eligible agents votes (approve/reject)
weighted by stake × trust_score.  After ``required_votes`` are collected
the verification auto-finalises; it can also be finalised manually.

Public API
──────────
  create_verification(caller_did, data)               → VerificationResponse
  assign_verifiers(verification_id, caller_did)       → VerificationResponse
  submit_vote(verification_id, caller_did, data)      → VerificationVoteResponse
  calculate_consensus(verification_id)                → VerificationConsensusResponse
  finalize_verification(verification_id)              → VerificationResponse
  get_verification(verification_id)                   → VerificationResponse
  list_pending_verifications()                        → list[VerificationResponse]

Design notes
────────────
• DID → UUID resolution is always performed inside the transaction.
• Vote power = max(1.0, SUM(active stakes) × trust_score) so every
  eligible agent has at least a base weight of 1.
• Auto-finalisation triggers inside submit_vote() when
  vote_count >= required_votes; finalize_verification() is also callable
  manually (idempotent if already finalised).
• submit_vote() and finalize_verification() lock the verification row
  (``FOR UPDATE``) before reading its status, so a verification is finalised
  once and no vote can land on one that is already finalised (Sprint 9, S9-6b).
• Neither party to the contract votes: not the requester (the creator) and
  not the contractor whose result is being verified.
• A verification is advisory: it never changes the contract or moves its
  escrow. The creator still decides (contract_service.complete_contract).
• Verifier rewards are NOT paid (S9-6b): nothing ever funds ``reward_pool``
  (no wallet is debited for it), so paying from it would create tokens from
  nothing. See _distribute_rewards.
• Trust (S9-9b): once a verification is final, the verifiers on the winning
  side get one ``peer_validation`` each (reputation.record_verification_outcome).
• Events are fire-and-forget; failures are logged, never bubble up.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.verification import (
    VerificationConsensusResponse,
    VerificationCreate,
    VerificationResponse,
    VerificationVoteCreate,
    VerificationVoteResponse,
)
from .reputation import record_verification_outcome

logger = logging.getLogger(__name__)

_VERIFICATION_COLS = """
    verification_id, contract_id, result_id, requester_did, requester_id,
    status, required_votes, consensus_threshold, yes_power, no_power,
    vote_count, reward_pool, created_at, finalized_at
"""

_VOTE_COLS = """
    vote_id, verification_id, verifier_did, vote, vote_power, comment, created_at
"""


# ── Row converters ─────────────────────────────────────────────────────────────

def _row_to_verification(row) -> VerificationResponse:
    return VerificationResponse(
        verification_id=row["verification_id"],
        contract_id=row["contract_id"],
        result_id=row["result_id"],
        requester_did=row["requester_did"],
        requester_id=row.get("requester_id"),
        status=row["status"],
        required_votes=row["required_votes"],
        consensus_threshold=float(row["consensus_threshold"]),
        yes_power=float(row["yes_power"]),
        no_power=float(row["no_power"]),
        vote_count=row["vote_count"],
        reward_pool=row["reward_pool"],
        created_at=row["created_at"],
        finalized_at=row.get("finalized_at"),
    )


def _row_to_vote(row) -> VerificationVoteResponse:
    return VerificationVoteResponse(
        vote_id=row["vote_id"],
        verification_id=row["verification_id"],
        verifier_did=row["verifier_did"],
        vote=row["vote"],
        vote_power=float(row["vote_power"]),
        comment=row.get("comment"),
        created_at=row["created_at"],
    )


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _resolve_vote_power(conn, agent_id: UUID, trust_score: float) -> float:
    """
    Compute vote_power = max(1.0, SUM(active stakes) × trust_score).
    Ensures every agent has a minimum weight of 1.0.
    """
    total_stake = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM   stakes
        WHERE  agent_id = $1 AND released_at IS NULL
        """,
        agent_id,
    ) or 0
    return max(1.0, float(total_stake) * trust_score)


async def _do_activate(conn, verification_id: UUID):
    """Transition a verification from 'pending' to 'active' (no-commit helper)."""
    return await conn.fetchrow(
        f"""
        UPDATE verifications
           SET status = 'active'
         WHERE verification_id = $1
        RETURNING {_VERIFICATION_COLS}
        """,
        verification_id,
    )


async def _distribute_rewards(conn, verification_id: UUID, winning_vote: str) -> None:
    """
    Verifier rewards — deliberately pays nothing (Sprint 9, S9-6b).

    This used to split ``verifications.reward_pool`` between the winning-side
    voters by crediting their wallets. But no code path ever *funds* that pool:
    the API always creates it as 0 and no wallet is debited for it. Paying out
    a non-zero pool (settable only by a direct database write) would therefore
    create tokens from nothing. Until verifier rewards are designed with a
    real source of funds (e.g. a slice of the contract's escrow), fail closed:
    credit nobody, and say so in the log if a pool was set.
    """
    reward_pool = await conn.fetchval(
        "SELECT reward_pool FROM verifications WHERE verification_id = $1",
        verification_id,
    )
    if reward_pool and reward_pool > 0:
        logger.warning(
            "verification_service: verification %s has an unfunded reward_pool "
            "of %d — NOT distributed (winning vote: %s)",
            verification_id, reward_pool, winning_vote,
        )


# ── Public service functions ───────────────────────────────────────────────────

async def create_verification(
    caller_did: str,
    data: VerificationCreate,
) -> VerificationResponse:
    """
    Create a verification request for a submitted contract result.

    The caller must be the contract creator.  The contract must be in
    'submitted' state.  The result must belong to the contract.
    After creation the verification is immediately activated.

    Args:
        caller_did: DID of the authenticated caller (must be contract creator).
        data:       Validated VerificationCreate payload.

    Returns:
        VerificationResponse with status='active'.

    Raises:
        ValueError: Contract/result not found, caller not creator, wrong status.
    """
    async with transaction() as conn:
        # Validate contract exists and caller is the creator
        contract = await conn.fetchrow(
            "SELECT contract_id, creator_did, status FROM contracts WHERE contract_id = $1",
            data.contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {data.contract_id}")
        if contract["creator_did"] != caller_did:
            raise ValueError("Only the contract creator can request verification")
        if contract["status"] != "submitted":
            raise ValueError(
                f"Contract must be in 'submitted' state for verification "
                f"(status={contract['status']})"
            )

        # Validate result exists and belongs to this contract
        result = await conn.fetchrow(
            """
            SELECT result_id
            FROM   contract_results
            WHERE  result_id = $1 AND contract_id = $2
            """,
            data.result_id,
            data.contract_id,
        )
        if result is None:
            raise ValueError(
                f"Result {data.result_id} not found for contract {data.contract_id}"
            )

        # Resolve requester DID → agent_id (NULL-safe)
        requester_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        requester_id = requester_row["agent_id"] if requester_row else None

        # Insert verification (status='pending')
        row = await conn.fetchrow(
            f"""
            INSERT INTO verifications
                (contract_id, result_id, requester_did, requester_id)
            VALUES ($1, $2, $3, $4)
            RETURNING {_VERIFICATION_COLS}
            """,
            data.contract_id,
            data.result_id,
            caller_did,
            requester_id,
        )
        verification_id = row["verification_id"]

        # Immediately activate (pending → active)
        activated = await _do_activate(conn, verification_id)
        row = activated if activated is not None else row

    verification = _row_to_verification(row)

    try:
        await publish_event(
            EventType.CONTRACT_VERIFICATION_REQUESTED,
            {
                "verification_id": str(verification_id),
                "contract_id":     str(data.contract_id),
                "result_id":       str(data.result_id),
                "requester_did":   caller_did,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "verification_service: failed to publish CONTRACT_VERIFICATION_REQUESTED",
            exc_info=True,
        )

    logger.info(
        "verification_service: verification %s created by %s for contract %s",
        verification_id, caller_did, data.contract_id,
    )
    return verification


async def assign_verifiers(
    verification_id: UUID,
    caller_did: str,
) -> VerificationResponse:
    """
    Explicitly activate a pending verification.

    Transitions the verification from 'pending' to 'active', enabling
    votes to be submitted.  Can be called by any authenticated agent.
    (Verifications created via ``create_verification`` are automatically
    activated; this function exists for manual activation of pending ones.)

    Args:
        verification_id: UUID of the verification to activate.
        caller_did:      DID of the caller (for audit; not restricted).

    Returns:
        VerificationResponse with status='active'.

    Raises:
        ValueError: Verification not found or not in 'pending' state.
    """
    async with transaction() as conn:
        v = await conn.fetchrow(
            "SELECT verification_id, status FROM verifications WHERE verification_id = $1",
            verification_id,
        )
        if v is None:
            raise ValueError(f"Verification not found: {verification_id}")
        if v["status"] != "pending":
            raise ValueError(
                f"Verification is not pending (status={v['status']})"
            )

        row = await _do_activate(conn, verification_id)

    logger.info(
        "verification_service: verification %s activated by %s",
        verification_id, caller_did,
    )
    return _row_to_verification(row)


async def submit_vote(
    verification_id: UUID,
    caller_did: str,
    data: VerificationVoteCreate,
) -> VerificationVoteResponse:
    """
    Submit a vote on an active verification.

    Vote power = max(1.0, SUM(active stakes) × trust_score).
    Caller must not be the verification requester or the contractor whose
    result is being verified, and must not have already voted.  After each
    vote, if vote_count ≥ required_votes the verification is auto-finalised
    in the same transaction.

    Args:
        verification_id: UUID of the target verification.
        caller_did:      DID of the voting agent.
        data:            Validated VerificationVoteCreate payload.

    Returns:
        VerificationVoteResponse for the recorded vote.

    Raises:
        ValueError:      Verification not found/not active, duplicate vote,
                         or verifier not found.
        PermissionError: the caller is the requester, or the contractor whose
                         result is being verified.
    """
    async with transaction() as conn:
        # Fetch verification and hold its row lock: votes on one verification
        # are serialised, so the status read here cannot go stale and the
        # verification is finalised exactly once.
        verification = await conn.fetchrow(
            f"""
            SELECT {_VERIFICATION_COLS} FROM verifications
            WHERE verification_id = $1
            FOR UPDATE
            """,
            verification_id,
        )
        if verification is None:
            raise ValueError(f"Verification not found: {verification_id}")
        if verification["status"] != "active":
            raise ValueError(
                f"Verification is not active (status={verification['status']})"
            )

        # Neither party to the contract may vote.
        if verification["requester_did"] == caller_did:
            raise PermissionError(
                "The verification requester cannot vote on their own verification"
            )
        contractor_did = await conn.fetchval(
            "SELECT contractor_did FROM contract_results WHERE result_id = $1",
            verification["result_id"],
        )
        if contractor_did == caller_did:
            raise PermissionError(
                "The contractor cannot vote on the verification of their own result"
            )

        # Resolve verifier DID → agent_id + trust_score
        verifier_row = await conn.fetchrow(
            """
            SELECT agent_id, COALESCE(trust_score, 0.0) AS trust_score
            FROM   agents
            WHERE  agent_did = $1
            """,
            caller_did,
        )
        if verifier_row is None:
            raise ValueError(f"Verifier agent not found: {caller_did}")
        verifier_id  = verifier_row["agent_id"]
        trust_score  = float(verifier_row["trust_score"])

        # Guard against duplicate votes (DB UNIQUE also enforces this)
        existing = await conn.fetchval(
            """
            SELECT vote_id FROM verification_votes
            WHERE  verification_id = $1 AND verifier_id = $2
            """,
            verification_id,
            verifier_id,
        )
        if existing is not None:
            raise ValueError(
                f"Agent {caller_did} has already voted on verification {verification_id}"
            )

        # Calculate vote_power
        vote_power = await _resolve_vote_power(conn, verifier_id, trust_score)

        # Insert vote
        vote_row = await conn.fetchrow(
            f"""
            INSERT INTO verification_votes
                (verification_id, verifier_did, verifier_id, vote, vote_power, comment)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {_VOTE_COLS}
            """,
            verification_id,
            caller_did,
            verifier_id,
            data.vote,
            vote_power,
            data.comment,
        )

        # Update running tallies on verification
        if data.vote == "approve":
            await conn.execute(
                """
                UPDATE verifications
                   SET yes_power  = yes_power + $1,
                       vote_count = vote_count + 1
                 WHERE verification_id = $2
                """,
                vote_power,
                verification_id,
            )
        else:
            await conn.execute(
                """
                UPDATE verifications
                   SET no_power   = no_power + $1,
                       vote_count = vote_count + 1
                 WHERE verification_id = $2
                """,
                vote_power,
                verification_id,
            )

        # Re-fetch to get updated vote_count for auto-finalise check
        updated_v = await conn.fetchrow(
            "SELECT vote_count, required_votes FROM verifications WHERE verification_id = $1",
            verification_id,
        )

        # Auto-finalise when enough votes have been collected
        finalised = updated_v["vote_count"] >= updated_v["required_votes"]
        if finalised:
            await _do_finalize(conn, verification_id)

    vote = _row_to_vote(vote_row)

    # S9-9b: a vote earns trust only once the outcome is known, and only on
    # the winning side (it was +0.03 for every vote cast, through the bus).
    if finalised:
        await record_verification_outcome(verification_id)

    try:
        await publish_event(
            EventType.VERIFICATION_SUBMITTED,
            {
                "vote_id":         str(vote.vote_id),
                "verification_id": str(verification_id),
                "verifier_did":    caller_did,
                "vote":            data.vote,
                "vote_power":      vote_power,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "verification_service: failed to publish VERIFICATION_SUBMITTED",
            exc_info=True,
        )

    logger.info(
        "verification_service: vote %s ('%s') submitted by %s on verification %s",
        vote.vote_id, data.vote, caller_did, verification_id,
    )
    return vote


async def _do_finalize(conn, verification_id: UUID) -> None:
    """
    Internal helper: compute consensus and transition the verification to
    'verified' or 'failed' within an already-open connection.
    """
    v = await conn.fetchrow(
        "SELECT yes_power, no_power, consensus_threshold, status FROM verifications "
        "WHERE verification_id = $1",
        verification_id,
    )
    if v is None or v["status"] in ("verified", "failed"):
        return  # Already finalised or not found

    total = float(v["yes_power"]) + float(v["no_power"])
    yes_ratio  = float(v["yes_power"]) / total if total > 0 else 0.0
    new_status = "verified" if yes_ratio >= float(v["consensus_threshold"]) else "failed"
    winning_vote = "approve" if new_status == "verified" else "reject"

    await conn.execute(
        """
        UPDATE verifications
           SET status       = $2,
               finalized_at = NOW()
         WHERE verification_id = $1
        """,
        verification_id,
        new_status,
    )

    # Verifier rewards: pays nothing today (see _distribute_rewards).
    await _distribute_rewards(conn, verification_id, winning_vote)

    # Publish event (can't await inside sync helper — use a sync-friendly flag)
    # Events are published after the transaction commits in finalize_verification().
    # Here we just log for the auto-finalise case.
    logger.info(
        "verification_service: verification %s auto-finalised as '%s'",
        verification_id, new_status,
    )


async def calculate_consensus(verification_id: UUID) -> VerificationConsensusResponse:
    """
    Calculate the current consensus state of a verification (read-only).

    Returns the outcome if vote_count >= required_votes, otherwise None.

    Args:
        verification_id: UUID of the verification to inspect.

    Returns:
        VerificationConsensusResponse with current tallies and optional outcome.

    Raises:
        ValueError: Verification not found.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT verification_id, status, required_votes, consensus_threshold,
                   yes_power, no_power, vote_count
            FROM   verifications
            WHERE  verification_id = $1
            """,
            verification_id,
        )
    if row is None:
        raise ValueError(f"Verification not found: {verification_id}")

    total     = float(row["yes_power"]) + float(row["no_power"])
    yes_ratio = float(row["yes_power"]) / total if total > 0 else 0.0

    outcome: str | None = None
    if row["vote_count"] >= row["required_votes"]:
        outcome = (
            "verified"
            if yes_ratio >= float(row["consensus_threshold"])
            else "failed"
        )

    return VerificationConsensusResponse(
        verification_id=row["verification_id"],
        yes_power=float(row["yes_power"]),
        no_power=float(row["no_power"]),
        vote_count=row["vote_count"],
        required_votes=row["required_votes"],
        consensus_threshold=float(row["consensus_threshold"]),
        yes_ratio=yes_ratio,
        outcome=outcome,
    )


async def finalize_verification(verification_id: UUID) -> VerificationResponse:
    """
    Manually finalise a verification, transitioning it to 'verified' or
    'failed' based on the current vote tallies.

    Idempotent: if already finalised, returns the current state.

    Args:
        verification_id: UUID of the verification to finalise.

    Returns:
        Updated VerificationResponse with final status.

    Raises:
        ValueError: Verification not found or still in 'pending' state.
    """
    async with transaction() as conn:
        verification = await conn.fetchrow(
            f"""
            SELECT {_VERIFICATION_COLS} FROM verifications
            WHERE verification_id = $1
            FOR UPDATE
            """,
            verification_id,
        )
        if verification is None:
            raise ValueError(f"Verification not found: {verification_id}")

        # Idempotency: already finalised
        if verification["status"] in ("verified", "failed"):
            return _row_to_verification(verification)

        if verification["status"] == "pending":
            raise ValueError(
                "Verification must be activated before it can be finalised"
            )

        # Compute outcome
        total     = float(verification["yes_power"]) + float(verification["no_power"])
        yes_ratio = float(verification["yes_power"]) / total if total > 0 else 0.0
        new_status   = "verified" if yes_ratio >= float(verification["consensus_threshold"]) else "failed"
        winning_vote = "approve" if new_status == "verified" else "reject"

        updated = await conn.fetchrow(
            f"""
            UPDATE verifications
               SET status       = $2,
                   finalized_at = NOW()
             WHERE verification_id = $1
            RETURNING {_VERIFICATION_COLS}
            """,
            verification_id,
            new_status,
        )

        # Verifier rewards: pays nothing today (see _distribute_rewards).
        await _distribute_rewards(conn, verification_id, winning_vote)

    result = _row_to_verification(updated)

    await record_verification_outcome(verification_id)

    # Publish post-transaction event
    event_type = (
        EventType.CONTRACT_VERIFIED
        if new_status == "verified"
        else EventType.VERIFICATION_FAILED
    )
    try:
        await publish_event(
            event_type,
            {
                "verification_id": str(verification_id),
                "contract_id":     str(verification["contract_id"]),
                "status":          new_status,
                "yes_power":       float(verification["yes_power"]),
                "no_power":        float(verification["no_power"]),
            },
        )
    except Exception:
        logger.warning(
            "verification_service: failed to publish %s", event_type, exc_info=True
        )

    logger.info(
        "verification_service: verification %s finalised as '%s'",
        verification_id, new_status,
    )
    return result


async def get_verification(verification_id: UUID) -> VerificationResponse:
    """
    Fetch a single verification by ID.

    Args:
        verification_id: UUID to look up.

    Returns:
        VerificationResponse.

    Raises:
        ValueError: Verification not found.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"SELECT {_VERIFICATION_COLS} FROM verifications WHERE verification_id = $1",
            verification_id,
        )
    if row is None:
        raise ValueError(f"Verification not found: {verification_id}")
    return _row_to_verification(row)


async def list_pending_verifications() -> list[VerificationResponse]:
    """
    List all pending and active verifications, newest first.

    Returns:
        List of VerificationResponse objects with status in ('pending', 'active').
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_VERIFICATION_COLS}
            FROM   verifications
            WHERE  status IN ('pending', 'active')
            ORDER  BY created_at DESC
            """
        )
    return [_row_to_verification(r) for r in rows]
