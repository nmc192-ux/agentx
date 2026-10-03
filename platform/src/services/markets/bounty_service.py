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
  list_bounties(status, capability, limit, offset)    → list[BountyResponse]
  get_bounty(bounty_id)                               → BountyResponse
  submit_solution(bounty_id, caller_did, data)        → SubmissionResponse
  evaluate_submission(bounty_id, submission_id,
                      caller_did, score)              → SubmissionResponse
  distribute_rewards(bounty_id, caller_did)           → RewardResponse
  cancel_bounty(bounty_id, caller_did)                → BountyResponse
  release_overdue_bounty(bounty_id)                   → (outcome, amount)  (scheduled job only)
  list_submissions(bounty_id)                         → list[SubmissionResponse]

Design notes
────────────
• Bounty lifecycle:
      open → evaluating → rewarded          (creator distributes; winner paid)
      open → cancelled                      (creator; no submissions; refunded)
      open | evaluating → rewarded          (automatic: AUTO_RELEASE_DAYS after
                                             the deadline, a submission was scored)
      open | evaluating → cancelled         (automatic: AUTO_RELEASE_DAYS after
                                             the deadline, nothing was scored;
                                             refunded)
• Money rules (Sprint 9, S9-6c). The reward pool is escrowed from the
  creator's wallet in the SAME transaction that creates the bounty: no funds,
  no bounty. While the bounty is 'open' or 'evaluating' the pool is held in
  escrow. It leaves in exactly three ways, each once: to the winning submitter
  when the creator distributes, back to the creator when the creator cancels
  a bounty nobody has submitted to, or by the deadline rule below.
• Deadlines (decision D5b; Sprint 12, S12-6). Every new bounty has a deadline
  (DEFAULT_BOUNTY_DAYS from creation when the creator names none; one already
  past is refused). After it the bounty takes no more submissions; the
  creator can still score and pay. If the pool is still held AUTO_RELEASE_DAYS
  after the deadline, ``release_overdue_bounty`` (scheduled job only, no
  route) pays it to the top-scored submission — the same pick as
  ``distribute_rewards`` — or, if nothing payable was scored, back to the
  creator. Both rules compare the DATABASE clock with the stored deadline
  under the bounty row lock; no caller supplies a time. A bounty stored
  with no deadline (created before this rule) is never released
  automatically.
• Every state change locks the bounty row (``SELECT … FOR UPDATE``) before it
  reads the status, so concurrent calls are serialised: the second caller sees
  the first one's committed status and is refused. Status change and payout
  commit together or not at all (no soft-fail). ``bounty_rewards`` also has
  UNIQUE(bounty_id) (migration 041) as a database-level backstop.
• The creator cannot submit to their own bounty, and a creator's own
  submission can never be picked as the winner.
• A bounty that has submissions cannot be cancelled by the creator; a
  creator who never picks a winner is overtaken by the deadline rule.
• Errors: PermissionError → 403, BountyConflictError → 409, other ValueError
  → 404 ("not found") or 400. See routers/markets.py.
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
    RewardResponse,
    SubmissionCreate,
    SubmissionResponse,
)
from ..auto_release import AUTO_RELEASE_DAYS
from ..token_service import _record_transaction

logger = logging.getLogger(__name__)


class BountyConflictError(ValueError):
    """The bounty is not in a state that allows the action (→ HTTP 409)."""


_BOUNTY_COLS = """
    bounty_id, creator_did, creator_id, title, description,
    capability_required, reward_pool, status, deadline,
    winner_submission_id, created_at, closed_at
"""

_SUBMISSION_COLS = """
    submission_id, bounty_id, submitter_did, submitter_id,
    solution_data, summary, score, status, submitted_at, evaluated_at
"""

# The reward pool is held in escrow while the bounty is in one of these states.
_ESCROW_HELD_STATUSES = ("open", "evaluating")

