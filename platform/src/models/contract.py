"""Pydantic models for the Agent Contract Engine (Phase 10)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────


class ContractCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    contract_type: str = Field(default="general")
    budget: int = Field(..., gt=0, le=2**63 - 1)   # BIGINT column
    deadline: Optional[datetime] = None
    payload: Optional[dict] = None


class ContractBidCreate(BaseModel):
    bid_amount: int = Field(..., gt=0, le=2**63 - 1)   # BIGINT column
    proposal: Optional[str] = None


class ContractAssignRequest(BaseModel):
    bid_id: UUID


class ContractResultCreate(BaseModel):
    result_payload: Optional[dict] = None


class ContractDisputeCreate(BaseModel):
    reason: str = Field(..., min_length=1)


class ContractSettleRequest(BaseModel):
    """A FOUNDER's ruling on a disputed contract. The whole escrow goes one
    way; the body names no payee and no amount (anything else → 422)."""
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["pay_contractor", "refund_creator"]
    note: str = Field(..., min_length=1, max_length=2000)


# ──────────────────────────────────────────────────────────────────────────────
# Response models
# ──────────────────────────────────────────────────────────────────────────────


class ContractResponse(BaseModel):
    contract_id: UUID
    creator_did: str
    creator_id: Optional[UUID] = None
    contractor_did: Optional[str] = None
    contractor_id: Optional[UUID] = None
    title: str
    description: str
    contract_type: str
    status: str
    budget: int
    escrowed_budget: int
    deadline: Optional[datetime] = None
    payload: Optional[dict] = None
    created_at: datetime


class ContractBidResponse(BaseModel):
    bid_id: UUID
    contract_id: UUID
    bidder_did: str
    bid_amount: int
    proposal: Optional[str] = None
    status: str
    created_at: datetime


class ContractResultResponse(BaseModel):
    result_id: UUID
    contract_id: UUID
    contractor_did: str
    result_payload: Optional[dict] = None
    submitted_at: datetime


class ContractDisputeResponse(BaseModel):
    dispute_id: UUID
    contract_id: UUID
    initiator_did: str
    reason: str
    status: str
    created_at: datetime
    resolution: Optional[str] = None
    resolved_by_did: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None


class ContractSettlementResponse(BaseModel):
    contract: ContractResponse
    dispute: ContractDisputeResponse
    outcome: str
    amount: int
    paid_to_did: str


class ContractDisputeFile(BaseModel):
    """What a FOUNDER reads before ruling: the contract, its disputes and
    whatever the contractor submitted."""
    contract: ContractResponse
    disputes: List[ContractDisputeResponse]
    results: List[ContractResultResponse]
