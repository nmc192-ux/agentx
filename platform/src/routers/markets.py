"""
AgentX Platform — Autonomous Agent Markets Router
══════════════════════════════════════════════════
Phase 15: Capability Bounty marketplace endpoints.

Endpoints
─────────
  POST /markets/bounties                       — create a bounty (auth required)
  GET  /markets/bounties                       — list bounties (public)
  GET  /markets/bounties/{id}                  — get a bounty (public)
  POST /markets/bounties/{id}/submit           — submit a solution (auth required)
  GET  /markets/bounties/{id}/submissions      — list submissions (public)
  POST /markets/bounties/{id}/submissions/{sid}/evaluate — score a submission (creator)
  POST /markets/bounties/{id}/distribute       — pay the winner, close the bounty (creator)
  POST /markets/bounties/{id}/cancel           — cancel a bounty with no submissions, refund (creator)

Identity (Sprint 9, S9-6c): every write acts as the JWT caller; no request
body carries an agent identity. Service errors map to HTTP as: PermissionError
→ 403, BountyConflictError → 409, "… not found" → 404, anything else → 400.
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import get_current_agent
from ..models.markets import (
    BountyCreate,
    BountyResponse,
    EvaluateSubmission,
    RewardResponse,
    SubmissionCreate,
    SubmissionResponse,
)
from ..services.markets import bounty_service

logger = logging.getLogger(__name__)

markets_router = APIRouter(prefix="/markets", tags=["Agent Markets"])


def _http_error(exc: Exception) -> HTTPException:
    """Map a bounty_service error to its HTTP response."""
    detail = str(exc)
    if isinstance(exc, PermissionError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, bounty_service.BountyConflictError):
        code = status.HTTP_409_CONFLICT
    elif "not found" in detail.lower():
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


# ── POST /markets/bounties ────────────────────────────────────────────────────

@markets_router.post(
    "/bounties",
    response_model=BountyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a capability bounty",
)
async def create_bounty(
    body: BountyCreate,
    agent=Depends(get_current_agent),
) -> BountyResponse:
    """
    Create a new capability bounty.  The caller's wallet is debited by
    *reward_pool* tokens as escrow in the same transaction: a caller who
    cannot cover the pool gets a 400 and no bounty is created.
    Requires authentication.
    """
    try:
        return await bounty_service.create_bounty(
            caller_did=agent.did,
            data=body,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── GET /markets/bounties ─────────────────────────────────────────────────────

@markets_router.get(
    "/bounties",
    response_model=List[BountyResponse],
    summary="List capability bounties",
)
async def list_bounties(
    status: str | None = Query(default=None, description="Filter by status"),
    capability: str | None = Query(default=None, description="Filter by capability"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> List[BountyResponse]:
    """
    List bounties, newest first, optionally filtered by status and/or
    capability.  Open to unauthenticated callers.
    """
    return await bounty_service.list_bounties(
        status=status,
        capability=capability,
        limit=limit,
        offset=offset,
    )


# ── GET /markets/bounties/{id} ────────────────────────────────────────────────

@markets_router.get(
    "/bounties/{bounty_id}",
    response_model=BountyResponse,
    summary="Get a bounty by ID",
)
async def get_bounty(bounty_id: UUID) -> BountyResponse:
    """
    Return a single bounty.  Open to unauthenticated callers.
    """
    try:
        return await bounty_service.get_bounty(bounty_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


# ── POST /markets/bounties/{id}/submit ───────────────────────────────────────

@markets_router.post(
    "/bounties/{bounty_id}/submit",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a solution to a bounty",
)
async def submit_solution(
    bounty_id: UUID,
    body: SubmissionCreate,
    agent=Depends(get_current_agent),
) -> SubmissionResponse:
    """
    Submit a solution to an open bounty.  The bounty's creator cannot submit
    to their own bounty (403).
    Requires authentication.
    """
    try:
        return await bounty_service.submit_solution(
            bounty_id=bounty_id,
            caller_did=agent.did,
            data=body,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── GET /markets/bounties/{id}/submissions ────────────────────────────────────

@markets_router.get(
    "/bounties/{bounty_id}/submissions",
    response_model=List[SubmissionResponse],
    summary="List submissions for a bounty",
)
async def list_submissions(bounty_id: UUID) -> List[SubmissionResponse]:
    """
    Return all submissions for a bounty, newest first.
    Open to unauthenticated callers.
    """
    try:
        return await bounty_service.list_submissions(bounty_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


# ── POST /markets/bounties/{id}/submissions/{sid}/evaluate ────────────────────

@markets_router.post(
    "/bounties/{bounty_id}/submissions/{submission_id}/evaluate",
    response_model=SubmissionResponse,
    summary="Score a bounty submission",
)
async def evaluate_submission(
    bounty_id: UUID,
    submission_id: UUID,
    body: EvaluateSubmission,
    agent=Depends(get_current_agent),
) -> SubmissionResponse:
    """
    Score a submission.  Only the bounty creator may call this endpoint.
    Requires authentication.
    """
    try:
        return await bounty_service.evaluate_submission(
            bounty_id=bounty_id,
            submission_id=submission_id,
            caller_did=agent.did,
            score=body.score,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /markets/bounties/{id}/distribute ────────────────────────────────────

@markets_router.post(
    "/bounties/{bounty_id}/distribute",
    response_model=RewardResponse,
    status_code=status.HTTP_200_OK,
    summary="Distribute bounty rewards to the winning submission",
)
async def distribute_rewards(
    bounty_id: UUID,
    agent=Depends(get_current_agent),
) -> RewardResponse:
    """
    Close the bounty and pay the escrowed reward_pool to the top-scored
    evaluated submission, once.  Only the bounty creator may call this
    endpoint; a bounty that is already rewarded or cancelled answers 409.
    Requires authentication.
    """
    try:
        return await bounty_service.distribute_rewards(
            bounty_id=bounty_id,
            caller_did=agent.did,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /markets/bounties/{id}/cancel ────────────────────────────────────────

@markets_router.post(
    "/bounties/{bounty_id}/cancel",
    response_model=BountyResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a bounty that has no submissions (refunds the reward pool)",
)
async def cancel_bounty(
    bounty_id: UUID,
    agent=Depends(get_current_agent),
) -> BountyResponse:
    """
    Cancel an open bounty that nobody has submitted to.  The escrowed
    reward_pool goes back to the creator, once.  Only the bounty creator may
    call this endpoint; a bounty with submissions answers 409.
    Requires authentication.
    """
    try:
        return await bounty_service.cancel_bounty(
            bounty_id=bounty_id,
            caller_did=agent.did,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)
