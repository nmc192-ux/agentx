"""
AgentX Platform — Agent Economy Router
════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Endpoints
─────────
  POST /markets/bounties/auto              — Agent-created bounty (no JWT; agent_did in body)
  POST /contracts/{contract_id}/subcontract — Spawn a sub-contract (requires auth)
  GET  /economy/strategies                 — List all economic strategies
  POST /economy/strategies/select          — Select optimal strategy for an agent
  POST /economy/market-analysis            — Evaluate market health
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
from ..services.markets import auto_bounty_service
from ..services import subcontract_service

logger = logging.getLogger(__name__)

agent_economy_router = APIRouter(tags=["Agent Economy"])


# ── POST /markets/bounties/auto ───────────────────────────────────────────────

@agent_economy_router.post(
    "/markets/bounties/auto",
    response_model=BountyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent-generated bounty",
)
async def create_agent_bounty(body: AutoBountyCreate) -> BountyResponse:
    """
    Allow an agent to autonomously publish a capability bounty.

    The agent DID is supplied in the request body (not a JWT) so that
    autonomous agents can call this endpoint without a human login flow.
    The agent's wallet is debited by *reward_pool* tokens as escrow.

    Open to unauthenticated callers — the agent_did in the body acts as
    the creator identity.
    """
    try:
        return await auto_bounty_service.create_agent_bounty(
            agent_did=body.agent_did,
            capability=body.capability,
            reward_pool=body.reward_pool,
            title=body.title,
            description=body.description,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)


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

    Only the active contractor of the parent contract may call this endpoint.
    Requires authentication.
    """
    try:
        return await subcontract_service.spawn_subcontract(
            parent_contract_id=contract_id,
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

    Open to unauthenticated callers.
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

    Open to unauthenticated callers.
    """
    result = agent_strategy.evaluate_market(
        bounties=body.bounties,
        agents=body.agents,
    )
    return MarketAnalysisResponse(**result)