# The deadline a bounty gets when its creator names none, counted from creation.
DEFAULT_BOUNTY_DAYS = 30

# The database clock against the stored deadline; never a caller's time.
_DEADLINE_PASSED = "COALESCE(deadline <= CURRENT_TIMESTAMP, FALSE)"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _lock_bounty(conn, bounty_id: UUID):
    """Fetch the bounty row and hold its row lock until the transaction ends.

    ``deadline_passed`` is the database's own answer (its clock against the
    stored deadline); it is FALSE for a bounty with no deadline."""
    row = await conn.fetchrow(
        f"SELECT {_BOUNTY_COLS}, {_DEADLINE_PASSED} AS deadline_passed "
        "FROM capability_bounties WHERE bounty_id = $1 FOR UPDATE",
        bounty_id,
    )
    if row is None:
        raise ValueError(f"Bounty not found: {bounty_id}")
    return row


async def _pick_winner(conn, bounty):
    """The submission the pool goes to: the highest-scored evaluated one,
    earliest first on a tie (then by id, so the pick is always the same).
    Never the creator's own, and never one whose agent row is gone (there is
    nobody to pay). None when there is no such submission. The caller holds
    the bounty's row lock."""
    return await conn.fetchrow(
        """
        SELECT submission_id, submitter_did, submitter_id, score
        FROM   bounty_submissions
        WHERE  bounty_id      = $1
          AND  status         = 'evaluated'
          AND  score          IS NOT NULL
          AND  submitter_id   IS NOT NULL
          AND  submitter_did  <> $2
        ORDER  BY score DESC, submitted_at ASC, submission_id ASC
        LIMIT  1
        """,
        bounty["bounty_id"],
        bounty["creator_did"],
    )


