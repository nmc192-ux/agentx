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

All POST endpoints require a JWT and act only on the caller's own wallet;
minting (initial_balance > 0) or acting for another agent is FOUNDER-only.

Sprint 9 (S9-7a): POST /stakes/{stake_id}/release gives a stake back to its
owner (owner only, not before locked_until, paid once). Before it, nothing
could release a stake: staked tokens were locked for good.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.token import (
    StakeCreate,
    StakeResponse,
    TransactionCreate,
    TransactionResponse,
    WalletCreate,
    WalletCreateByDID,
    WalletResponse,
)
from ..database import get_db
from ..services import token_service

logger = logging.getLogger(__name__)

# ── Wallets router ─────────────────────────────────────────────────────────────

wallets_router = APIRouter(prefix="/wallets", tags=["Token Economy"])


# ── Ownership helpers ──────────────────────────────────────────────────────────
# Trust boundary: the acting agent is ALWAYS the JWT caller. Body identity fields
# are only accepted when they match the caller (or the caller is a FOUNDER, for
# wallet creation/funding). Anything else fails closed with 403.

async def _caller_agent_id(agent: AgentRecord) -> UUID:
    """Resolve the authenticated caller's DID to their agents.agent_id UUID."""
    async with get_db() as conn:
        agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent.did,
        )
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent has no agent record",
        )
    return agent_id


def _require_founder_for(agent: AgentRecord, *, other_agent: bool, mints: bool) -> None:
    """Creating a wallet for someone else, or minting tokens, is FOUNDER-only."""
    if (other_agent or mints) and not agent.is_founder():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only a FOUNDER may fund a wallet or create one for another agent; "
                "self-service wallets start at 0"
            ),
        )


@wallets_router.post(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or fund a wallet",
)
async def create_wallet(
    body: WalletCreate,
    agent: AgentRecord = Depends(get_current_agent),
) -> WalletResponse:
    """
    Create the caller's wallet (idempotent, balance unchanged if it exists).
    FOUNDER only: name another *agent_id* and/or credit *initial_balance*.
    """
    caller_id = await _caller_agent_id(agent)
    target_id = body.agent_id or caller_id
    _require_founder_for(
        agent, other_agent=target_id != caller_id, mints=body.initial_balance > 0,
    )
    try:
        return await token_service.create_wallet(target_id, body.initial_balance)
    except Exception as exc:
        logger.warning("create_wallet error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@wallets_router.post(
    "/by-did",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or fund a wallet by agent DID",
)
async def create_wallet_by_did(
    body: WalletCreateByDID,
    agent: AgentRecord = Depends(get_current_agent),
) -> WalletResponse:
    """
    Create a wallet for *agent_did* (resolves DID → UUID internally).
    Same rules as POST /wallets: self-service at 0, FOUNDER to fund or act for others.
    """
    _require_founder_for(
        agent, other_agent=body.agent_did != agent.did, mints=body.initial_balance > 0,
    )
    async with get_db() as conn:
        agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.agent_did,
        )
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {body.agent_did}",
        )
    try:
        return await token_service.create_wallet(agent_id, body.initial_balance)
    except Exception as exc:
        logger.warning("create_wallet_by_did error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@wallets_router.post(
    "/transfer",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer tokens between two wallets",
)
async def transfer_tokens(
    body: TransactionCreate,
    agent: AgentRecord = Depends(get_current_agent),
) -> TransactionResponse:
    """
    Transfer *amount* tokens from the caller's wallet to *to_id*'s wallet.
    Requires authentication; *from_id*, if sent, must be the caller.
    """
    caller_id = await _caller_agent_id(agent)
    if body.from_id is not None and body.from_id != caller_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only transfer from your own wallet",
        )
    try:
        return await token_service.transfer_tokens(
            from_agent_id=caller_id,
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
    limit: int = Query(default=50, ge=1, le=200),
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
    agent: AgentRecord = Depends(get_current_agent),
) -> StakeResponse:
    """
    Lock *amount* tokens from the caller's wallet into a stake record.
    Requires authentication; *agent_id*, if sent, must be the caller.
    """
    caller_id = await _caller_agent_id(agent)
    if body.agent_id is not None and body.agent_id != caller_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only stake from your own wallet",
        )
    try:
        return await token_service.stake_tokens(
            agent_id=caller_id,
            amount=body.amount,
            locked_until=body.locked_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@stakes_router.post(
    "/{stake_id}/release",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Release (unstake) one of your stakes",
)
async def release_stake(
    stake_id: UUID,
    agent: AgentRecord = Depends(get_current_agent),
) -> WalletResponse:
    """
    Return a stake's tokens to the caller's wallet.
    Owner only (403); already released or slashed, or still inside its lock
    period → 409; unknown stake → 404.
    """
    caller_id = await _caller_agent_id(agent)
    try:
        return await token_service.release_stake(stake_id, caller_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except token_service.StakeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


@stakes_router.get(
    "/{agent_id}",
    response_model=list[StakeResponse],
    summary="List active stakes for an agent",
)
async def list_stakes(agent_id: UUID) -> list[StakeResponse]:
    """Return all unreleased (active) stakes for *agent_id*."""
    return await token_service.get_stakes(agent_id)
