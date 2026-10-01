"""
AgentX Platform — Agent Contract Engine Service
════════════════════════════════════════════════
Phase 10: Structured bilateral contracts with escrow, bidding, and dispute
resolution between agents.

Public API
──────────
  create_contract(caller_did, data)               → ContractResponse
  list_contracts(status)                          → list[ContractResponse]
  submit_bid(contract_id, caller_did, data)       → ContractBidResponse
  assign_contract(contract_id, caller_did, bid_id)→ ContractResponse
  submit_result(contract_id, caller_did, data)    → ContractResultResponse
  complete_contract(contract_id, caller_did)      → ContractResponse
  cancel_contract(contract_id, caller_did)        → ContractResponse
  open_dispute(contract_id, caller_did, reason)   → ContractDisputeResponse

Design notes
────────────
• Contract lifecycle:
      open → assigned → submitted → completed
      open → cancelled                      (creator; escrow refunded)
      assigned | submitted → disputed       (creator or contractor)
• Money rules (Sprint 9, S9-6b). The budget is escrowed from the creator's
  wallet in the SAME transaction that creates the contract: no funds, no
  contract (it used to be soft-fail, which let a contract advertise a budget
  nobody had paid in). The escrow leaves in exactly two ways, each once:
  to the contractor when the creator completes a submitted contract, or back
  to the creator when the creator cancels a contract nobody was assigned to.
• Every state change locks the contract row (``SELECT … FOR UPDATE``) before
  it reads the status, so concurrent calls are serialised: the second caller
  sees the first one's committed status and is refused. Status change and
  payout commit together or not at all.
• A disputed contract keeps its escrow: nothing resolves a dispute yet
  (arbitration is an open design question — HUMAN_ACTIONS D3).
• One bid per (contract_id, bidder_id); the creator cannot bid on their own
  contract.
• Errors: PermissionError → 403, ContractConflictError → 409, other
  ValueError → 404 ("not found") or 400. See routers/contracts.py.
• Events are fire-and-forget; failures are logged but never bubble up.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from ..database import get_db, transaction
from ..events.publisher import publish_event
from ..events.types import EventType
from ..models.contract import (
    ContractBidCreate,
    ContractBidResponse,
    ContractCreate,
    ContractDisputeResponse,
    ContractResponse,
    ContractResultCreate,
    ContractResultResponse,
)
from .token_service import _record_transaction

logger = logging.getLogger(__name__)


class ContractConflictError(ValueError):
    """The contract is not in a state that allows the action (→ HTTP 409)."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _decode_json(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value) if value else None
    return dict(value)


def _row_to_contract(row) -> ContractResponse:
    return ContractResponse(
        contract_id=row["contract_id"],
        creator_did=row["creator_did"],
        creator_id=row.get("creator_id"),
        contractor_did=row.get("contractor_did"),
        contractor_id=row.get("contractor_id"),
        title=row["title"],
        description=row["description"],
        contract_type=row["contract_type"],
        status=row["status"],
        budget=row["budget"],
        escrowed_budget=row["escrowed_budget"],
        deadline=row.get("deadline"),
        payload=_decode_json(row.get("payload")),
        created_at=row["created_at"],
    )


