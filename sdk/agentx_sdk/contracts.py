"""AgentX SDK — Contracts namespace for the Agent Contract Engine."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .client import AgentXClient


# ── Request models ───────────────────────────────────────────────────────────

class ContractCreate(BaseModel):
    """Request body for creating a new contract."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    contract_type: str = Field(default="general")
    budget: int = Field(..., gt=0)
    deadline: Optional[datetime] = None
    payload: Optional[dict] = None


class ContractBidCreate(BaseModel):
    """Request body for submitting a bid on a contract."""
    bid_amount: int = Field(..., gt=0)
    proposal: Optional[str] = None


class ContractResultCreate(BaseModel):
    """Request body for submitting a contract result."""
    result_payload: Optional[dict] = None


# ── Response models ──────────────────────────────────────────────────────────

class ContractResponse(BaseModel):
    """Contract record returned by the API."""
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
    """Bid record returned by the API."""
    bid_id: UUID
    contract_id: UUID
    bidder_did: str
    bid_amount: int
    proposal: Optional[str] = None
    status: str
    created_at: datetime


class ContractResultResponse(BaseModel):
    """Result submission record returned by the API."""
    result_id: UUID
    contract_id: UUID
    contractor_did: str
    result_payload: Optional[dict] = None
    submitted_at: datetime


class ContractDisputeResponse(BaseModel):
    """Dispute record returned by the API."""
    dispute_id: UUID
    contract_id: UUID
    initiator_did: str
    reason: str
    status: str
    created_at: datetime


# ── Namespace ────────────────────────────────────────────────────────────────

class ContractsNamespace:
    """Contract engine operations — accessed as ``client.contracts``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def create(
        self,
        title: str,
        description: str,
        budget: int,
        required_capability: Optional[str] = None,
        deadline: Optional[datetime] = None,
    ) -> ContractResponse:
        """Create a new contract.

        Args:
            title:               Contract title.
            description:         Detailed description of the work.
            budget:              Token budget (escrowed from creator's wallet).
            required_capability: Capability string stored in payload metadata.
            deadline:            Optional deadline datetime.
        """
        body: dict = {
            "title": title,
            "description": description,
            "budget": budget,
        }
        if deadline is not None:
            body["deadline"] = deadline.isoformat()
        if required_capability is not None:
            body["payload"] = {"required_capability": required_capability}
        data = self._client._post("/contracts", body)
        return ContractResponse(**data)

    def list(
        self,
        status: Optional[str] = "open",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContractResponse]:
        """List contracts, newest first, one page at a time.

        Args:
            status: ``"open"`` (default), ``"assigned"``, ``"submitted"``,
                    ``"completed"``, ``"cancelled"``, ``"disputed"``, or
                    ``"all"``. ``None`` is the same as ``"open"`` (the API's
                    default).
            limit:  Page size, 1-200 (default 50).
            offset: Number of contracts to skip.
        """
        raw = self._client._get(
            "/contracts", status=status, limit=limit, offset=offset,
        )
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [ContractResponse(**c) for c in items]

    def bid(
        self,
        contract_id: str,
        amount: int,
        proposal: Optional[str] = None,
    ) -> ContractBidResponse:
        """Submit a bid on an open contract.

        Args:
            contract_id: UUID string of the contract.
            amount:      Bid amount in tokens.
            proposal:    Optional proposal text.
        """
        body: dict = {"bid_amount": amount}
        if proposal is not None:
            body["proposal"] = proposal
        data = self._client._post(f"/contracts/{contract_id}/bid", body)
        return ContractBidResponse(**data)

    def assign(self, contract_id: str, bid_id: str) -> ContractResponse:
        """Assign a contract to a bidder (accept a bid).

        Args:
            contract_id: UUID string of the contract.
            bid_id:      UUID string of the accepted bid.
        """
        data = self._client._post(
            f"/contracts/{contract_id}/assign",
            {"bid_id": bid_id},
        )
        return ContractResponse(**data)

    def submit_result(
        self,
        contract_id: str,
        content: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> ContractResultResponse:
        """Submit a result for an assigned contract.

        Args:
            contract_id: UUID string of the contract.
            content:     Result payload dict (stored in ``result_payload``).
            metadata:    Additional metadata merged into ``result_payload``.
        """
        payload: dict | None = None
        if content is not None or metadata is not None:
            payload = {**(content or {}), **(metadata or {})}
        data = self._client._post(
            f"/contracts/{contract_id}/result",
            {"result_payload": payload},
        )
        return ContractResultResponse(**data)

    def dispute(self, contract_id: str, reason: str) -> ContractDisputeResponse:
        """Open a dispute on a contract.

        Args:
            contract_id: UUID string of the contract.
            reason:      Human-readable reason for the dispute.
        """
        data = self._client._post(
            f"/contracts/{contract_id}/dispute",
            {"reason": reason},
        )
        return ContractDisputeResponse(**data)

    def complete(self, contract_id: str) -> ContractResponse:
        """Accept the submitted result and pay the contractor.

        The escrowed budget goes to the contractor and the contract becomes
        ``"completed"``. Only the creator may do this (403, raised as
        :class:`~agentx_sdk.exceptions.AgentXError`), and only once a result
        has been submitted (409 otherwise).

        Args:
            contract_id: UUID string of the contract.
        """
        data = self._client._post(f"/contracts/{contract_id}/complete")
        return ContractResponse(**data)

    def cancel(self, contract_id: str) -> ContractResponse:
        """Cancel an open contract and get its escrowed budget back.

        Only the creator may do this (403), and only while nobody has been
        assigned (409 otherwise). The contract becomes ``"cancelled"``.

        Args:
            contract_id: UUID string of the contract.
        """
        data = self._client._post(f"/contracts/{contract_id}/cancel")
        return ContractResponse(**data)
