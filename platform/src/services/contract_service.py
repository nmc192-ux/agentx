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
  settle_dispute(contract_id, caller_did, outcome, note)
                                                  → ContractSettlementResponse
  reclaim_contract(contract_id, caller_did)       → ContractResponse
  release_overdue_contract(contract_id)           → int   (scheduled job only)
  get_dispute_file(contract_id, caller_did)       → ContractDisputeFile

Design notes
────────────
• Contract lifecycle:
      open → assigned → submitted → completed
      open → cancelled                      (creator; escrow refunded)
      assigned | submitted → disputed       (creator or contractor)
      disputed → completed | cancelled      (a FOUNDER's ruling; escrow paid
                                             to the contractor / refunded)
      assigned → cancelled                  (creator reclaims: the deadline
                                             passed with nothing delivered)
      submitted → completed                 (automatic: the creator left the
                                             delivery unanswered for
                                             AUTO_RELEASE_DAYS)
• Money rules (Sprint 9, S9-6b). The budget is escrowed from the creator's
  wallet in the SAME transaction that creates the contract: no funds, no
  contract (it used to be soft-fail, which let a contract advertise a budget
  nobody had paid in). The escrow leaves in exactly five ways, each once:
  to the contractor when the creator completes a submitted contract, back
  to the creator when the creator cancels a contract nobody was assigned to,
  for a disputed contract only — to whichever of the two a FOUNDER rules for
  (``settle_dispute``, Sprint 12, S12-3), and by the two deadline rules below.
• The price is the accepted bid (decision D4b; Sprint 12, S12-5). A bid above
  the budget is refused. When the creator accepts a bid, the part of the
  escrow above the bid goes back to the creator in the assigning transaction
  and the escrow becomes exactly the bid; from then on every way out above
  moves that amount, whole, to one side. The amount is read from the bid row
  under the contract lock; no request names it.
• Deadlines (decision D3c; Sprint 12, S12-4). A contractor who has not
  delivered by the contract's deadline can lose the job: the creator takes
  the escrow back with ``reclaim_contract``. A creator who leaves a delivery
  unanswered for AUTO_RELEASE_DAYS loses the say: ``release_overdue_contract``
  (scheduled job only, no route) pays the contractor. Both compare the
  DATABASE clock with a time the database holds, under the contract row lock;
  no caller supplies a time. A contract with no deadline cannot be reclaimed,
  and a disputed contract is touched by neither rule — it waits for a FOUNDER.
  So that a deadline cannot be used as a trap, a contract cannot be created
  with a deadline already past, and a contract past its deadline takes no new
  bid and cannot be assigned.
• Every state change locks the contract row (``SELECT … FOR UPDATE``) before
  it reads the status, so concurrent calls are serialised: the second caller
  sees the first one's committed status and is refused. Status change and
  payout commit together or not at all.
• A disputed contract keeps its escrow until a FOUNDER settles it (decision
  D3b). The FOUNDER role is read from the database inside the settling
  transaction, not taken from the caller; a FOUNDER who is a party to the
  contract cannot rule on it; the whole escrow goes to the contractor or to
  the creator, never anywhere else and never split.
• One bid per (contract_id, bidder_id); the creator cannot bid on their own
  contract.
• Errors: PermissionError → 403, ContractConflictError → 409,
  BidOverBudgetError → 422, other
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
    ContractDisputeFile,
    ContractDisputeResponse,
    ContractResponse,
    ContractResultCreate,
    ContractResultResponse,
    ContractSettlementResponse,
)
from .auto_release import AUTO_RELEASE_DAYS
from .token_service import _record_transaction

logger = logging.getLogger(__name__)


class ContractConflictError(ValueError):
    """The contract is not in a state that allows the action (→ HTTP 409)."""