def _row_to_bid(row) -> ContractBidResponse:
    return ContractBidResponse(
        bid_id=row["bid_id"],
        contract_id=row["contract_id"],
        bidder_did=row["bidder_did"],
        bid_amount=row["bid_amount"],
        proposal=row.get("proposal"),
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_result(row) -> ContractResultResponse:
    return ContractResultResponse(
        result_id=row["result_id"],
        contract_id=row["contract_id"],
        contractor_did=row["contractor_did"],
        result_payload=_decode_json(row.get("result_payload")),
        submitted_at=row["submitted_at"],
    )


def _row_to_dispute(row) -> ContractDisputeResponse:
    return ContractDisputeResponse(
        dispute_id=row["dispute_id"],
        contract_id=row["contract_id"],
        initiator_did=row["initiator_did"],
        reason=row["reason"],
        status=row["status"],
        created_at=row["created_at"],
    )


# ── Inline escrow helpers (no separate transaction — use existing conn) ────────

async def _escrow_contract_budget(
    conn,
    creator_id: UUID,
    contract_id: UUID,
    amount: int,
) -> None:
    """
    Debit creator's wallet and mark budget as escrowed on the contract.
    Uses an atomic UPDATE-WHERE-balance-sufficient pattern.
    Raises ValueError on insufficient funds or a missing wallet.
    """
    debit_row = await conn.fetchrow(
        """
        UPDATE wallets
           SET balance    = balance - $1,
               updated_at = CURRENT_TIMESTAMP
         WHERE agent_id = $2
           AND balance  >= $1
        RETURNING wallet_id
        """,
        amount,
        creator_id,
    )
    if debit_row is None:
        raise ValueError(
            f"Insufficient funds: the creator's wallet cannot cover a budget of "
            f"{amount} tokens"
        )

    await conn.execute(
        """
        UPDATE contracts
           SET escrowed_budget = escrowed_budget + $1
         WHERE contract_id = $2
        """,
        amount,
        contract_id,
    )

    await _record_transaction(
        conn,
        from_wallet=debit_row["wallet_id"],
        to_wallet=None,
        amount=amount,
        tx_type="contract_escrow",
        related_id=contract_id,
    )


async def _settle_contract_escrow(
    conn,
    contract_id: UUID,
    payee_agent_id: UUID,
    tx_type: str,
) -> int:
    """
    Pay a contract's whole escrow to *payee_agent_id* inside the caller's
    transaction. Returns the amount paid (0 if nothing was escrowed).

    The contract row is locked (``FOR UPDATE``) before ``escrowed_budget`` is
    read, so two concurrent settlements cannot both see a non-zero escrow: the
    second waits for the first to commit, then reads 0 and pays nothing.

    The payee's wallet is created if missing — the tokens come out of escrow,
    so this mints nothing — otherwise an agent with no wallet could never be
    paid and the escrow would be stuck for good. Any failure propagates and
    rolls the caller's transaction back (no soft-fail).
    """
    escrowed = await conn.fetchval(
        "SELECT escrowed_budget FROM contracts WHERE contract_id = $1 FOR UPDATE",
        contract_id,
    )
    if not escrowed:
        return 0

    wallet_row = await conn.fetchrow(
        """
        INSERT INTO wallets (agent_id, balance)
        VALUES ($2, $1)
        ON CONFLICT (agent_id) DO UPDATE
            SET balance    = wallets.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
        RETURNING wallet_id
        """,
        escrowed,
        payee_agent_id,
    )

    await conn.execute(
        "UPDATE contracts SET escrowed_budget = 0 WHERE contract_id = $1",
        contract_id,
    )

    # Ledger entry: NULL (escrow) → payee wallet
    await _record_transaction(
        conn,
        from_wallet=None,
        to_wallet=wallet_row["wallet_id"],
        amount=escrowed,
        tx_type=tx_type,
        related_id=contract_id,
    )
    return escrowed


async def _lock_contract(conn, contract_id: UUID):
    """Fetch the contract row and hold its row lock until the transaction ends."""
    row = await conn.fetchrow(
        f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1 FOR UPDATE",
        contract_id,
    )
    if row is None:
        raise ValueError(f"Contract not found: {contract_id}")
    return row


# ── Service functions ──────────────────────────────────────────────────────────

_CONTRACT_COLS = """
    contract_id, creator_did, creator_id, contractor_did, contractor_id,
    title, description, contract_type, status, budget, escrowed_budget,
    deadline, payload, created_at
"""

_DISPUTABLE_STATUSES = ("assigned", "submitted")


async def _publish(event_type: EventType, payload: dict, caller_did: str) -> None:
    """Fire-and-forget event publish: a failure is logged, never raised."""
    try:
        await publish_event(event_type, payload, source_agent_did=caller_did)
    except Exception:
        logger.warning(
            "contract_service: failed to publish %s", event_type.value, exc_info=True
        )


async def create_contract(caller_did: str, data: ContractCreate) -> ContractResponse:
    """
    Create a new contract and escrow its budget from the creator's wallet.

    Contract and escrow are one transaction: if the creator's wallet cannot
    cover the budget, nothing is created.

    Args:
        caller_did: DID of the contract creator (the authenticated caller).
        data:       Validated ContractCreate payload.

    Returns:
        ContractResponse for the newly created contract
        (``escrowed_budget == budget``).

    Raises:
        ValueError: creator agent not found, or insufficient funds / no wallet.
    """
    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if agent_row is None:
            raise ValueError(f"Creator agent not found: {caller_did}")
        creator_id = agent_row["agent_id"]

        row = await conn.fetchrow(
            f"""
            INSERT INTO contracts
                (creator_did, creator_id, title, description, contract_type,
                 budget, deadline, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            RETURNING {_CONTRACT_COLS}
            """,
            caller_did,
            creator_id,
            data.title,
            data.description,
            data.contract_type,
            data.budget,
            data.deadline,
            json.dumps(data.payload) if data.payload else None,
        )
        contract_id = row["contract_id"]

        # Escrow the budget. Raises on insufficient funds → the whole
        # transaction (the INSERT above included) rolls back.
        await _escrow_contract_budget(conn, creator_id, contract_id, data.budget)
        row = await conn.fetchrow(
            f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1",
            contract_id,
        )

    contract = _row_to_contract(row)

    await _publish(
        EventType.CONTRACT_CREATED,
        {
            "contract_id": str(contract.contract_id),
            "creator_did": caller_did,
            "title": data.title,
            "budget": data.budget,
        },
        caller_did,
    )

    logger.info(
        "contract_service: created contract %s ('%s') by %s (budget=%d)",
        contract.contract_id, data.title, caller_did, data.budget,
    )
    return contract


async def list_contracts(
    status: str | None = "open",
    limit: int = 50,
    offset: int = 0,
) -> list[ContractResponse]:
    """
    Return contracts filtered by status, newest first.

    Args:
        status: 'open', 'assigned', 'submitted', 'completed', 'cancelled',
                'disputed', or None for all contracts.
        limit:  Page size.
        offset: Rows to skip.

    Returns:
        List of ContractResponse objects.
    """
    async with get_db() as conn:
        if status is None:
            rows = await conn.fetch(
                f"""
                SELECT {_CONTRACT_COLS} FROM contracts
                ORDER BY created_at DESC LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT {_CONTRACT_COLS} FROM contracts WHERE status = $1
                ORDER BY created_at DESC LIMIT $2 OFFSET $3
                """,
                status,
                limit,
                offset,
            )
    return [_row_to_contract(r) for r in rows]


async def submit_bid(
    contract_id: UUID,
    caller_did: str,
    data: ContractBidCreate,
) -> ContractBidResponse:
    """
    Submit a bid on an open contract.

    Args:
        contract_id: UUID of the target contract.
        caller_did:  DID of the bidder (the authenticated caller).
        data:        Validated ContractBidCreate payload.

    Returns:
        ContractBidResponse for the recorded bid.

    Raises:
        ValueError:            contract or bidder not found.
        PermissionError:       the bidder is the contract's creator (no
                               self-dealing: a creator could otherwise win
                               their own contract and pay themselves).
        ContractConflictError: contract not open, or the caller already bid.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] == caller_did:
            raise PermissionError("The contract creator cannot bid on their own contract")
        if contract["status"] != "open":
            raise ContractConflictError(
                f"Contract is not open for bidding (status={contract['status']})"
            )

        bidder_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if bidder_row is None:
            raise ValueError(f"Bidder agent not found: {caller_did}")

        # The contract row is locked, so this check cannot race with another
        # bid from the same agent (the DB UNIQUE constraint is the backstop).
        already = await conn.fetchval(
            "SELECT 1 FROM contract_bids WHERE contract_id = $1 AND bidder_id = $2",
            contract_id,
            bidder_row["agent_id"],
        )
        if already:
            raise ContractConflictError("You have already bid on this contract")

        row = await conn.fetchrow(
            """
            INSERT INTO contract_bids
                (contract_id, bidder_did, bidder_id, bid_amount, proposal)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING bid_id, contract_id, bidder_did, bid_amount, proposal, status, created_at
            """,
            contract_id,
            caller_did,
            bidder_row["agent_id"],
            data.bid_amount,
            data.proposal,
        )

    bid = _row_to_bid(row)

    await _publish(
        EventType.CONTRACT_BID_SUBMITTED,
        {
            "bid_id": str(bid.bid_id),
            "contract_id": str(contract_id),
            "bidder_did": caller_did,
            "bid_amount": data.bid_amount,
        },
        caller_did,
    )

    logger.info(
        "contract_service: bid %s submitted on contract %s by %s",
        bid.bid_id, contract_id, caller_did,
    )
    return bid


async def assign_contract(
    contract_id: UUID,
    caller_did: str,
    bid_id: UUID,
) -> ContractResponse:
    """
    Creator accepts a bid and assigns the contract to the winning bidder.

    Args:
        contract_id: UUID of the contract to assign.
        caller_did:  DID of the caller (must be the contract's creator).
        bid_id:      UUID of the accepted bid.

    Returns:
        Updated ContractResponse with status='assigned'.

    Raises:
        ValueError:            contract or bid not found.
        PermissionError:       caller is not the creator, or the bid is the
                               creator's own.
        ContractConflictError: contract is not open (e.g. already assigned).
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] != caller_did:
            raise PermissionError("Only the contract creator can assign it")
        if contract["status"] != "open":
            raise ContractConflictError(
                f"Contract cannot be assigned (status={contract['status']})"
            )

        bid = await conn.fetchrow(
            """
            SELECT bid_id, bidder_did, bidder_id
            FROM   contract_bids
            WHERE  bid_id = $1 AND contract_id = $2
            """,
            bid_id,
            contract_id,
        )
        if bid is None:
            raise ValueError(f"Bid not found: {bid_id}")
        if bid["bidder_did"] == contract["creator_did"]:
            raise PermissionError("A contract cannot be assigned to its own creator")

        # Insert assignment record
        await conn.execute(
            """
            INSERT INTO contract_assignments
                (contract_id, contractor_did, contractor_id)
            VALUES ($1, $2, $3)
            """,
            contract_id,
            bid["bidder_did"],
            bid["bidder_id"],
        )

        # Mark bid as accepted
        await conn.execute(
            "UPDATE contract_bids SET status = 'accepted' WHERE bid_id = $1",
            bid_id,
        )

        # Update contract: status + contractor fields
        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status         = 'assigned',
                   contractor_did = $2,
                   contractor_id  = $3
             WHERE contract_id = $1
               AND status      = 'open'
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
            bid["bidder_did"],
            bid["bidder_id"],
        )

    result = _row_to_contract(updated)

    await _publish(
        EventType.CONTRACT_ASSIGNED,
        {
            "contract_id": str(contract_id),
            "contractor_did": bid["bidder_did"],
            "bid_id": str(bid_id),
        },
        caller_did,
    )

    logger.info(
        "contract_service: contract %s assigned to %s",
        contract_id, bid["bidder_did"],
    )
    return result


