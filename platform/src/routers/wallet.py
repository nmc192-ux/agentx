"""
AgentX Platform — Wallet Endpoints
═══════════════════════════════════
Balance queries, transaction history, and peer-to-peer transfers.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..database import get_db
from ..models.wallet import (
    BalanceResponse,
    TokenBalance,
    TokenType,
    TransactionResponse,
    TransferRequest,
    TransferResponse,
)
from ..services import token_service

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get(
    "/balance",
    response_model=BalanceResponse,
    summary="Get token balances",
)
async def get_balance(
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Return all token balances for the authenticated agent."""
    balances = []
    total = 0
    for tt in TokenType:
        bal = await token_service.get_balance(agent.did, tt.value)
        balances.append(TokenBalance(token_type=tt, balance=bal))
        total += bal

    return BalanceResponse(balances=balances, total_value=total)


@router.get(
    "/history",
    response_model=list[TransactionResponse],
    summary="Transaction history",
)
async def get_history(
    request: Request,
    token_type: Optional[TokenType] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Return recent token transactions for the authenticated agent."""
    agent_did = agent.did

    type_filter = ""
    params: list = [agent_did, limit]
    if token_type:
        type_filter = "AND t.token_type = $3::token_type"
        params.append(token_type.value)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                t.tx_id,
                t.token_type,
                t.amount,
                t.transaction_type AS tx_type,
                t.from_did,
                t.to_did,
                t.reference_id,
                t.memo,
                t.created_at
            FROM token_transactions t
            WHERE (t.from_did = $1 OR t.to_did = $1)
            {type_filter}
            ORDER BY t.created_at DESC
            LIMIT $2
            """,
            *params,
        )

    results = []
    for row in rows:
        direction = "IN" if row["to_did"] == agent_did else "OUT"
        counterparty = row["from_did"] if direction == "IN" else row["to_did"]
        results.append(TransactionResponse(
            tx_id=row["tx_id"],
            token_type=row["token_type"],
            amount=row["amount"],
            tx_type=row["tx_type"],
            counterparty_did=counterparty,
            reference_id=row["reference_id"],
            memo=row["memo"],
            direction=direction,
            created_at=row["created_at"],
        ))

    return results


@router.post(
    "/transfer",
    response_model=TransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer tokens",
)
async def transfer_tokens(
    body: TransferRequest,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Transfer tokens from authenticated agent to another agent."""
    from_did = agent.did

    if from_did == body.to_did:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot transfer to yourself",
        )

    try:
        await token_service.transfer(
            from_did=from_did,
            to_did=body.to_did,
            token_type=body.token_type.value,
            amount=body.amount,
            tx_type="TRANSFER",
            reference_id=None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Fetch the just-created transaction for the response
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT tx_id, from_did, to_did, token_type, amount, memo, created_at
            FROM token_transactions
            WHERE from_did = $1 AND to_did = $2 AND token_type = $3::token_type
            ORDER BY created_at DESC
            LIMIT 1
            """,
            from_did,
            body.to_did,
            body.token_type.value,
        )

    return TransferResponse(
        tx_id=row["tx_id"],
        from_did=from_did,
        to_did=body.to_did,
        token_type=body.token_type,
        amount=body.amount,
        memo=body.memo,
        created_at=row["created_at"],
    )
