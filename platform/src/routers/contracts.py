"""
AgentX Platform — Agent Contract Engine Router
═══════════════════════════════════════════════
Phase 10: Contract lifecycle management.

Endpoints
─────────
  POST /contracts                        — create a new contract (requires auth)
  GET  /contracts                        — list contracts (public)
  POST /contracts/{contract_id}/bid      — submit a bid (requires auth)
  POST /contracts/{contract_id}/assign   — assign contract to a bidder (requires auth)
  POST /contracts/{contract_id}/result   — submit result (requires auth)
  POST /contracts/{contract_id}/dispute  — open a dispute (requires auth)
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import get_current_agent
from ..models.contract import (
    ContractAssignRequest,
    ContractBidCreate,
    ContractBidResponse,
    ContractCreate,
    ContractDisputeCreate,
    ContractDisputeResponse,
    ContractResponse,
    ContractResultCreate,
    ContractResultResponse,
)
from ..services import contract_service

logger = logging.getLogger(__name__)

contracts_router = APIRouter(prefix="/contracts", tags=["Contract Engine"])


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
    Budget is immediately escrowed from the creator's wallet (soft-fail).
    Requires authentication.
    """
    try:
        return await contract_service.create_contract(caller_did=agent.did, data=body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── GET /contracts ────────────────────────────────────────────────────────────

@contracts_router.get(
    "",
    response_model=List[ContractResponse],
    summary="List contracts",
)
async def list_contracts(
    contract_status: Optional[str] = Query(default="open", alias="status"),
) -> List[ContractResponse]:
    """
    Return contracts filtered by status ('open', 'assigned', 'submitted',
    'completed', 'disputed'). Pass status=all to return all contracts.
    Open to unauthenticated callers.
    """
    filter_status = None if contract_status == "all" else contract_status
    return await contract_service.list_contracts(status=filter_status)


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
    Submit a bid on an open contract. Requires authentication.
    """
    try:
        return await contract_service.submit_bid(
            contract_id=contract_id,
            caller_did=agent.did,
            data=body,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


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
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


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
    Contractor submits their result for an assigned contract.
    Requires authentication.
    """
    try:
        return await contract_service.submit_result(
            contract_id=contract_id,
            caller_did=agent.did,
            data=body,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


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
    Open a dispute on a contract. Either party (creator or contractor) may
    open a dispute. Requires authentication.
    """
    try:
        return await contract_service.open_dispute(
            contract_id=contract_id,
            caller_did=agent.did,
            reason=body.reason,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)