class BidOverBudgetError(ValueError):
    """The bid asks for more than the contract's budget (→ HTTP 422)."""


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
        resolution=row.get("resolution"),
        resolved_by_did=row.get("resolved_by_did"),
        resolved_at=row.get("resolved_at"),
        resolution_note=row.get("resolution_note"),
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


async def _refund_escrow_above_bid(
    conn,
    contract_id: UUID,
    creator_id: UUID,
    bid_amount: int,
) -> int:
    """
    Cut a contract's escrow down to the accepted bid and return the rest to
    the creator, inside the caller's transaction. Returns the amount refunded
    (0 when the bid equals the escrow).

    The caller must hold the contract row lock. The escrow is read here, under
    that lock, and the UPDATE is conditional on the value read, so the refund
    and the new escrow always add up to what was held. A bid that is not
    positive or is above the escrow is refused: nothing is ever taken from
    the creator's wallet to top the escrow up.
    """
    escrowed = await conn.fetchval(
        "SELECT escrowed_budget FROM contracts WHERE contract_id = $1 FOR UPDATE",
        contract_id,
    )
    if bid_amount <= 0 or escrowed is None or bid_amount > escrowed:
        raise ContractConflictError(
            "The bid is above the contract's budget and cannot be accepted"
        )
    remainder = escrowed - bid_amount
    if remainder == 0:
        return 0

    cut = await conn.fetchval(
        """
        UPDATE contracts
           SET escrowed_budget = $2
         WHERE contract_id = $1
           AND escrowed_budget = $3
        RETURNING contract_id
        """,
        contract_id,
        bid_amount,
        escrowed,
    )
    if cut is None:
        raise ContractConflictError("Contract escrow changed; try again")

    wallet_row = await conn.fetchrow(
        """
        INSERT INTO wallets (agent_id, balance)
        VALUES ($2, $1)
        ON CONFLICT (agent_id) DO UPDATE
            SET balance    = wallets.balance + EXCLUDED.balance,
                updated_at = CURRENT_TIMESTAMP
        RETURNING wallet_id
        """,
        remainder,
        creator_id,
    )

    # Ledger entry: NULL (escrow) → creator wallet
    await _record_transaction(
        conn,
        from_wallet=None,
        to_wallet=wallet_row["wallet_id"],
        amount=remainder,
        tx_type="contract_bid_refund",
        related_id=contract_id,
    )
    return remainder


