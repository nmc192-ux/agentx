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
  open_dispute(contract_id, caller_did, reason)   → ContractDisputeResponse

Design notes
────────────
• Creator's DID is resolved to agent_id inside each write transaction so
  the router stays free of DB lookups (same pattern as governance_service).
• Budget escrow is performed inline within the create_contract transaction
  using the same debit-wallet → update-contract → ledger-entry pattern from
  token_service (soft-fail: escrow failure is logged but the contract is
  still created).
• Escrow release is similarly inline within complete_contract.
• One bid per (contract_id, bidder_id) is enforced by DB UNIQUE constraint.
• Contract lifecycle: open → assigned → submitted → completed | disputed.
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
    Raises ValueError on insufficient funds or missing wallet.
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
            f"Insufficient funds or wallet not found for agent: {creator_id}"
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


async def _release_contract_escrow(
    conn,
    contract_id: UUID,
    contractor_id: UUID,
    amount: int,
) -> None:
    """
    Credit contractor's wallet and zero out the contract's escrowed_budget.
    Raises ValueError if contractor wallet not found.
    """
    wallet_row = await conn.fetchrow(
        """
        UPDATE wallets
           SET balance    = balance + $1,
               updated_at = CURRENT_TIMESTAMP
         WHERE agent_id = $2
        RETURNING wallet_id
        """,
        amount,
        contractor_id,
    )
    if wallet_row is None:
        raise ValueError(
            f"Contractor wallet not found for agent: {contractor_id}"
        )

    await conn.execute(
        "UPDATE contracts SET escrowed_budget = 0 WHERE contract_id = $1",
        contract_id,
    )

    await _record_transaction(
        conn,
        from_wallet=None,
        to_wallet=wallet_row["wallet_id"],
        amount=amount,
        tx_type="contract_release",
        related_id=contract_id,
    )


# ── Service functions ──────────────────────────────────────────────────────────

_CONTRACT_COLS = """
    contract_id, creator_did, creator_id, contractor_did, contractor_id,
    title, description, contract_type, status, budget, escrowed_budget,
    deadline, payload, created_at
"""


