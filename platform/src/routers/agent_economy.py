"""
AgentX Platform — Agent Economy Router
════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Endpoints
─────────
  POST /markets/bounties/auto              — Agent-created bounty (requires auth; creator = caller)
  POST /contracts/{contract_id}/subcontract — Spawn a sub-contract (requires auth)
  GET  /economy/strategies                 — List all economic strategies
  POST /economy/strategies/select          — Select optimal strategy for an agent
  POST /economy/market-analysis            — Evaluate market health

Identity and money (Sprint 9, S9-7c): the two writes act as the JWT caller and
only ever debit the caller's own wallet, in the same transaction that creates
the bounty / sub-contract (no funds → nothing is created). Service errors map
to HTTP as in the contracts and markets routers: PermissionError → 403,
ContractConflictError / BountyConflictError → 409, "… not found" → 404,
anything else → 400. The two login-free POSTs only calculate on a bounded
request body; they read and write nothing.
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import get_current_agent
from ..models.agent_economy import (
    AutoBountyCreate,
    MarketAnalysisRequest,
    MarketAnalysisResponse,
    StrategyInfo,
    StrategySelectRequest,
    StrategySelectResponse,
    SubcontractCreate,
    SubcontractResponse,
)
from ..models.markets import BountyResponse
from ..services import agent_strategy
from ..services.contract_service import ContractConflictError
from ..services.markets import auto_bounty_service
from ..services.markets.bounty_service import BountyConflictError
from ..services import subcontract_service

logger = logging.getLogger(__name__)

agent_economy_router = APIRouter(tags=["Agent Economy"])


def _http_error(exc: Exception) -> HTTPException:
    """Map a service error to its HTTP response."""
    detail = str(exc)
    if isinstance(exc, PermissionError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (ContractConflictError, BountyConflictError)):
        code = status.HTTP_409_CONFLICT
    elif "not found" in detail.lower():
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


# ── POST /markets/bounties/auto ───────────────────────────────────────────────

@agent_economy_router.post(
    "/markets/bounties/auto",
    response_model=BountyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent-generated bounty",
)
async def create_agent_bounty(
    body: AutoBountyCreate,
    agent=Depends(get_current_agent),
) -> BountyResponse:
    """
    Allow an authenticated agent to publish a capability bounty.

    SECURITY: the creator is the JWT-authenticated caller (`agent.did`), NOT a
    value from the request body. This endpoint escrows *reward_pool* tokens from
    the creator's wallet, so it must only ever debit the caller's own wallet.
    Requiring `get_current_agent` (which rejects missing/invalid tokens with a
    401) makes it impossible to escrow from anyone else's wallet — closing the
    prior unauthenticated wallet-drain hole. Mirrors `markets.create_bounty`.

    The pool is escrowed in the same transaction as the create: a caller who
    cannot cover it gets a 400 and no bounty is created.
    """
    try:
        return await auto_bounty_service.create_agent_bounty(
            agent_did=agent.did,
            capability=body.capability,
            reward_pool=body.reward_pool,
            title=body.title,
            description=body.description,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── POST /contracts/{contract_id}/subcontract ─────────────────────────────────

@agent_economy_router.post(
    "/contracts/{contract_id}/subcontract",
    response_model=SubcontractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Spawn a sub-contract from an existing contract",
)
async def spawn_subcontract(
    contract_id: UUID,
    body: SubcontractCreate,
    agent=Depends(get_current_agent),
) -> SubcontractResponse:
    """
    The assigned contractor of *contract_id* may delegate work by spawning
    a child (sub-)contract.  The child contract encodes the parent reference
    inside its payload.

    Only the assigned contractor of the parent contract may call this
    endpoint (anyone else → 403), and only while the parent is 'assigned' or
    'submitted' (otherwise → 409). The child's budget is escrowed from the
    caller's own wallet in the same transaction (no funds → 400, no child).
    Requires authentication.
    """
    try:
        return await subcontract_service.spawn_subcontract(
            parent_contract_id=contract_id,
            caller_did=agent.did,
            data=body,
        )
    except (PermissionError, ValueError) as exc:
        raise _http_error(exc)


# ── GET /economy/strategies ───────────────────────────────────────────────────

@agent_economy_router.get(
    "/economy/strategies",
    response_model=List[StrategyInfo],
    summary="List all economic agent strategies",
)
async def list_strategies() -> List[StrategyInfo]:
    """
    Return descriptors for all available economic strategies:
    specialist, generalist, coordinator, validator.

    Open to unauthenticated callers.
    """
    raw = agent_strategy.list_strategies()
    return [StrategyInfo(**s) for s in raw]


# ── POST /economy/strategies/select ──────────────────────────────────────────

@agent_economy_router.post(
    "/economy/strategies/select",
    response_model=StrategySelectResponse,
    summary="Select the optimal strategy for an agent",
)
async def select_strategy(body: StrategySelectRequest) -> StrategySelectResponse:
    """
    Given an agent's capability list, recommend the most appropriate
    economic strategy (specialist / generalist / coordinator / validator).

    Open to unauthenticated callers: a pure calculation on the (bounded)
    request body. `agent_id` is only echoed back; nothing is read or stored.
    """
    strategy = agent_strategy.select_strategy(
        agent_id=body.agent_id,
        capabilities=body.capabilities,
    )
    n = len(body.capabilities)
    if n == 0:
        rationale = "No capabilities declared; defaulting to generalist."
    elif n == 1:
        rationale = "Single capability — specialist strategy maximises depth."
    elif n >= 4:
        rationale = (
            f"{n} capabilities detected; coordinator strategy enables delegation."
        )
    else:
        rationale = (
            f"{n} capabilities detected; generalist strategy maximises opportunity."
        )

    return StrategySelectResponse(
        agent_id=body.agent_id,
        strategy=strategy.value,
        rationale=rationale,
    )


# ── POST /economy/market-analysis ─────────────────────────────────────────────

@agent_economy_router.post(
    "/economy/market-analysis",
    response_model=MarketAnalysisResponse,
    summary="Evaluate current market health",
)
async def market_analysis(body: MarketAnalysisRequest) -> MarketAnalysisResponse:
    """
    Compute a market-health snapshot from the supplied bounty and agent
    lists.  Useful for coordinator-strategy agents deciding whether to
    post new work.

    Open to unauthenticated callers: a pure calculation on the (bounded)
    request body; nothing is read or stored.
    """
    result = agent_strategy.evaluate_market(
        bounties=[b.model_dump() for b in body.bounties],
        agents=[a.model_dump() for a in body.agents],
    )
    return MarketAnalysisResponse(**result)
