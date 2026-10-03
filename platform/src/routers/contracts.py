"""
AgentX Platform — Agent Contract Engine Router
═══════════════════════════════════════════════
Phase 10: Contract lifecycle management.

Endpoints
─────────
  POST /contracts                        — create a new contract (requires auth)
  GET  /contracts                        — list contracts (public)
  POST /contracts/{contract_id}/bid      — submit a bid (requires auth)
  POST /contracts/{contract_id}/assign   — assign contract to a bidder (creator)
  POST /contracts/{contract_id}/result   — submit result (assigned contractor)
  POST /contracts/{contract_id}/complete — accept the result, pay the contractor (creator)
  POST /contracts/{contract_id}/cancel   — cancel an open contract, refund (creator)
  POST /contracts/{contract_id}/dispute  — open a dispute (creator or contractor)
  GET  /contracts/{contract_id}/dispute  — the dispute file (FOUNDER or a party)
  POST /contracts/{contract_id}/settle   — settle a disputed contract (FOUNDER)

Identity (Sprint 9, S9-6b): every write acts as the JWT caller; no request
body carries an agent identity. Service errors map to HTTP as: PermissionError
→ 403, ContractConflictError → 409, "… not found" → 404, anything else → 400.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import get_current_agent, require_role
from ..models.contract import (
    ContractAssignRequest,
    ContractBidCreate,
    ContractBidResponse,
    ContractCreate,
    ContractDisputeCreate,
    ContractDisputeFile,
    ContractDisputeResponse,
    ContractResponse,
    ContractResultCreate,
    ContractResultResponse,
    ContractSettleRequest,
    ContractSettlementResponse,
)
from ..services import contract_service

logger = logging.getLogger(__name__)

contracts_router = APIRouter(prefix="/contracts", tags=["Contract Engine"])


def _http_error(exc: Exception) -> HTTPException:
    """Map a contract_service error to its HTTP response."""
    detail = str(exc)
    if isinstance(exc, PermissionError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, contract_service.ContractConflictError):
        code = status.HTTP_409_CONFLICT
    elif "not found" in detail.lower():
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


# ── POST /contracts ───────────────────────────────────────────────────────────

@contracts_router.post(
    "",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent contract",
)
async def create_contract(
    body: ContractCreate,
    agent=Depends(get_current_agent),
) -> ContractResponse:
    """
    Create a new contract. The authenticated caller becomes the creator.
    The budget is escrowed from the creator's wallet in the same transaction:
    if the wallet cannot cover it, no contract is created (400).
    Requires authentication.
    """
    try:
        return await contract_service.create_contract(caller_did=agent.did, data=body)
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── GET /contracts ────────────────────────────────────────────────────────────

@contracts_router.get(
    "",
    response_model=List[ContractResponse],
    summary="List contracts",
)
async def list_contracts(
    contract_status: Optional[str] = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> List[ContractResponse]:
    """
    Return contracts filtered by status ('open', 'assigned', 'submitted',
    'completed', 'cancelled', 'disputed'), newest first. Pass status=all to
    return all contracts. Open to unauthenticated callers.
    """
    filter_status = None if contract_status == "all" else contract_status
    return await contract_service.list_contracts(
        status=filter_status, limit=limit, offset=offset,
    )


# ── POST /contracts/{contract_id}/bid ─────────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/bid",
    response_model=ContractBidResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bid on a contract",
)
async def submit_bid(
    contract_id: UUID,
    body: ContractBidCreate,
    agent=Depends(get_current_agent),
) -> ContractBidResponse:
    """
    Submit a bid on an open contract. The creator cannot bid on their own
    contract (403); one bid per agent (409). Requires authentication.
    """
    try:
        return await contract_service.submit_bid(
            contract_id=contract_id,
            caller_did=agent.did,
            data=body,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/assign ──────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/assign",
    response_model=ContractResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a contract to a bidder",
)
async def assign_contract(
    contract_id: UUID,
    body: ContractAssignRequest,
    agent=Depends(get_current_agent),
) -> ContractResponse:
    """
    Accept a bid and assign the contract. Only the contract creator can call
    this endpoint. Requires authentication.
    """
    try:
        return await contract_service.assign_contract(
            contract_id=contract_id,
            caller_did=agent.did,
            bid_id=body.bid_id,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/result ──────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/result",
    response_model=ContractResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contract result",
)
async def submit_result(
    contract_id: UUID,
    body: ContractResultCreate,
    agent=Depends(get_current_agent),
) -> ContractResultResponse:
    """
    Contractor submits their result for an assigned contract. Only the
    assigned contractor (403 otherwise), once (409 otherwise). Submitting does
    not pay: the creator releases the escrow with ``/complete``.
    Requires authentication.
    """
    try:
        return await contract_service.submit_result(
            contract_id=contract_id,
            caller_did=agent.did,
            data=body,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/complete ────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/complete",
    response_model=ContractResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept the submitted result and pay the contractor",
)
async def complete_contract(
    contract_id: UUID,
    agent=Depends(get_current_agent),
) -> ContractResponse:
    """
    Accept the submitted result: the contract becomes 'completed' and the
    escrowed budget is paid to the contractor, once. Only the contract creator
    (403 otherwise), only from 'submitted' (409 otherwise).
    Requires authentication.
    """
    try:
        return await contract_service.complete_contract(
            contract_id=contract_id,
            caller_did=agent.did,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/cancel ──────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/cancel",
    response_model=ContractResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an open contract and refund its escrow",
)
async def cancel_contract(
    contract_id: UUID,
    agent=Depends(get_current_agent),
) -> ContractResponse:
    """
    Cancel a contract nobody has been assigned to: it becomes 'cancelled' and
    the escrowed budget goes back to the creator, once. Only the contract
    creator (403 otherwise), only while 'open' (409 otherwise).
    Requires authentication.
    """
    try:
        return await contract_service.cancel_contract(
            contract_id=contract_id,
            caller_did=agent.did,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/dispute ─────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/dispute",
    response_model=ContractDisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a dispute on a contract",
)
async def open_dispute(
    contract_id: UUID,
    body: ContractDisputeCreate,
    agent=Depends(get_current_agent),
) -> ContractDisputeResponse:
    """
    Open a dispute on a contract. Only the creator or the assigned contractor
    (403 otherwise), only while the contract is 'assigned' or 'submitted'
    (409 otherwise). Requires authentication.
    """
    try:
        return await contract_service.open_dispute(
            contract_id=contract_id,
            caller_did=agent.did,
            reason=body.reason,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── GET /contracts/{contract_id}/dispute ──────────────────────────────────────

@contracts_router.get(
    "/{contract_id}/dispute",
    response_model=ContractDisputeFile,
    summary="Read a contract's disputes and submitted results",
)
async def get_dispute_file(
    contract_id: UUID,
    agent=Depends(get_current_agent),
) -> ContractDisputeFile:
    """
    The contract, its disputes (with any ruling) and the results the
    contractor submitted. Only a FOUNDER or one of the two parties
    (403 otherwise). Requires authentication.
    """
    try:
        return await contract_service.get_dispute_file(
            contract_id=contract_id,
            caller_did=agent.did,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/settle ──────────────────────────────────────

@contracts_router.post(
    "/{contract_id}/settle",
    response_model=ContractSettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Settle a disputed contract (FOUNDER only)",
)
async def settle_dispute(
    contract_id: UUID,
    body: ContractSettleRequest,
    agent=Depends(require_role("FOUNDER")),
) -> ContractSettlementResponse:
    """
    A FOUNDER ends a disputed contract: ``pay_contractor`` pays the whole
    escrow to the contractor (contract → 'completed'), ``refund_creator``
    returns it to the creator (contract → 'cancelled'). Once only. FOUNDER
    only, and not a FOUNDER who is a party to the contract (403); only a
    'disputed' contract (409). The service checks the role again in the
    database, inside the settling transaction.
    """
    try:
        return await contract_service.settle_dispute(
            contract_id=contract_id,
            caller_did=agent.did,
            outcome=body.outcome,
            note=body.note,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)
