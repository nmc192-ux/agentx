"""
AgentX Platform — Capability Bounty Service
════════════════════════════════════════════
Phase 15: Autonomous Agent Markets.

Organisations post capability bounties; agents compete to win the reward pool
by submitting solutions.  The bounty creator evaluates submissions and the
winner receives the entire reward_pool.

Public API
──────────
  create_bounty(caller_did, data)                     → BountyResponse
  list_bounties(status, capability)                   → list[BountyResponse]
  get_bounty(bounty_id)                               → BountyResponse
  submit_solution(bounty_id, caller_did, data)        → SubmissionResponse
  evaluate_submission(bounty_id, submission_id,
                      caller_did, score)              → SubmissionResponse
  distribute_rewards(bounty_id, caller_did)           → RewardResponse
  list_submissions(bounty_id)                         → list[SubmissionResponse]

Integration
───────────
• Economy: creator's wallet is debited reward_pool on bounty creation
  (escrowed via a NULL-to-NULL ledger debit so the balance is locked).
• Reward distribution: the escrow is credited to the winning submitter's
  wallet.  Soft-fail: credit errors are logged, never bubble up.
• Events: fire-and-forget; failures are logged, never propagate.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ...database import get_db, transaction
from ...events.publisher import publish_event
from ...events.types import EventType
from ...models.markets import (
    BountyCreate,
    BountyResponse,
    EvaluateSubmission,
    RewardResponse,
    SubmissionCreate,
    SubmissionResponse,
)

logger = logging.getLogger(__name__)

_BOUNTY_COLS = """
    bounty_id, creator_did, creator_id, title, description,
    capability_required, reward_pool, status, deadline,
    winner_submission_id, created_at, closed_at
"""

_SUBMISSION_COLS = """
    submission_id, bounty_id, submitter_did, submitter_id,
    solution_data, summary, score, status, submitted_at, evaluated_at
"""


# ── Row converters ─────────────────────────────────────────────────────────────

def _row_to_bounty(row: Any) -> BountyResponse:
    return BountyResponse(
        bounty_id=row["bounty_id"],
        creator_did=row["creator_did"],
        creator_id=row.get("creator_id"),
        title=row["title"],
        description=row["description"],
        capability_required=row["capability_required"],
        reward_pool=row["reward_pool"],
        status=row["status"],
        deadline=row.get("deadline"),
        winner_submission_id=row.get("winner_submission_id"),
        created_at=row["created_at"],
        closed_at=row.get("closed_at"),
    )


def _row_to_submission(row: Any) -> SubmissionResponse:
    import json as _json
    solution_data = row["solution_data"]
    if isinstance(solution_data, str):
        solution_data = _json.loads(solution_data)
    return SubmissionResponse(
        submission_id=row["submission_id"],
        bounty_id=row["bounty_id"],
        submitter_did=row["submitter_did"],
        submitter_id=row.get("submitter_id"),
        solution_data=solution_data,
        summary=row.get("summary"),
        score=float(row["score"]) if row.get("score") is not None else None,
        status=row["status"],
        submitted_at=row["submitted_at"],
        evaluated_at=row.get("evaluated_at"),
    )


# ── Public service functions ───────────────────────────────────────────────────

async def create_bounty(
    caller_did: str,
    data: BountyCreate,
) -> BountyResponse:
    """
    Create a new capability bounty.

    The caller's wallet is debited by *reward_pool* tokens immediately to
    escrow the prize.  If the wallet has insufficient funds the operation
    raises ValueError and no bounty is created.

    Args:
        caller_did: DID of the authenticated caller (bounty creator).
        data:       Validated BountyCreate payload.

    Returns:
        BountyResponse with status='open'.

    Raises:
        ValueError: Caller agent not found, wallet not found, or insufficient funds.
    """
    async with transaction() as conn:
        # Resolve DID → agent_id
        creator_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        creator_id: UUID | None = creator_row["agent_id"] if creator_row else None

        # Escrow reward_pool: debit caller wallet (to_wallet=NULL means escrow)
        if data.reward_pool > 0:
            wallet_row = await conn.fetchrow(
                """
                UPDATE wallets
                   SET balance    = balance - $1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE agent_id = $2
                   AND balance  >= $1
                RETURNING wallet_id
                """,
                data.reward_pool,
                creator_id,
            )
            if wallet_row is None:
                exists = await conn.fetchval(
                    "SELECT 1 FROM wallets WHERE agent_id = $1", creator_id
                )
                if not exists:
                    raise ValueError(f"Wallet not found for agent: {caller_did}")
                raise ValueError(
                    f"Insufficient funds: cannot escrow {data.reward_pool} tokens for bounty"
                )

            # Ledger record: from_wallet → NULL (escrow)
            await conn.execute(
                """
                INSERT INTO transactions
                    (from_wallet, to_wallet, amount, type, related_id)
                VALUES ($1, NULL, $2, 'bounty_escrow', NULL)
                """,
                wallet_row["wallet_id"],
                data.reward_pool,
            )

        # Insert bounty
        row = await conn.fetchrow(
            f"""
            INSERT INTO capability_bounties
                (creator_did, creator_id, title, description,
                 capability_required, reward_pool, deadline)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING {_BOUNTY_COLS}
            """,
            caller_did,
            creator_id,
            data.title,
            data.description,
            data.capability_required,
            data.reward_pool,
            data.deadline,
        )

    bounty = _row_to_bounty(row)

    try:
        await publish_event(
            EventType.BOUNTY_CREATED,
            {
                "bounty_id":           str(bounty.bounty_id),
                "creator_did":         caller_did,
                "title":               bounty.title,
                "capability_required": bounty.capability_required,
                "reward_pool":         bounty.reward_pool,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "bounty_service: failed to publish BOUNTY_CREATED for %s",
            bounty.bounty_id, exc_info=True,
        )

    logger.info(
        "bounty_service: bounty %s created by %s (pool=%d)",
        bounty.bounty_id, caller_did, bounty.reward_pool,
    )
    return bounty


async def list_bounties(
    status: str | None = None,
    capability: str | None = None,
) -> list[BountyResponse]:
    """
    List bounties, optionally filtered by status and/or capability.

    Args:
        status:     e.g. 'open', 'closed', 'rewarded'. None = all.
        capability: capability_required filter. None = all.

    Returns:
        List of BountyResponse, newest first.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if status is not None:
        params.append(status)
        conditions.append(f"status = ${len(params)}")

    if capability is not None:
        params.append(capability)
        conditions.append(f"capability_required = ${len(params)}")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT {_BOUNTY_COLS} FROM capability_bounties {where_clause} ORDER BY created_at DESC",
            *params,
        )

    return [_row_to_bounty(r) for r in rows]


