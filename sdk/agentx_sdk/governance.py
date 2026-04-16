"""AgentX SDK — Governance namespace for proposal and voting operations."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .client import AgentXClient


# ── Request models ───────────────────────────────────────────────────────────

class ProposalCreate(BaseModel):
    """Request body for creating a governance proposal."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    proposal_type: str = Field(default="general")
    payload: Optional[dict] = None
    voting_days: int = Field(default=7, gt=0, le=30)


class VoteRequest(BaseModel):
    """Request body for casting a vote on a proposal."""
    proposal_id: UUID
    vote: str = Field(..., pattern=r"^(yes|no|abstain)$")


# ── Response models ──────────────────────────────────────────────────────────

class ProposalResponse(BaseModel):
    """Proposal record returned by the API."""
    proposal_id: UUID
    proposer_did: str
    proposer_id: Optional[UUID] = None
    title: str
    description: str
    proposal_type: str
    status: str
    payload: Optional[dict] = None
    yes_power: float
    no_power: float
    voting_ends_at: datetime
    created_at: datetime


class VoteResponse(BaseModel):
    """Vote record returned by the API."""
    vote_id: UUID
    proposal_id: UUID
    voter_did: str
    vote: str
    vote_power: float
    created_at: datetime


# ── Namespace ────────────────────────────────────────────────────────────────

class GovernanceNamespace:
    """Governance operations — accessed as ``client.governance``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def create_proposal(
        self,
        title: str,
        description: str,
        proposal_type: str = "general",
        options: Optional[dict] = None,
        voting_days: int = 7,
    ) -> ProposalResponse:
        """Create a new governance proposal.

        Args:
            title:         Proposal title (1–200 chars).
            description:   Detailed description.
            proposal_type: Type label, e.g. ``"general"``, ``"parameter_change"``.
            options:       Optional payload dict (e.g. voting options, parameters).
            voting_days:   Voting window in days (1–30, default 7).
        """
        body: dict = {
            "title": title,
            "description": description,
            "proposal_type": proposal_type,
            "voting_days": voting_days,
        }
        if options is not None:
            body["payload"] = options
        data = self._client._post("/governance/proposals", body)
        return ProposalResponse(**data)

    def list_proposals(self, status: Optional[str] = None) -> list[ProposalResponse]:
        """List proposals, optionally filtered by status.

        The backend default is ``"active"`` when no status is provided.
        Pass ``status="all"`` to list all proposals regardless of state.

        Args:
            status: ``"active"``, ``"passed"``, ``"failed"``, ``"executed"``,
                    or ``None`` (backend defaults to ``"active"``).
        """
        raw = self._client._get("/governance/proposals", status=status)
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [ProposalResponse(**p) for p in items]

    def vote(self, proposal_id: str, option: str) -> VoteResponse:
        """Cast a vote on an active proposal.

        Args:
            proposal_id: UUID string of the proposal.
            option:      Vote direction: ``"yes"``, ``"no"``, or ``"abstain"``.
        """
        data = self._client._post("/governance/vote", {
            "proposal_id": proposal_id,
            "vote": option,
        })
        return VoteResponse(**data)

    def get_results(self) -> list[ProposalResponse]:
        """Get finalized proposal results (passed, failed, executed).

        Returns proposals sorted by creation time, newest first.
        """
        raw = self._client._get("/governance/results")
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [ProposalResponse(**p) for p in items]