async def _lock_contract(conn, contract_id: UUID):
    """Fetch the contract row and hold its row lock until the transaction ends.

    ``deadline_passed`` is the database's own answer (its clock against the
    stored deadline); it is FALSE for a contract with no deadline."""
    row = await conn.fetchrow(
        f"SELECT {_CONTRACT_COLS}, {_DEADLINE_PASSED} AS deadline_passed "
        "FROM contracts WHERE contract_id = $1 FOR UPDATE",
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

# The database clock against the stored deadline; never a caller's time.
_DEADLINE_PASSED = "COALESCE(deadline < CURRENT_TIMESTAMP, FALSE)"

_DISPUTABLE_STATUSES = ("assigned", "submitted")

_DISPUTE_COLS = """
    dispute_id, contract_id, initiator_did, reason, status, created_at,
    resolution, resolved_by_did, resolved_at, resolution_note
"""

# A FOUNDER's ruling → (who is paid, the contract's final status, ledger type).
_SETTLEMENTS = {
    "pay_contractor": ("contractor", "completed", "contract_dispute_release"),
    "refund_creator": ("creator", "cancelled", "contract_dispute_refund"),
}


async def _is_active_founder(conn, did: str, *, hold: bool = False) -> bool:
    """True only if *did* is an ACTIVE agent whose role, in the database right
    now, is FOUNDER. Anything else — unknown, suspended, any other role — is
    False. ``hold=True`` share-locks the agent row, so the role cannot be
    changed under the caller's transaction before it commits."""
    row = await conn.fetchrow(
        "SELECT governance_role::text AS role, status::text AS status "
        "FROM agents WHERE agent_did = $1" + (" FOR SHARE" if hold else ""),
        did,
    )
    return row is not None and row["role"] == "FOUNDER" and row["status"] == "ACTIVE"


async def _publish(event_type: EventType, payload: dict, caller_did: str) -> None:
    """Fire-and-forget event publish: a failure is logged, never raised."""
    try:
        await publish_event(event_type, payload, source_agent_did=caller_did)
    except Exception:
        logger.warning(
            "contract_service: failed to publish %s", event_type.value, exc_info=True
        )


async def create_contract_in_transaction(
    conn,
    caller_did: str,
    data: ContractCreate,
) -> ContractResponse:
    """
    Insert a contract and escrow its budget on *conn*, inside the caller's
    transaction. Raises ValueError (creator not found, a deadline that is not
    in the future, or insufficient funds / no wallet), which must roll that
    transaction back.

    The caller announces the contract with ``announce_contract_created`` once
    its transaction has committed.
    """
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
        RETURNING {_CONTRACT_COLS}, {_DEADLINE_PASSED} AS deadline_passed
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
    if row.get("deadline_passed"):
        # A deadline already past would let the creator reclaim the moment a
        # contractor is assigned. Raising rolls the INSERT back.
        raise ValueError("The contract deadline must be in the future")

    # Escrow the budget. Raises on insufficient funds → the whole
    # transaction (the INSERT above included) rolls back.
    await _escrow_contract_budget(conn, creator_id, contract_id, data.budget)
    row = await conn.fetchrow(
        f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1",
        contract_id,
    )
    return _row_to_contract(row)


async def announce_contract_created(contract: ContractResponse) -> None:
    """Publish CONTRACT_CREATED and log it. Call after the create has committed."""
    await _publish(
        EventType.CONTRACT_CREATED,
        {
            "contract_id": str(contract.contract_id),
            "creator_did": contract.creator_did,
            "title": contract.title,
            "budget": contract.budget,
        },
        contract.creator_did,
    )

    logger.info(
        "contract_service: created contract %s ('%s') by %s (budget=%d)",
        contract.contract_id, contract.title, contract.creator_did, contract.budget,
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
        ValueError: creator agent not found, a deadline that is not in the
                    future, or insufficient funds / no wallet.
    """
    async with transaction() as conn:
        contract = await create_contract_in_transaction(conn, caller_did, data)

    await announce_contract_created(contract)
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
        ContractConflictError: contract not open or past its deadline, or
                               the caller already bid.
        BidOverBudgetError:    the bid is above the contract's budget (the
                               accepted bid is what the contractor is paid).
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] == caller_did:
            raise PermissionError("The contract creator cannot bid on their own contract")
        if contract["status"] != "open":
            raise ContractConflictError(
                f"Contract is not open for bidding (status={contract['status']})"
            )
        if contract.get("deadline_passed"):
            raise ContractConflictError("Contract deadline has passed; it takes no new bids")
        if data.bid_amount > min(contract["budget"], contract["escrowed_budget"]):
            raise BidOverBudgetError(
                f"Bid of {data.bid_amount} is above the contract's budget of "
                f"{contract['budget']} tokens"
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

    The accepted bid becomes the price (decision D4b; Sprint 12, S12-5): in
    this same transaction, with the contract row locked, the escrow above the
    bid is returned to the creator and the escrow left is exactly the bid.
    The amount is the one stored on the bid row; the request names only the
    bid. A bid above the escrow cannot be accepted.

    Args:
        contract_id: UUID of the contract to assign.
        caller_did:  DID of the caller (must be the contract's creator).
        bid_id:      UUID of the accepted bid.

    Returns:
        Updated ContractResponse with status='assigned' and
        ``escrowed_budget`` equal to the accepted bid.

    Raises:
        ValueError:            contract or bid not found.
        PermissionError:       caller is not the creator, or the bid is the
                               creator's own.
        ContractConflictError: contract is not open (e.g. already assigned),
                               its deadline has passed, or the bid is above
                               the escrow.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] != caller_did:
            raise PermissionError("Only the contract creator can assign it")
        if contract["status"] != "open":
            raise ContractConflictError(
                f"Contract cannot be assigned (status={contract['status']})"
            )
        if contract.get("deadline_passed"):
            # Assigning now would let the creator reclaim at once.
            raise ContractConflictError(
                "Contract deadline has passed; it cannot be assigned (cancel it instead)"
            )

        bid = await conn.fetchrow(
            """
            SELECT bid_id, bidder_did, bidder_id, bid_amount
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

        creator_id = contract["creator_id"]
        if creator_id is None:
            creator_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                caller_did,
            )
            if creator_id is None:
                raise ValueError(f"Creator agent not found: {caller_did}")

        # The accepted bid is the price: return the escrow above it.
        refunded = await _refund_escrow_above_bid(
            conn, contract_id, creator_id, bid["bid_amount"]
        )

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
        "contract_service: contract %s assigned to %s for %d (refunded %d to the creator)",
        contract_id, bid["bidder_did"], bid["bid_amount"], refunded,
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


async def reclaim_contract(contract_id: UUID, caller_did: str) -> ContractResponse:
    """
    Creator takes the escrow back from a contractor who did not deliver by the
    deadline (decision D3c; Sprint 12, S12-4).

    Marks the contract 'cancelled' and refunds the whole escrowed budget to
    the creator in ONE transaction, with the contract row locked, so it
    happens once however often or however concurrently it is called, and a
    delivery racing the reclaim either lands first (the reclaim is refused)
    or finds the contract cancelled.

    Refused (nothing changes) unless every one of these holds:
      • the caller is the contract's creator;
      • the contract is 'assigned' — a contractor was hired and nothing was
        delivered. Once a result is in ('submitted'), late or not, the creator
        completes or disputes; a 'disputed' contract waits for a FOUNDER;
      • the contract has a deadline and, by the database clock, it has passed.

    Args:
        contract_id: UUID of the contract to reclaim.
        caller_did:  DID of the caller (must be the contract's creator).

    Returns:
        Updated ContractResponse with status='cancelled', escrowed_budget=0.

    Raises:
        ValueError:            contract not found.
        PermissionError:       caller is not the creator.
        ContractConflictError: contract is not 'assigned', has no deadline,
                               or its deadline has not passed.
    """
    async with transaction() as conn:
        contract = await _lock_contract(conn, contract_id)
        if contract["creator_did"] != caller_did:
            raise PermissionError("Only the contract creator can reclaim it")
        if contract["status"] != "assigned":
            raise ContractConflictError(
                "Only an assigned contract with nothing delivered can be reclaimed "
                f"(status={contract['status']})"
            )
        if contract["deadline"] is None:
            raise ContractConflictError(
                "Contract has no deadline and cannot be reclaimed; open a dispute instead"
            )
        if contract["deadline_passed"] is not True:
            raise ContractConflictError("Contract deadline has not passed yet")

        creator_id = contract["creator_id"]
        if creator_id is None:
            creator_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1",
                caller_did,
            )
            if creator_id is None:
                raise ValueError(f"Creator agent not found: {caller_did}")

        refunded = await _settle_contract_escrow(
            conn, contract_id, creator_id, "contract_deadline_refund"
        )

        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status = 'cancelled'
             WHERE contract_id = $1
               AND status      = 'assigned'
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
        )

    logger.info(
        "contract_service: contract %s reclaimed by %s after its deadline "
        "(refunded %d; contractor %s did not deliver)",
        contract_id, caller_did, refunded, contract["contractor_did"],
    )
    return _row_to_contract(updated)


