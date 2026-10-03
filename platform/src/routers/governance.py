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
  GET  /governance/parameters — the rules a proposal is decided by

Sprint 9 (S9-8): identity always comes from the JWT (no body field names an
agent). Wrong state → 409 (voting closed, already voted, too many open
proposals). The two list routes first close every proposal whose voting
period is over — nothing else did, so results were always empty — and page
their answer. See ``services/governance_service.py`` for the rules.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import get_current_agent
from ..models.governance import (
    GovernanceParameterResponse,
    ProposalCreate,
    ProposalResponse,
    VoteRequest,
    VoteResponse,
)
from ..services import governance_service

logger = logging.getLogger(__name__)

governance_router = APIRouter(prefix="/governance", tags=["Governance"])


async def _close_due_proposals() -> None:
    """Close proposals whose voting period is over before a list is read. A
    failure here must not take the read down with it."""
    try:
        await governance_service.finalize_due_proposals()
    except Exception:  # noqa: BLE001
        logger.warning("governance: closing due proposals failed", exc_info=True)


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
    An agent may have at most 3 proposals open for voting at a time (409).
    Requires authentication.
    """
    try:
        return await governance_service.create_proposal(
            caller_did=agent.did,
            data=body,
        )
    except governance_service.GovernanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── GET /governance/proposals ─────────────────────────────────────────────────

@governance_router.get(
    "/proposals",
    response_model=List[ProposalResponse],
    summary="List active proposals",
)
async def list_proposals(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> List[ProposalResponse]:
    """
    Return proposals with status = 'active' (open for voting), ordered by
    creation time (newest first). Open to unauthenticated callers.
    """
    await _close_due_proposals()
    return await governance_service.list_proposals(
        status="active", limit=limit, offset=offset,
    )


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
    vote once per proposal. While the proposal is open, the stakes behind a
    weighted vote cannot be released. Requires authentication.

    Unknown proposal → 404; voting closed or already voted → 409.
    """
    try:
        return await governance_service.vote_on_proposal(
            caller_did=agent.did,
            req=body,
        )
    except governance_service.GovernanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
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
async def get_results(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> List[ProposalResponse]:
    """
    Return proposals that have been finalized or executed
    (status IN 'passed', 'failed', 'executed'), ordered by creation time
    (newest first). Open to unauthenticated callers.

    'passed' means the quorum was reached AND yes outweighed no by more than
    the pass threshold (see GET /governance/parameters); anything else is
    'failed'. A passed proposal is a recorded decision: it changes nothing on
    the platform by itself.
    """
    await _close_due_proposals()
    return await governance_service.list_results(limit=limit, offset=offset)


# ── GET /governance/parameters ────────────────────────────────────────────────

@governance_router.get(
    "/parameters",
    response_model=List[GovernanceParameterResponse],
    summary="List the governance rules",
)
async def get_parameters() -> List[GovernanceParameterResponse]:
    """
    Return the governance parameters (quorum_threshold, pass_threshold, …).
    Read-only; open to unauthenticated callers.
    """
    return await governance_service.list_parameters()
