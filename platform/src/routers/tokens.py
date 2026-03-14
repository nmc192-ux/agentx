"""
AgentX Platform — Token Economy Router
═══════════════════════════════════════
Phase 8: Wallets and Stakes endpoints.

Two separate routers are exported:
  wallets_router — prefix /wallets
  stakes_router  — prefix /stakes

Route order matters for /wallets:
  POST /wallets/transfer  (registered BEFORE the /{agent_id} catch-all)
  GET  /wallets/{agent_id}/transactions
  GET  /wallets/{agent_id}
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import get_current_agent
from ..models.token import (
    StakeCreate,
    StakeResponse,
    TransactionCreate,
    TransactionResponse,
    WalletCreate,
    WalletResponse,
)
from ..services import token_service

logger = logging.getLogger(__name__)

# ── Wallets router ─────────────────────────────────────────────────────────────

wallets_router = APIRouter(prefix="/wallets", tags=["Token Economy"])


@wallets_router.post(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or fund a wallet",
)
async def create_wallet(body: WalletCreate) -> WalletResponse:
    """
    Create a wallet for *agent_id* with *initial_balance* tokens,
    or add *initial_balance* to an existing wallet (idempotent).
    """
    try:
        return await token_service.create_wallet(
            body.agent_id, body.initial_balance
        )
    except Exception as exc:
        logger.warning("create_wallet error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@wallets_router.post(
    "/transfer",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer tokens between two wallets",
)
async def transfer_tokens(
    body: TransactionCreate,
    _agent=Depends(get_current_agent),
) -> TransactionResponse:
    """
    Transfer *amount* tokens from the sender's wallet to the receiver's wallet.
    Requires authentication.
    """
    try:
        return await token_service.transfer_tokens(
            from_agent_id=body.from_id,
            to_agent_id=body.to_id,
            amount=body.amount,
            tx_type=body.type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@wallets_router.get(
    "/{agent_id}/transactions",
    response_model=list[TransactionResponse],
    summary="List transaction history for an agent",
)
async def list_transactions(
    agent_id: UUID,
    limit: int = 50,
) -> list[TransactionResponse]:
    """Return the most recent *limit* transactions for *agent_id*."""
    return await token_service.get_transactions(agent_id, limit=limit)


@wallets_router.get(
    "/{agent_id}",
    response_model=WalletResponse,
    summary="Get wallet and balance for an agent",
)
async def get_wallet(agent_id: UUID) -> WalletResponse:
    """Return wallet details and current token balance for *agent_id*."""
    try:
        return await token_service.get_wallet(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Stakes router ──────────────────────────────────────────────────────────────

stakes_router = APIRouter(prefix="/stakes", tags=["Token Economy"])


@stakes_router.post(
    "",
    response_model=StakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Stake (lock) tokens",
)
async def stake_tokens(
    body: StakeCreate,
    _agent=Depends(get_current_agent),
) -> StakeResponse:
    """
    Lock *amount* tokens from the agent's wallet into a stake record.
    Requires authentication.
    """
    try:
        return await token_service.stake_tokens(
            agent_id=body.agent_id,
            amount=body.amount,
            locked_until=body.locked_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@stakes_router.get(
    "/{agent_id}",
    response_model=list[StakeResponse],
    summary="List active stakes for an agent",
)
async def list_stakes(agent_id: UUID) -> list[StakeResponse]:
    """Return all unreleased (active) stakes for *agent_id*."""
    return await token_service.get_stakes(agent_id)