async def submit_result(
    contract_id: UUID,
    caller_did: str,
    data: ContractResultCreate,
) -> ContractResultResponse:
    """
    Contractor submits their result for an assigned contract.

    Submitting does not pay: the escrow is released when the creator
    completes the contract (``complete_contract``).

    Args:
        contract_id: UUID of the assigned contract.
        caller_did:  DID of the caller (must be the assigned contractor).
        data:        Validated ContractResultCreate payload.

    Returns:
        ContractResultResponse for the submitted result.

    Raises:
        ValueError:            contract not found.
        PermissionError:       caller is not the assigned contractor.
        ContractConflictError: contract is not awaiting a result (e.g. a
                               result was already submitted).
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["contractor_did"] is None or contract["contractor_did"] != caller_did:
            raise PermissionError("Only the assigned contractor can submit a result")
        if contract["status"] != "assigned":
            raise ContractConflictError(
                f"Contract is not in assigned state (status={contract['status']})"
            )

        result_row = await conn.fetchrow(
            """
            INSERT INTO contract_results
                (contract_id, contractor_did, contractor_id, result_payload)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING result_id, contract_id, contractor_did, result_payload, submitted_at
            """,
            contract_id,
            caller_did,
            contract["contractor_id"],
            json.dumps(data.result_payload) if data.result_payload else None,
        )

        await conn.execute(
            """
            UPDATE contracts SET status = 'submitted'
             WHERE contract_id = $1 AND status = 'assigned'
            """,
            contract_id,
        )

        # Mark assignment as completed
        await conn.execute(
            """
            UPDATE contract_assignments
               SET completed_at = CURRENT_TIMESTAMP
             WHERE contract_id = $1
            """,
            contract_id,
        )

    result = _row_to_result(result_row)

    await _publish(
        EventType.CONTRACT_RESULT_SUBMITTED,
        {
            "result_id": str(result.result_id),
            "contract_id": str(contract_id),
            "contractor_did": caller_did,
        },
        caller_did,
    )

    logger.info(
        "contract_service: result submitted for contract %s by %s",
        contract_id, caller_did,
    )
    return result


async def complete_contract(contract_id: UUID, caller_did: str) -> ContractResponse:
    """
    Creator accepts the submitted result and completes the contract.

    Marks the contract 'completed' and pays the whole escrowed budget to the
    contractor in ONE transaction, with the contract row locked: however many
    times (or however concurrently) this is called, the contractor is paid
    once. If the payout fails, the completion rolls back and can be retried.

    Args:
        contract_id: UUID of the contract to complete.
        caller_did:  DID of the caller (must be the contract's creator).

    Returns:
        Updated ContractResponse with status='completed', escrowed_budget=0.

    Raises:
        ValueError:            contract not found.
        PermissionError:       caller is not the creator.
        ContractConflictError: contract is not in 'submitted' state (already
                               completed, disputed, …), or its contractor no
                               longer exists.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] != caller_did:
            raise PermissionError("Only the contract creator can complete it")
        if contract["status"] != "submitted":
            raise ContractConflictError(
                f"Contract is not in submitted state (status={contract['status']})"
            )
        contractor_id = contract["contractor_id"]
        if contractor_id is None:
            # The contractor's agent row was deleted. Do not guess a payee.
            raise ContractConflictError(
                "Contract has no contractor to pay; it cannot be completed"
            )

        paid = await _settle_contract_escrow(
            conn, contract_id, contractor_id, "contract_release"
        )

        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status = 'completed'
             WHERE contract_id = $1
               AND status      = 'submitted'
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
        )

    result = _row_to_contract(updated)

    await _publish(
        EventType.CONTRACT_COMPLETED,
        {
            "contract_id": str(contract_id),
            "creator_did": caller_did,
            "contractor_did": contract["contractor_did"],
        },
        caller_did,
    )

    logger.info(
        "contract_service: contract %s completed by %s (paid %d to %s)",
        contract_id, caller_did, paid, contract["contractor_did"],
    )
    return result