async def create_contract(caller_did: str, data: ContractCreate) -> ContractResponse:
    """
    Create a new contract and escrow the budget from the creator's wallet.

    Args:
        caller_did: DID of the contract creator.
        data:       Validated ContractCreate payload.

    Returns:
        ContractResponse for the newly created contract.
    """
    async with transaction() as conn:
        # Resolve creator DID → agent_id
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        creator_id = agent_row["agent_id"] if agent_row else None

        # Insert contract
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

        # Escrow budget (soft-fail)
        if creator_id is not None and data.budget > 0:
            try:
                await _escrow_contract_budget(conn, creator_id, contract_id, data.budget)
                # Re-fetch to pick up updated escrowed_budget
                row = await conn.fetchrow(
                    f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1",
                    contract_id,
                )
            except Exception:
                logger.warning(
                    "contract_service: escrow skipped for contract %s",
                    contract_id, exc_info=True,
                )

    contract = _row_to_contract(row)

    try:
        await publish_event(
            EventType.CONTRACT_CREATED,
            {
                "contract_id": str(contract.contract_id),
                "creator_did": caller_did,
                "title": data.title,
                "budget": data.budget,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_CREATED", exc_info=True
        )

    logger.info(
        "contract_service: created contract %s ('%s') by %s (budget=%d)",
        contract.contract_id, data.title, caller_did, data.budget,
    )
    return contract


async def list_contracts(status: str | None = "open") -> list[ContractResponse]:
    """
    Return contracts filtered by status, newest first.

    Args:
        status: 'open', 'assigned', 'submitted', 'completed', 'disputed', or
                None for all contracts.

    Returns:
        List of ContractResponse objects.
    """
    async with get_db() as conn:
        if status is None:
            rows = await conn.fetch(
                f"SELECT {_CONTRACT_COLS} FROM contracts ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                f"SELECT {_CONTRACT_COLS} FROM contracts WHERE status = $1 ORDER BY created_at DESC",
                status,
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
        caller_did:  DID of the bidder.
        data:        Validated ContractBidCreate payload.

    Returns:
        ContractBidResponse for the recorded bid.

    Raises:
        ValueError: Contract not found, not open, or bidder not found.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            "SELECT contract_id, status FROM contracts WHERE contract_id = $1",
            contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if contract["status"] != "open":
            raise ValueError(
                f"Contract is not open for bidding (status={contract['status']})"
            )

        bidder_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            caller_did,
        )
        if bidder_row is None:
            raise ValueError(f"Bidder agent not found: {caller_did}")

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

    try:
        await publish_event(
            EventType.CONTRACT_BID_SUBMITTED,
            {
                "bid_id": str(bid.bid_id),
                "contract_id": str(contract_id),
                "bidder_did": caller_did,
                "bid_amount": data.bid_amount,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_BID_SUBMITTED", exc_info=True
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
        caller_did:  DID of the creator (must match contract.creator_did).
        bid_id:      UUID of the accepted bid.

    Returns:
        Updated ContractResponse with status='assigned'.

    Raises:
        ValueError: Contract not found, caller not creator, not open, or bid not found.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            "SELECT contract_id, creator_did, status FROM contracts WHERE contract_id = $1",
            contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if contract["creator_did"] != caller_did:
            raise ValueError("Only the contract creator can assign it")
        if contract["status"] != "open":
            raise ValueError(
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
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
            bid["bidder_did"],
            bid["bidder_id"],
        )

    result = _row_to_contract(updated)

    try:
        await publish_event(
            EventType.CONTRACT_ASSIGNED,
            {
                "contract_id": str(contract_id),
                "contractor_did": bid["bidder_did"],
                "bid_id": str(bid_id),
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_ASSIGNED", exc_info=True
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

    Args:
        contract_id: UUID of the assigned contract.
        caller_did:  DID of the contractor (must match contract.contractor_did).
        data:        Validated ContractResultCreate payload.

    Returns:
        ContractResultResponse for the submitted result.

    Raises:
        ValueError: Contract not found, not assigned, or caller not contractor.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            """
            SELECT contract_id, status, contractor_did, contractor_id
            FROM   contracts
            WHERE  contract_id = $1
            """,
            contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if contract["status"] != "assigned":
            raise ValueError(
                f"Contract is not in assigned state (status={contract['status']})"
            )
        if contract["contractor_did"] != caller_did:
            raise ValueError("Only the assigned contractor can submit a result")

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
            "UPDATE contracts SET status = 'submitted' WHERE contract_id = $1",
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

    try:
        await publish_event(
            EventType.CONTRACT_RESULT_SUBMITTED,
            {
                "result_id": str(result.result_id),
                "contract_id": str(contract_id),
                "contractor_did": caller_did,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_RESULT_SUBMITTED", exc_info=True
        )

    logger.info(
        "contract_service: result submitted for contract %s by %s",
        contract_id, caller_did,
    )
    return result


async def complete_contract(contract_id: UUID, caller_did: str) -> ContractResponse:
    """
    Creator accepts the submitted result and completes the contract.

    Releases the escrowed budget to the contractor's wallet (soft-fail).

    Args:
        contract_id: UUID of the contract to complete.
        caller_did:  DID of the creator.

    Returns:
        Updated ContractResponse with status='completed'.

    Raises:
        ValueError: Contract not found, caller not creator, or not in submitted state.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            f"SELECT {_CONTRACT_COLS} FROM contracts WHERE contract_id = $1",
            contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")
        if contract["creator_did"] != caller_did:
            raise ValueError("Only the contract creator can complete it")
        if contract["status"] != "submitted":
            raise ValueError(
                f"Contract is not in submitted state (status={contract['status']})"
            )

        updated = await conn.fetchrow(
            f"""
            UPDATE contracts
               SET status = 'completed'
             WHERE contract_id = $1
            RETURNING {_CONTRACT_COLS}
            """,
            contract_id,
        )

        # Release escrowed budget to contractor (soft-fail)
        escrowed = contract["escrowed_budget"]
        contractor_id = contract.get("contractor_id")
        if escrowed > 0 and contractor_id:
            try:
                await _release_contract_escrow(conn, contract_id, contractor_id, escrowed)
            except Exception:
                logger.warning(
                    "contract_service: escrow release failed for contract %s",
                    contract_id, exc_info=True,
                )

    result = _row_to_contract(updated)

    try:
        await publish_event(
            EventType.CONTRACT_COMPLETED,
            {
                "contract_id": str(contract_id),
                "creator_did": caller_did,
                "contractor_did": contract.get("contractor_did"),
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_COMPLETED", exc_info=True
        )

    logger.info("contract_service: contract %s completed by %s", contract_id, caller_did)
    return result


async def open_dispute(
    contract_id: UUID,
    caller_did: str,
    reason: str,
) -> ContractDisputeResponse:
    """
    Open a dispute on a contract.

    Any party (creator or contractor) may open a dispute. The contract
    status is updated to 'disputed'.

    Args:
        contract_id: UUID of the disputed contract.
        caller_did:  DID of the dispute initiator.
        reason:      Human-readable reason for the dispute.

    Returns:
        ContractDisputeResponse for the created dispute.

    Raises:
        ValueError: Contract not found.
    """
    async with transaction() as conn:
        contract = await conn.fetchrow(
            "SELECT contract_id, creator_id FROM contracts WHERE contract_id = $1",
            contract_id,
        )
        if contract is None:
            raise ValueError(f"Contract not found: {contract_id}")

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
            "UPDATE contracts SET status = 'disputed' WHERE contract_id = $1",
            contract_id,
        )

    dispute = _row_to_dispute(dispute_row)

    try:
        await publish_event(
            EventType.CONTRACT_DISPUTED,
            {
                "dispute_id": str(dispute.dispute_id),
                "contract_id": str(contract_id),
                "initiator_did": caller_did,
                "reason": reason,
            },
            source_agent_did=caller_did,
        )
    except Exception:
        logger.warning(
            "contract_service: failed to publish CONTRACT_DISPUTED", exc_info=True
        )

    logger.info(
        "contract_service: dispute %s opened on contract %s by %s",
        dispute.dispute_id, contract_id, caller_did,
    )
    return dispute