async def release_overdue_contract(contract_id: UUID) -> int:
    """
    Pay the contractor for a delivery the creator has left unanswered for
    AUTO_RELEASE_DAYS, so a silent creator cannot withhold the escrow
    (decision D3c; Sprint 12, S12-4). Returns the amount released.

    For the scheduled job only — no route calls this and it takes no caller
    and no time: with the contract row locked, the DATABASE clock is compared
    with the submitted_at the database stamped on the delivered result. A
    contract that is not 'submitted' (so never a disputed one), not yet due,
    with no result on record, or whose contractor no longer exists is refused
    and nothing moves. The payee is the contractor on the locked row.

    Raises:
        ValueError:            contract not found.
        ContractConflictError: nothing delivered and unanswered, the period
                               has not passed, or there is no contractor to pay.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            """
            SELECT c.contract_id, c.status, c.contractor_did, c.contractor_id,
                   COALESCE(
                       (SELECT MAX(r.submitted_at) FROM contract_results r
                         WHERE r.contract_id = c.contract_id)
                           <= CURRENT_TIMESTAMP - make_interval(days => $2),
                       FALSE
                   ) AS due
            FROM contracts c WHERE c.contract_id = $1
            FOR UPDATE OF c
            """,
            contract_id,
            AUTO_RELEASE_DAYS,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if contract["status"] != "submitted":
            raise ContractConflictError(
                f"Contract has no delivery awaiting the creator (status={contract['status']})"
            )
        if contract["due"] is not True:
            raise ContractConflictError(
                f"The creator still has time to answer ({AUTO_RELEASE_DAYS} days from delivery)"
            )
        if contract["contractor_id"] is None:
            # The contractor's agent row was deleted. Do not guess a payee.
            raise ContractConflictError(
                "Contract has no contractor to pay; it cannot be released"
            )

        released = await _settle_contract_escrow(
            conn, contract_id, contract["contractor_id"], "contract_auto_release"
        )

        await conn.execute(
            """
            UPDATE contracts SET status = 'completed'
             WHERE contract_id = $1 AND status = 'submitted'
            """,
            contract_id,
        )

    logger.info(
        "contract_service: contract %s released automatically after %d days (%d to %s)",
        contract_id, AUTO_RELEASE_DAYS, released, contract["contractor_did"],
    )
    return released


async def open_dispute(
    contract_id: UUID,
    caller_did: str,
    reason: str,
) -> ContractDisputeResponse:
    """
    Open a dispute on a contract.

    Only the two parties (creator or assigned contractor) may dispute, and
    only while work is in flight ('assigned' or 'submitted'). The contract
    moves to 'disputed' and its escrow stays where it is until a FOUNDER
    settles it (``settle_dispute``), so this must not be open to outsiders.

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