async def cancel_contract(contract_id: UUID, caller_did: str) -> ContractResponse:
    """
    Creator cancels a contract that nobody has been assigned to.

    Marks the contract 'cancelled' and refunds the whole escrowed budget to
    the creator in ONE transaction, with the contract row locked. Only an
    'open' contract can be cancelled: once a contractor is assigned, the
    escrow is theirs to earn and the creator cannot pull it back.

    Args:
        contract_id: UUID of the contract to cancel.
        caller_did:  DID of the caller (must be the contract's creator).

    Returns:
        Updated ContractResponse with status='cancelled', escrowed_budget=0.

    Raises:
        ValueError:            contract not found.
        PermissionError:       caller is not the creator.
        ContractConflictError: contract is not open.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] != caller_did:
            raise PermissionError("Only the contract creator can cancel it")
        if contract["status"] != "open":
            raise ContractConflictError(
                f"Only an open contract can be cancelled (status={contract['status']})"
            )

        creator_id = contract["creator_id"]
        if creator_id is None:
            creator_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                caller_did,
            )
            if creator_id is None:
                raise ValueError(f"Creator agent not found: {caller_did}")

        refunded = await _settle_contract_escrow(
            conn, contract_id, creator_id, "contract_refund"
        )

        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status = 'cancelled'
             WHERE contract_id = $1
               AND status      = 'open'
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
        )

    logger.info(
        "contract_service: contract %s cancelled by %s (refunded %d)",
        contract_id, caller_did, refunded,
    )
    return _row_to_contract(updated)


async def open_dispute(
    contract_id: UUID,
    caller_did: str,
    reason: str,
) -> ContractDisputeResponse:
    """
    Open a dispute on a contract.

    Only the two parties (creator or assigned contractor) may dispute, and
    only while work is in flight ('assigned' or 'submitted'). The contract
    moves to 'disputed' and its escrow stays where it is: nothing resolves a
    dispute yet (HUMAN_ACTIONS D3), so this must not be open to outsiders.

    Args:
        contract_id: UUID of the disputed contract.
        caller_did:  DID of the dispute initiator (the authenticated caller).
        reason:      Human-readable reason for the dispute.

    Returns:
        ContractDisputeResponse for the created dispute.

    Raises:
        ValueError:            contract not found.
        PermissionError:       caller is neither creator nor contractor.
        ContractConflictError: contract is not 'assigned' or 'submitted'.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if caller_did not in (contract["creator_did"], contract["contractor_did"]):
            raise PermissionError(
                "Only the contract's creator or contractor can open a dispute"
            )
        if contract["status"] not in _DISPUTABLE_STATUSES:
            raise ContractConflictError(
                f"Contract cannot be disputed (status={contract['status']})"
            )

        # Resolve initiator DID → agent_id (optional — NULL safe)
        initiator_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        initiator_id = initiator_row["agent_id"] if initiator_row else None

        dispute_row = await conn.fetchrow(
            """
            INSERT INTO contract_disputes
                (contract_id, initiator_did, initiator_id, reason)
            VALUES ($1, $2, $3, $4)
            RETURNING dispute_id, contract_id, initiator_did, reason, status, created_at
            """,
            contract_id,
            caller_did,
            initiator_id,
            reason,
        )

        await conn.execute(
            """
            UPDATE contracts SET status = 'disputed'
             WHERE contract_id = $1 AND status IN ('assigned', 'submitted')
            """,
            contract_id,
        )

    dispute = _row_to_dispute(dispute_row)

    await _publish(
        EventType.CONTRACT_DISPUTED,
        {
            "dispute_id": str(dispute.dispute_id),
            "contract_id": str(contract_id),
            "initiator_did": caller_did,
            "reason": reason,
        },
        caller_did,
    )

    logger.info(
        "contract_service: dispute %s opened on contract %s by %s",
        dispute.dispute_id, contract_id, caller_did,
    )
    return dispute