async def get_bounty(bounty_id: UUID) -> BountyResponse:
    """
    Fetch a single bounty by ID.

    Raises:
        ValueError: Bounty not found.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"SELECT {_BOUNTY_COLS} FROM capability_bounties WHERE bounty_id = $1",
            bounty_id,
        )
    if row is None:
        raise ValueError(f"Bounty not found: {bounty_id}")
    return _row_to_bounty(row)


async def submit_solution(
    bounty_id: UUID,
    caller_did: str,
    data: SubmissionCreate,
) -> SubmissionResponse:
    """
    Submit a solution to an open bounty.

    Args:
        bounty_id:  UUID of the target bounty.
        caller_did: DID of the submitting agent.
        data:       Validated SubmissionCreate payload.

    Returns:
        SubmissionResponse with status='pending'.

    Raises:
        ValueError: Bounty not found or not in 'open' status.
    """
    import json as _json

    async with transaction() as conn:
        # Validate bounty exists and is open
        bounty = await conn.fetchrow(
            "SELECT bounty_id, status, creator_did FROM capability_bounties WHERE bounty_id = $1",
            bounty_id,
        )
        if bounty is None:
            raise ValueError(f"Bounty not found: {bounty_id}")
        if bounty["status"] != "open":
            raise ValueError(
                f"Bounty is not open for submissions (status={bounty['status']})"
            )

        # Resolve submitter DID → agent_id
        submitter_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        submitter_id: UUID | None = submitter_row["agent_id"] if submitter_row else None

        # Insert submission
        row = await conn.fetchrow(
            f"""
            INSERT INTO bounty_submissions
                (bounty_id, submitter_did, submitter_id, solution_data, summary)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            RETURNING {_SUBMISSION_COLS}
            """,
            bounty_id,
            caller_did,
            submitter_id,
            _json.dumps(data.solution_data),
            data.summary,
        )

    submission = _row_to_submission(row)

    try:
        await publish_event(
            EventType.BOUNTY_SUBMISSION,
            {
                "submission_id": str(submission.submission_id),
                "bounty_id":     str(bounty_id),
                "submitter_did": caller_did,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "bounty_service: failed to publish BOUNTY_SUBMISSION for %s",
            submission.submission_id, exc_info=True,
        )

    logger.info(
        "bounty_service: submission %s by %s for bounty %s",
        submission.submission_id, caller_did, bounty_id,
    )
    return submission


async def evaluate_submission(
    bounty_id: UUID,
    submission_id: UUID,
    caller_did: str,
    score: float,
) -> SubmissionResponse:
    """
    Score a bounty submission (bounty creator only).

    Args:
        bounty_id:     UUID of the parent bounty.
        submission_id: UUID of the submission to score.
        caller_did:    DID of the caller (must be bounty creator).
        score:         Float in [0.0, 1.0].

    Returns:
        SubmissionResponse with updated score and status='evaluated'.

    Raises:
        ValueError: Bounty/submission not found, caller not creator,
                    or bounty already closed.
    """
    async with transaction() as conn:
        bounty = await conn.fetchrow(
            "SELECT bounty_id, status, creator_did FROM capability_bounties WHERE bounty_id = $1",
            bounty_id,
        )
        if bounty is None:
            raise ValueError(f"Bounty not found: {bounty_id}")
        if bounty["creator_did"] != caller_did:
            raise ValueError("Only the bounty creator can evaluate submissions")
        if bounty["status"] not in ("open", "evaluating"):
            raise ValueError(
                f"Bounty cannot be evaluated in status '{bounty['status']}'"
            )

        row = await conn.fetchrow(
            f"""
            UPDATE bounty_submissions
               SET score        = $1,
                   status       = 'evaluated',
                   evaluated_at = NOW()
             WHERE submission_id = $2
               AND bounty_id     = $3
            RETURNING {_SUBMISSION_COLS}
            """,
            score,
            submission_id,
            bounty_id,
        )
        if row is None:
            raise ValueError(
                f"Submission {submission_id} not found for bounty {bounty_id}"
            )

        # Transition bounty to 'evaluating' if still open
        await conn.execute(
            """
            UPDATE capability_bounties
               SET status = 'evaluating'
             WHERE bounty_id = $1 AND status = 'open'
            """,
            bounty_id,
        )

    submission = _row_to_submission(row)

    try:
        await publish_event(
            EventType.BOUNTY_EVALUATED,
            {
                "submission_id": str(submission_id),
                "bounty_id":     str(bounty_id),
                "score":         score,
                "evaluator_did": caller_did,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "bounty_service: failed to publish BOUNTY_EVALUATED for %s",
            submission_id, exc_info=True,
        )

    logger.info(
        "bounty_service: submission %s scored %.2f by %s",
        submission_id, score, caller_did,
    )
    return submission


async def distribute_rewards(
    bounty_id: UUID,
    caller_did: str,
) -> RewardResponse:
    """
    Close the bounty and distribute the reward pool to the top-scoring submission.

    The submission with the highest score is declared the winner.  The bounty's
    escrowed reward_pool is credited to the winner's wallet.  Soft-fail: credit
    errors are logged but do not roll back the bounty closure.

    Args:
        bounty_id:  UUID of the bounty to close.
        caller_did: DID of the caller (must be the bounty creator).

    Returns:
        RewardResponse describing the payment.

    Raises:
        ValueError: Bounty not found, caller not creator, bounty already closed,
                    or no evaluated submissions found.
    """
    async with transaction() as conn:
        bounty = await conn.fetchrow(
            f"SELECT {_BOUNTY_COLS} FROM capability_bounties WHERE bounty_id = $1",
            bounty_id,
        )
        if bounty is None:
            raise ValueError(f"Bounty not found: {bounty_id}")
        if bounty["creator_did"] != caller_did:
            raise ValueError("Only the bounty creator can distribute rewards")
        if bounty["status"] in ("rewarded", "closed"):
            raise ValueError(
                f"Bounty rewards already distributed (status={bounty['status']})"
            )

        # Find winner: highest-scored evaluated submission
        winner_row = await conn.fetchrow(
            """
            SELECT submission_id, submitter_did, submitter_id, score
            FROM   bounty_submissions
            WHERE  bounty_id = $1
              AND  status    = 'evaluated'
            ORDER  BY score DESC NULLS LAST
            LIMIT  1
            """,
            bounty_id,
        )
        if winner_row is None:
            raise ValueError(
                f"No evaluated submissions found for bounty {bounty_id}"
            )

        winner_submission_id = winner_row["submission_id"]
        recipient_did        = winner_row["submitter_did"]
        recipient_id         = winner_row.get("submitter_id")
        reward_amount        = bounty["reward_pool"]

        # Credit winner's wallet (soft-fail on wallet missing)
        if reward_amount > 0 and recipient_id is not None:
            try:
                wallet_row = await conn.fetchrow(
                    """
                    UPDATE wallets
                       SET balance    = balance + $1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE agent_id = $2
                    RETURNING wallet_id
                    """,
                    reward_amount,
                    recipient_id,
                )
                if wallet_row is None:
                    logger.warning(
                        "bounty_service: no wallet for winner %s — skipping credit",
                        recipient_did,
                    )
                else:
                    # Ledger record: NULL (escrow) → winner wallet
                    await conn.execute(
                        """
                        INSERT INTO transactions
                            (from_wallet, to_wallet, amount, type, related_id)
                        VALUES (NULL, $1, $2, 'bounty_reward', $3)
                        """,
                        wallet_row["wallet_id"],
                        reward_amount,
                        bounty_id,
                    )
            except Exception:
                logger.warning(
                    "bounty_service: wallet credit failed for winner %s",
                    recipient_did, exc_info=True,
                )

        # Record reward
        reward_row = await conn.fetchrow(
            """
            INSERT INTO bounty_rewards
                (bounty_id, submission_id, recipient_did, recipient_id, amount)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING reward_id, bounty_id, submission_id,
                      recipient_did, recipient_id, amount, distributed_at
            """,
            bounty_id,
            winner_submission_id,
            recipient_did,
            recipient_id,
            reward_amount,
        )

        # Close bounty and mark winner
        await conn.execute(
            """
            UPDATE capability_bounties
               SET status               = 'rewarded',
                   winner_submission_id = $2,
                   closed_at            = NOW()
             WHERE bounty_id = $1
            """,
            bounty_id,
            winner_submission_id,
        )

        # Mark winner submission as 'won', others as 'closed'
        await conn.execute(
            """
            UPDATE bounty_submissions
               SET status = CASE
                   WHEN submission_id = $2 THEN 'won'
                   ELSE 'closed'
               END
             WHERE bounty_id = $1
            """,
            bounty_id,
            winner_submission_id,
        )

    reward = RewardResponse(
        reward_id=reward_row["reward_id"],
        bounty_id=reward_row["bounty_id"],
        submission_id=reward_row["submission_id"],
        recipient_did=reward_row["recipient_did"],
        recipient_id=reward_row.get("recipient_id"),
        amount=reward_row["amount"],
        distributed_at=reward_row["distributed_at"],
    )

    try:
        await publish_event(
            EventType.BOUNTY_REWARD_DISTRIBUTED,
            {
                "reward_id":     str(reward.reward_id),
                "bounty_id":     str(bounty_id),
                "submission_id": str(winner_submission_id),
                "recipient_did": recipient_did,
                "amount":        reward_amount,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "bounty_service: failed to publish BOUNTY_REWARD_DISTRIBUTED for %s",
            bounty_id, exc_info=True,
        )

    logger.info(
        "bounty_service: reward %d tokens distributed to %s for bounty %s",
        reward_amount, recipient_did, bounty_id,
    )
    return reward


async def list_submissions(bounty_id: UUID) -> list[SubmissionResponse]:
    """
    List all submissions for a bounty, newest first.

    Args:
        bounty_id: UUID of the bounty.

    Returns:
        List of SubmissionResponse.

    Raises:
        ValueError: Bounty not found.
    """
    async with get_db() as conn:
        # Verify bounty exists
        exists = await conn.fetchval(
            "SELECT 1 FROM capability_bounties WHERE bounty_id = $1",
            bounty_id,
        )
        if not exists:
            raise ValueError(f"Bounty not found: {bounty_id}")

        rows = await conn.fetch(
            f"""
            SELECT {_SUBMISSION_COLS}
            FROM   bounty_submissions
            WHERE  bounty_id = $1
            ORDER  BY submitted_at DESC
            """,
            bounty_id,
        )

    return [_row_to_submission(r) for r in rows]