async def settle_dispute(
    contract_id: UUID,
    caller_did: str,
    outcome: str,
    note: str,
) -> ContractSettlementResponse:
    """
    A FOUNDER settles a disputed contract (decision D3b; Sprint 12, S12-3).

    ``outcome='pay_contractor'`` pays the whole escrow to the contractor and
    the contract ends 'completed'; ``outcome='refund_creator'`` returns it to
    the creator and the contract ends 'cancelled'. Escrow, contract status and
    the ruling on the dispute row change in ONE transaction with the contract
    row locked, so however often or however concurrently this is called the
    escrow moves once; a failure anywhere rolls all of it back.

    Refused (nothing changes) unless every one of these holds:
      • the caller is, in the database at this moment, an ACTIVE FOUNDER;
      • the caller is neither the creator nor the contractor;
      • the contract is 'disputed' and has an open dispute on record;
      • the party to be paid still exists.

    Args:
        contract_id: UUID of the disputed contract.
        caller_did:  DID of the caller (the authenticated agent).
        outcome:     'pay_contractor' or 'refund_creator'.
        note:        The FOUNDER's reason; kept on the dispute row.

    Raises:
        ValueError:            contract not found, unknown outcome, empty note.
        PermissionError:       caller is not an active FOUNDER, or is a party.
        ContractConflictError: contract is not disputed (e.g. already
                               settled), has no open dispute, or the party to
                               be paid no longer exists.
    """
    if outcome not in _SETTLEMENTS:
        raise ValueError(f"Unknown settlement outcome: {outcome!r}")
    if not note or not note.strip():
        raise ValueError("A settlement needs a note giving the reason")
    payee_side, final_status, tx_type = _SETTLEMENTS[outcome]

    async with transaction() as conn:
        if not await _is_active_founder(conn, caller_did, hold=True):
            raise PermissionError("Only a FOUNDER can settle a disputed contract")

        contract = await _lock_contract(conn, contract_id)
        if caller_did in (contract["creator_did"], contract["contractor_did"]):
            raise PermissionError(
                "A party to the contract cannot settle its dispute"
            )
        if contract["status"] != "disputed":
            raise ContractConflictError(
                f"Only a disputed contract can be settled (status={contract['status']})"
            )

        # The payee is one of the two parties named on the locked row — never
        # anything the caller supplies.
        payee_did = contract[f"{payee_side}_did"]
        payee_id = contract[f"{payee_side}_id"]
        if payee_did is not None and payee_id is None:
            payee_id = await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1", payee_did
            )
        if payee_did is None or payee_id is None:
            raise ContractConflictError(
                f"The contract's {payee_side} no longer exists and cannot be paid"
            )

        dispute_row = await conn.fetchrow(
            f"""
            UPDATE contract_disputes
               SET status          = 'resolved',
                   resolution      = $2,
                   resolved_by_did = $3,
                   resolved_at     = CURRENT_TIMESTAMP,
                   resolution_note = $4
             WHERE contract_id = $1
               AND status      = 'open'
            RETURNING {_DISPUTE_COLS}
            """,
            contract_id,
            outcome,
            caller_did,
            note.strip(),
        )
        if dispute_row is None:
            raise ContractConflictError(
                "Contract has no open dispute on record; it cannot be settled"
            )

        amount = await _settle_contract_escrow(conn, contract_id, payee_id, tx_type)

        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status = $2
             WHERE contract_id = $1
               AND status      = 'disputed'
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
            final_status,
        )

    logger.info(
        "contract_service: dispute %s on contract %s settled by %s: %s "
        "(%d to %s)",
        dispute_row["dispute_id"], contract_id, caller_did, outcome, amount, payee_did,
    )
    return ContractSettlementResponse(
        contract=_row_to_contract(updated),
        dispute=_row_to_dispute(dispute_row),
        outcome=outcome,
        amount=amount,
        paid_to_did=payee_did,
    )


async def get_dispute_file(contract_id: UUID, caller_did: str) -> ContractDisputeFile:
    """
    The contract, its disputes and its submitted results — what a FOUNDER
    reads before ruling. Only an active FOUNDER or one of the two parties.

    Raises:
        ValueError:      contract not found.
        PermissionError: caller is neither a FOUNDER nor a party.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1",
            contract_id,
        )
        if row is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if caller_did not in (row["creator_did"], row["contractor_did"]) and not (
            await _is_active_founder(conn, caller_did)
        ):
            raise PermissionError(
                "Only a FOUNDER or a party to the contract can read its disputes"
            )
        disputes = await conn.fetch(
            f"SELECT {_DISPUTE_COLS} FROM contract_disputes "
            "WHERE contract_id = $1 ORDER BY created_at, dispute_id",
            contract_id,
        )
        results = await conn.fetch(
            "SELECT result_id, contract_id, contractor_did, result_payload, submitted_at "
            "FROM contract_results WHERE contract_id = $1 ORDER BY submitted_at, result_id",
            contract_id,
        )
    return ContractDisputeFile(
        contract=_row_to_contract(row),
        disputes=[_row_to_dispute(d) for d in disputes],
        results=[_row_to_result(r) for r in results],
    )
