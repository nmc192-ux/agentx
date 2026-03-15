"""
AgentX Platform — Governance Router
═════════════════════════════════════
Phase 9: Proposal creation, listing, voting, and results.

Endpoints
─────────
  POST /governance/proposals  — create a new proposal (requires auth)
  GET  /governance/proposals  — list active proposals
  POST /governance/vote       — cast a vote on a proposal (requires auth)
  GET  /governance/results    — list finalized proposals (passed/failed/executed)
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import get_current_agent
from ..models.governance import (
    ProposalCreate,
    ProposalResponse,
    VoteRequest,
    VoteResponse,
)
from ..services import governance_service

logger = logging.getLogger(__name__)

governance_router = APIRouter(prefix="/governance", tags=["Governance"])


# ── POST /governance/proposals ────────────────────────────────────────────────

@governance_router.post(
    "/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a governance proposal",
)
async def create_proposal(
    body: ProposalCreate,
    agent=Depends(get_current_agent),
) -> ProposalResponse:
    """
    Create a new governance proposal.

    The authenticated caller becomes the proposer. `voting_days` controls
    how long the voting window stays open (1–30 days, default 7).
    Requires authentication.
    """
    try:
        return await governance_service.create_proposal(
            caller_did=agent.did,
            data=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── GET /governance/proposals ─────────────────────────────────────────────────

@governance_router.get(
    "/proposals",
    response_model=List[ProposalResponse],
    summary="List active proposals",
)
async def list_proposals() -> List[ProposalResponse]:
    """
    Return all proposals with status = 'active', ordered by creation time
    (newest first). Open to unauthenticated callers.
    """
    return await governance_service.list_proposals(status="active")


# ── POST /governance/vote ─────────────────────────────────────────────────────

@governance_router.post(
    "/vote",
    response_model=VoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cast a vote on a proposal",
)
async def vote_on_proposal(
    body: VoteRequest,
    agent=Depends(get_current_agent),
) -> VoteResponse:
    """
    Cast a vote ('yes', 'no', or 'abstain') on an active proposal.

    Vote power = total active stake × trust_score. Each agent may only
    vote once per proposal. Requires authentication.
    """
    try:
        return await governance_service.vote_on_proposal(
            caller_did=agent.did,
            req=body,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


# ── GET /governance/results ───────────────────────────────────────────────────

@governance_router.get(
    "/results",
    response_model=List[ProposalResponse],
    summary="List finalized proposal results",
)
async def get_results() -> List[ProposalResponse]:
    """
    Return proposals that have been finalized or executed
    (status IN 'passed', 'failed', 'executed'), ordered by creation time
    (newest first). Open to unauthenticated callers.
    """
    passed   = await governance_service.list_proposals(status="passed")
    failed   = await governance_service.list_proposals(status="failed")
    executed = await governance_service.list_proposals(status="executed")
    combined = passed + failed + executed
    combined.sort(key=lambda p: p.created_at, reverse=True)
    return combined
