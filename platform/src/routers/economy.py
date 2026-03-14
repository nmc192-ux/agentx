"""
AgentX Platform — Economic Engine Router
═════════════════════════════════════════
Phase 8.5: Treasury management, token minting, stake slashing, and metrics.

Endpoints
─────────
  GET  /economy/metrics  — latest economic snapshot
  GET  /economy/treasury — treasury wallet balance
  POST /economy/mint     — mint tokens into treasury (requires auth)
  POST /economy/slash    — slash a stake (requires auth)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import get_current_agent
from ..models.economy import (
    EconomicMetricsResponse,
    MintRequest,
    SlashRequest,
    StakeSlashResponse,
    TokenSupplyResponse,
)
from ..models.token import WalletResponse
from ..services import economy_service

logger = logging.getLogger(__name__)

economy_router = APIRouter(prefix="/economy", tags=["Economic Engine"])


# ── GET /economy/metrics ──────────────────────────────────────────────────────

@economy_router.get(
    "/metrics",
    response_model=Optional[EconomicMetricsResponse],
    summary="Get latest economic metrics snapshot",
)
async def get_metrics() -> Optional[EconomicMetricsResponse]:
    """
    Return the most recent economic metrics snapshot.
    Returns null if no snapshot has been recorded yet.
    """
    return await economy_service.get_latest_metrics()


# ── GET /economy/treasury ─────────────────────────────────────────────────────

@economy_router.get(
    "/treasury",
    response_model=WalletResponse,
    summary="Get treasury wallet balance",
)
async def get_treasury() -> WalletResponse:
    """
    Return the treasury wallet and its current token balance.
    Returns 404 if the treasury has not been initialised yet.
    """
    try:
        return await economy_service.get_treasury_balance()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── POST /economy/mint ────────────────────────────────────────────────────────

@economy_router.post(
    "/mint",
    response_model=TokenSupplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Mint tokens into the treasury",
)
async def mint_tokens(
    body: MintRequest,
    _agent=Depends(get_current_agent),
) -> TokenSupplyResponse:
    """
    Mint *amount* new tokens directly into the treasury wallet.
    Updates the total_minted counter in token_supply.
    Requires authentication.
    """
    try:
        return await economy_service.mint_tokens(body.amount, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── POST /economy/slash ───────────────────────────────────────────────────────

@economy_router.post(
    "/slash",
    response_model=StakeSlashResponse,
    status_code=status.HTTP_200_OK,
    summary="Slash a stake (forfeit to treasury)",
)
async def slash_stake(
    body: SlashRequest,
    _agent=Depends(get_current_agent),
) -> StakeSlashResponse:
    """
    Forfeit the full amount of a stake to the treasury.
    Marks the stake as released and records an immutable slash event.
    Requires authentication.
    """
    try:
        return await economy_service.slash_stake(body.stake_id, body.reason)
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)