async def _reward_winner(conn, bounty, winner_row, tx_type: str):
    """Close the locked *bounty* as 'rewarded' and pay its whole pool to
    *winner_row*'s submitter, inside the caller's transaction. Returns the
    new bounty_rewards row. The status-guarded UPDATE and UNIQUE(bounty_id)
    on bounty_rewards each make a second payout impossible."""
    bounty_id = bounty["bounty_id"]
    winner_submission_id = winner_row["submission_id"]
    reward_amount = bounty["reward_pool"]

    closed = await conn.fetchval(
        """
        UPDATE capability_bounties
           SET status               = 'rewarded',
               winner_submission_id = $2,
               closed_at            = NOW()
         WHERE bounty_id = $1
           AND status IN ('open', 'evaluating')
        RETURNING bounty_id
        """,
        bounty_id,
        winner_submission_id,
    )
    if closed is None:
        raise BountyConflictError("Bounty rewards already distributed")

    # Record reward (UNIQUE(bounty_id): a second reward row cannot exist)
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
        winner_row["submitter_did"],
        winner_row["submitter_id"],
        reward_amount,
    )

    # Pay the winner out of escrow
    await _pay_out_escrow(
        conn, bounty_id, winner_row["submitter_id"], reward_amount, tx_type
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
    return reward_row


async def _pay_out_escrow(
    conn,
    bounty_id: UUID,
    payee_agent_id: UUID,
    amount: int,
    tx_type: str,
) -> None:
    """
    Credit *amount* escrowed tokens to *payee_agent_id* inside the caller's
    transaction. The caller must hold the bounty's row lock and must move the
    bounty out of the escrow-held statuses in the same transaction.

    The payee's wallet is created if missing — the tokens come out of escrow,
    so this mints nothing — otherwise an agent with no wallet could never be
    paid and the escrow would be stuck for good. Any failure propagates and
    rolls the caller's transaction back (no soft-fail).
    """
    if amount <= 0:
        return

    wallet_row = await conn.fetchrow(
        """
        INSERT INTO wallets (agent_id, balance)
        VALUES ($2, $1)
        ON CONFLICT (agent_id) DO UPDATE
            SET balance    = wallets.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
        RETURNING wallet_id
        """,
        amount,
        payee_agent_id,
    )

    # Ledger entry: NULL (escrow) → payee wallet
    await _record_transaction(
        conn,
        from_wallet=None,
        to_wallet=wallet_row["wallet_id"],
        amount=amount,
        tx_type=tx_type,
        related_id=bounty_id,
    )


async def _publish(event_type: EventType, payload: dict, caller_did: str) -> None:
    """Fire-and-forget event publish: a failure is logged, never raised."""
    try:
        await publish_event(event_type, payload, source_agent_did=caller_did)
    except Exception:
        logger.warning(
            "bounty_service: failed to publish %s", event_type.value, exc_info=True
        )


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

    The caller's wallet is debited by *reward_pool* tokens in the same
    transaction, to escrow the prize.  If the wallet is missing or has
    insufficient funds the operation raises ValueError and no bounty is
    created.

    Args:
        caller_did: DID of the authenticated caller (bounty creator).
        data:       Validated BountyCreate payload.

    The deadline is the one given, or DEFAULT_BOUNTY_DAYS from now (database
    clock) when none is given. One that is not in the future is refused: the
    bounty would be closed to submissions from the start.

    Returns:
        BountyResponse with status='open'.

    Raises:
        ValueError: Caller agent not found, no wallet / insufficient funds,
                    or a deadline that is not in the future.
    """
    async with transaction() as conn:
        # Resolve DID → agent_id
        creator_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if creator_row is None:
            raise ValueError(f"Creator agent not found: {caller_did}")
        creator_id: UUID = creator_row["agent_id"]

        # Escrow reward_pool: debit caller wallet (to_wallet=NULL means escrow)
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
                # Worded to answer 400 like any other unfunded create, not 404.
                raise ValueError(
                    f"Insufficient funds: {caller_did} has no wallet to escrow "
                    f"{data.reward_pool} tokens from"
                )
            raise ValueError(
                f"Insufficient funds: cannot escrow {data.reward_pool} tokens for bounty"
            )

        # Insert bounty
        row = await conn.fetchrow(
            f"""
            INSERT INTO capability_bounties
                (creator_did, creator_id, title, description,
                 capability_required, reward_pool, deadline)
            VALUES ($1, $2, $3, $4, $5, $6,
                    COALESCE($7::timestamptz, CURRENT_TIMESTAMP + make_interval(days => $8)))
            RETURNING {_BOUNTY_COLS}, {_DEADLINE_PASSED} AS deadline_passed
            """,
            caller_did,
            creator_id,
            data.title,
            data.description,
            data.capability_required,
            data.reward_pool,
            data.deadline,
            DEFAULT_BOUNTY_DAYS,
        )
        if row["deadline_passed"] is not False:
            # Raising rolls the escrow debit and the row back.
            raise ValueError("The bounty deadline must be in the future")

        # Ledger record: creator wallet → NULL (escrow)
        await _record_transaction(
            conn,
            from_wallet=wallet_row["wallet_id"],
            to_wallet=None,
            amount=data.reward_pool,
            tx_type="bounty_escrow",
            related_id=row["bounty_id"],
        )

    bounty = _row_to_bounty(row)

    await _publish(
        EventType.BOUNTY_CREATED,
        {
            "bounty_id":           str(bounty.bounty_id),
            "creator_did":         caller_did,
            "title":               bounty.title,
            "capability_required": bounty.capability_required,
            "reward_pool":         bounty.reward_pool,
        },
        caller_did,
    )

    logger.info(
        "bounty_service: bounty %s created by %s (pool=%d)",
        bounty.bounty_id, caller_did, bounty.reward_pool,
    )
    return bounty


async def list_bounties(
    status: str | None = None,
    capability: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BountyResponse]:
    """
    List bounties, optionally filtered by status and/or capability.

    Args:
        status:     e.g. 'open', 'evaluating', 'rewarded', 'cancelled'. None = all.
        capability: capability_required filter. None = all.
        limit:      Page size.
        offset:     Rows to skip.

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
    params.extend([limit, offset])

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_BOUNTY_COLS} FROM capability_bounties {where_clause}
            ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
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

    The bounty row is locked, so a submission cannot slip in while the bounty
    is being cancelled or its reward distributed.

    Args:
        bounty_id:  UUID of the target bounty.
        caller_did: DID of the submitting agent.
        data:       Validated SubmissionCreate payload.

    Returns:
        SubmissionResponse with status='pending'.

    Raises:
        ValueError:          Bounty or submitting agent not found.
        PermissionError:     Caller is the bounty's creator.
        BountyConflictError: Bounty is not in 'open' status, or its deadline
                             has passed (database clock).
    """
    import json as _json

    async with transaction() as conn:
        bounty = await _lock_bounty(conn, bounty_id)
        if bounty["creator_did"] == caller_did:
            raise PermissionError("The bounty creator cannot submit to their own bounty")
        if bounty["status"] != "open":
            raise BountyConflictError(
                f"Bounty is not open for submissions (status={bounty['status']})"
            )
        if bounty["deadline_passed"] is not False:
            raise BountyConflictError(
                "Bounty deadline has passed; it takes no more submissions"
            )

        # Resolve submitter DID → agent_id
        submitter_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if submitter_row is None:
            raise ValueError(f"Submitter agent not found: {caller_did}")
        submitter_id: UUID = submitter_row["agent_id"]

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

    await _publish(
        EventType.BOUNTY_SUBMISSION,
        {
            "submission_id": str(submission.submission_id),
            "bounty_id":     str(bounty_id),
            "submitter_did": caller_did,
        },
        caller_did,
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
        ValueError:          Bounty/submission not found.
        PermissionError:     Caller is not the bounty's creator.
        BountyConflictError: Bounty is already rewarded or cancelled.
    """
    async with transaction() as conn:
        bounty = await _lock_bounty(conn, bounty_id)
        if bounty["creator_did"] != caller_did:
            raise PermissionError("Only the bounty creator can evaluate submissions")
        if bounty["status"] not in _ESCROW_HELD_STATUSES:
            raise BountyConflictError(
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

    await _publish(
        EventType.BOUNTY_EVALUATED,
        {
            "submission_id": str(submission_id),
            "bounty_id":     str(bounty_id),
            "score":         score,
            "evaluator_did": caller_did,
        },
        caller_did,
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
    Close the bounty and pay the reward pool to the top-scoring submission.

    The evaluated submission with the highest score wins (earliest submission
    on a tie).  The bounty is marked 'rewarded' and the escrowed reward_pool
    is credited to the winner's wallet in ONE transaction, with the bounty row
    locked: however many times (or however concurrently) this is called, the
    reward is paid once. If the payout fails, everything rolls back and the
    call can be retried.

    Args:
        bounty_id:  UUID of the bounty to close.
        caller_did: DID of the caller (must be the bounty creator).

    Returns:
        RewardResponse describing the payment.

    Raises:
        ValueError:          Bounty not found.
        PermissionError:     Caller is not the bounty's creator.
        BountyConflictError: Bounty already rewarded or cancelled, or it has
                             no evaluated submission that can be paid.
    """
    async with transaction() as conn:
        bounty = await _lock_bounty(conn, bounty_id)
        if bounty["creator_did"] != caller_did:
            raise PermissionError("Only the bounty creator can distribute rewards")
        if bounty["status"] not in _ESCROW_HELD_STATUSES:
            raise BountyConflictError(
                f"Bounty rewards cannot be distributed (status={bounty['status']})"
            )

        winner_row = await _pick_winner(conn, bounty)
        if winner_row is None:
            raise BountyConflictError(
                f"No evaluated submissions found for bounty {bounty_id}"
            )

        winner_submission_id = winner_row["submission_id"]
        recipient_did        = winner_row["submitter_did"]
        recipient_id         = winner_row["submitter_id"]
        reward_amount        = bounty["reward_pool"]

        reward_row = await _reward_winner(conn, bounty, winner_row, "bounty_reward")

    reward = RewardResponse(
        reward_id=reward_row["reward_id"],
        bounty_id=reward_row["bounty_id"],
        submission_id=reward_row["submission_id"],
        recipient_did=reward_row["recipient_did"],
        recipient_id=reward_row.get("recipient_id"),
        amount=reward_row["amount"],
        distributed_at=reward_row["distributed_at"],
    )

    await _publish(
        EventType.BOUNTY_REWARD_DISTRIBUTED,
        {
            "reward_id":     str(reward.reward_id),
            "bounty_id":     str(bounty_id),
            "submission_id": str(winner_submission_id),
            "recipient_did": recipient_did,
            "recipient_id":  str(recipient_id),
            "amount":        reward_amount,
        },
        caller_did,
    )

    logger.info(
        "bounty_service: reward %d tokens distributed to %s for bounty %s",
        reward_amount, recipient_did, bounty_id,
    )
    return reward


async def cancel_bounty(bounty_id: UUID, caller_did: str) -> BountyResponse:
    """
    Creator cancels a bounty that nobody has submitted to.

    Marks the bounty 'cancelled' and refunds the escrowed reward_pool to the
    creator in ONE transaction, with the bounty row locked. Only an 'open'
    bounty with no submissions can be cancelled: once an agent has done the
    work, the creator cannot pull the prize back.

    Args:
        bounty_id:  UUID of the bounty to cancel.
        caller_did: DID of the caller (must be the bounty creator).

    Returns:
        Updated BountyResponse with status='cancelled'.

    Raises:
        ValueError:          Bounty not found.
        PermissionError:     Caller is not the bounty's creator.
        BountyConflictError: Bounty is not open, or it has submissions.
    """
    async with transaction() as conn:
        bounty = await _lock_bounty(conn, bounty_id)
        if bounty["creator_did"] != caller_did:
            raise PermissionError("Only the bounty creator can cancel it")
        if bounty["status"] != "open":
            raise BountyConflictError(
                f"Only an open bounty can be cancelled (status={bounty['status']})"
            )
        has_submissions = await conn.fetchval(
            "SELECT 1 FROM bounty_submissions WHERE bounty_id = $1 LIMIT 1",
            bounty_id,
        )
        if has_submissions:
            raise BountyConflictError(
                "A bounty that has submissions cannot be cancelled"
            )

        creator_id = bounty["creator_id"]
        if creator_id is None:
            creator_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                caller_did,
            )
            if creator_id is None:
                raise ValueError(f"Creator agent not found: {caller_did}")

        updated = await conn.fetchrow(
            f"""
            UPDATE capability_bounties
               SET status    = 'cancelled',
                   closed_at = NOW()
             WHERE bounty_id = $1
               AND status    = 'open'
            RETURNING {_BOUNTY_COLS}
            """,
            bounty_id,
        )
        if updated is None:
            raise BountyConflictError("Bounty is no longer open")

        await _pay_out_escrow(
            conn, bounty_id, creator_id, bounty["reward_pool"], "bounty_refund"
        )

    logger.info(
        "bounty_service: bounty %s cancelled by %s (refunded %d)",
        bounty_id, caller_did, bounty["reward_pool"],
    )
    return _row_to_bounty(updated)


async def release_overdue_bounty(bounty_id: UUID) -> tuple[str, int]:
    """
    Release the pool of a bounty its creator has left unpaid for
    AUTO_RELEASE_DAYS after the deadline, so a silent creator cannot keep it
    locked for ever (decision D5b; Sprint 12, S12-6).

    The pool goes, whole, to the top-scored submission (the same pick as
    ``distribute_rewards``: highest score, earliest on a tie) and the bounty
    becomes 'rewarded'; if no payable submission was scored it goes back to
    the creator and the bounty becomes 'cancelled'. Returns
    ``("rewarded" | "refunded", amount)``.

    For the scheduled job only — no route calls this and it takes no caller
    and no time: with the bounty row locked, the DATABASE clock is compared
    with the stored deadline. A bounty that no longer holds its pool, has no
    deadline, or is not yet due is refused and nothing moves; so is one with
    nothing scored whose creator no longer exists (no payee is guessed).

    Raises:
        ValueError:          bounty not found.
        BountyConflictError: pool already paid or refunded, no deadline, the
                             period has not passed, or nobody to pay.
    """
    async with transaction() as conn:
        bounty = await conn.fetchrow(
            f"""
            SELECT {_BOUNTY_COLS},
                   COALESCE(
                       deadline <= CURRENT_TIMESTAMP - make_interval(days => $2),
                       FALSE
                   ) AS due
            FROM capability_bounties WHERE bounty_id = $1
            FOR UPDATE
            """,
            bounty_id,
            AUTO_RELEASE_DAYS,
        )
        if bounty is None:
            raise ValueError(f"Bounty not found: {bounty_id}")
        if bounty["status"] not in _ESCROW_HELD_STATUSES:
            raise BountyConflictError(
                f"Bounty holds no reward pool to release (status={bounty['status']})"
            )
        if bounty["deadline"] is None:
            raise BountyConflictError(
                "Bounty has no deadline and is not released automatically"
            )
        if bounty["due"] is not True:
            raise BountyConflictError(
                f"The creator still has time to pay out "
                f"({AUTO_RELEASE_DAYS} days from the deadline)"
            )

        amount = bounty["reward_pool"]
        winner_row = await _pick_winner(conn, bounty)
        reward_row = None

        if winner_row is not None:
            outcome = "rewarded"
            payee_did = winner_row["submitter_did"]
            reward_row = await _reward_winner(
                conn, bounty, winner_row, "bounty_auto_release"
            )
        else:
            outcome = "refunded"
            payee_did = bounty["creator_did"]
            creator_id = bounty["creator_id"]
            if creator_id is None:
                creator_id = await conn.fetchval(
                    "SELECT agent_id FROM agents WHERE agent_did = $1",
                    bounty["creator_did"],
                )
                if creator_id is None:
                    # The creator's agent row was deleted. Do not guess a payee.
                    raise BountyConflictError(
                        "Bounty has no scored submission and no creator to refund; "
                        "it cannot be released"
                    )

            closed = await conn.fetchval(
                """
                UPDATE capability_bounties
                   SET status    = 'cancelled',
                       closed_at = NOW()
                 WHERE bounty_id = $1
                   AND status IN ('open', 'evaluating')
                RETURNING bounty_id
                """,
                bounty_id,
            )
            if closed is None:
                raise BountyConflictError("Bounty no longer holds its reward pool")

            await _pay_out_escrow(
                conn, bounty_id, creator_id, amount, "bounty_deadline_refund"
            )
            await conn.execute(
                "UPDATE bounty_submissions SET status = 'closed' WHERE bounty_id = $1",
                bounty_id,
            )

    if reward_row is not None:
        await _publish(
            EventType.BOUNTY_REWARD_DISTRIBUTED,
            {
                "reward_id":     str(reward_row["reward_id"]),
                "bounty_id":     str(bounty_id),
                "submission_id": str(reward_row["submission_id"]),
                "recipient_did": reward_row["recipient_did"],
                "recipient_id":  str(reward_row["recipient_id"]),
                "amount":        amount,
                "automatic":     True,
            },
            bounty["creator_did"],
        )

    logger.info(
        "bounty_service: bounty %s released automatically %d days after its "
        "deadline (%s: %d to %s)",
        bounty_id, AUTO_RELEASE_DAYS, outcome, amount, payee_did,
    )
    return outcome, amount


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
