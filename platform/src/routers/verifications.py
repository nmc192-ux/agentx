"""
AgentX Platform — Result Verification Engine Router
════════════════════════════════════════════════════
Phase 12: Decentralised result verification.

Endpoints
─────────
  POST /verifications                  — request verification (requires auth)
  POST /verifications/{id}/vote        — submit a vote (requires auth)
  GET  /verifications/pending          — list pending/active verifications (public)
  GET  /verifications/{id}             — get a verification by ID (public)
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import get_current_agent
from ..models.verification import (
    VerificationCreate,
    VerificationResponse,
    VerificationVoteCreate,
    VerificationVoteResponse,
)
from ..services import verification_service

logger = logging.getLogger(__name__)

verifications_router = APIRouter(prefix="/verifications", tags=["Verification Engine"])


# ── POST /verifications ───────────────────────────────────────────────────────

@verifications_router.post(
    "",
    response_model=VerificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request verification of a contract result",
)
async def create_verification(
    body: VerificationCreate,
    agent=Depends(get_current_agent),
) -> VerificationResponse:
    """
    Create a verification request for a submitted contract result.
    The authenticated caller must be the contract creator.
    Requires authentication.
    """
    try:
        return await verification_service.create_verification(
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


# ── POST /verifications/{id}/vote ─────────────────────────────────────────────

@verifications_router.post(
    "/{verification_id}/vote",
    response_model=VerificationVoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a vote on a verification",
)
async def submit_vote(
    verification_id: UUID,
    body: VerificationVoteCreate,
    agent=Depends(get_current_agent),
) -> VerificationVoteResponse:
    """
    Submit an 'approve' or 'reject' vote on an active verification.
    Vote power is weighted by stake × trust_score.
    Requires authentication.
    """
    try:
        return await verification_service.submit_vote(
            verification_id=verification_id,
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


# ── GET /verifications/pending ────────────────────────────────────────────────
# NOTE: this static route is declared BEFORE the /{id} parameterised route so
# FastAPI resolves "/pending" as a literal path, not as a UUID parameter.

@verifications_router.get(
    "/pending",
    response_model=List[VerificationResponse],
    summary="List pending and active verifications",
)
async def list_pending_verifications() -> List[VerificationResponse]:
    """
    Return all pending and active verifications, newest first.
    Open to unauthenticated callers.
    """
    return await verification_service.list_pending_verifications()


# ── GET /verifications/{id} ───────────────────────────────────────────────────

@verifications_router.get(
    "/{verification_id}",
    response_model=VerificationResponse,
    summary="Get a verification by ID",
)
async def get_verification(verification_id: UUID) -> VerificationResponse:
    """
    Return a single verification.  Open to unauthenticated callers.
    """
    try:
        return await verification_service.get_verification(verification_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
