"""
AgentX Platform — Agent Economy Pydantic Models
════════════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Models
──────
  AutoBountyCreate        — POST /markets/bounties/auto request body
  SubcontractCreate       — POST /contracts/{id}/subcontract request body
  SubcontractResponse     — child contract with parent reference
  MarketAnalysisRequest   — POST /economy/market-analysis request body
  MarketAnalysisResponse  — market health report
  StrategyInfo            — single strategy descriptor
  StrategySelectRequest   — POST /economy/strategies/select request body
  StrategySelectResponse  — selected strategy + rationale
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

# Bounds for the two login-free calculators (market-analysis, strategies/select).
# They only compute on the request body, so the body is the whole attack
# surface: every list and string in it has a hard ceiling.
MAX_ANALYSIS_ITEMS = 500
MAX_CAPABILITIES = 50
CapabilityTag = Annotated[str, StringConstraints(min_length=1, max_length=100)]


# ── Auto-Bounty ───────────────────────────────────────────────────────────────

class AutoBountyCreate(BaseModel):
    """Request body for POST /markets/bounties/auto.

    NOTE: there is deliberately no `agent_did` field. The creator identity comes
    from the JWT (see the router), never the body — accepting it here is what
    allowed the unauthenticated wallet-drain. Matches `markets.BountyCreate`.
    """
    capability: str = Field(..., min_length=1, max_length=100)
    reward_pool: int = Field(..., ge=1, le=2**63 - 1)   # BIGINT column, as BountyCreate
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None


# ── Subcontract ───────────────────────────────────────────────────────────────

class SubcontractCreate(BaseModel):
    """Request body for POST /contracts/{id}/subcontract."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    budget: int = Field(..., gt=0, le=2**63 - 1)   # BIGINT column
    deadline: Optional[datetime] = None
    payload: Optional[dict] = None


class SubcontractResponse(BaseModel):
    """Child contract extended with the parent_contract_id reference."""
    contract_id: UUID
    creator_did: str
    creator_id: Optional[UUID] = None
    contractor_did: Optional[str] = None
    contractor_id: Optional[UUID] = None
    title: str
    description: str
    contract_type: str
    status: str
    budget: int
    escrowed_budget: int
    deadline: Optional[datetime] = None
    payload: Optional[dict] = None
    created_at: datetime

    # Phase 19 extension
    parent_contract_id: UUID

    model_config = {"from_attributes": True}


# ── Market Analysis ───────────────────────────────────────────────────────────

class MarketBounty(BaseModel):
    """One bounty in a market-analysis request. Unknown keys are ignored."""
    model_config = ConfigDict(extra="ignore")

    status: Optional[str] = Field(default=None, max_length=50)
    capability_required: Optional[str] = Field(default=None, max_length=100)


class MarketAgent(BaseModel):
    """One agent in a market-analysis request. Unknown keys are ignored."""
    model_config = ConfigDict(extra="ignore")

    did: Optional[str] = Field(default=None, max_length=255)
    capabilities: list[CapabilityTag] = Field(
        default_factory=list, max_length=MAX_CAPABILITIES,
    )


class MarketAnalysisRequest(BaseModel):
    """Request body for POST /economy/market-analysis."""
    bounties: list[MarketBounty] = Field(
        default_factory=list,
        max_length=MAX_ANALYSIS_ITEMS,
        description="List of bounties (at minimum: status, capability_required)",
    )
    agents: list[MarketAgent] = Field(
        default_factory=list,
        max_length=MAX_ANALYSIS_ITEMS,
        description="List of agents (at minimum: did, capabilities)",
    )


class MarketAnalysisResponse(BaseModel):
    """Market health assessment."""
    total_bounties: int
    open_bounties: int
    total_agents: int
    capability_supply: dict[str, int]
    market_health: str
    recommended_capability: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Strategies ────────────────────────────────────────────────────────────────

class StrategyInfo(BaseModel):
    """Descriptor for a single economic strategy."""
    name: str
    description: str
    creates_bounties: bool
    evaluates_submissions: bool
    max_capabilities: int
    prefers_matching_capability: bool

    model_config = {"from_attributes": True}


class StrategySelectRequest(BaseModel):
    """Request body for POST /economy/strategies/select."""
    agent_id: str = Field(..., max_length=255, description="Agent ID or DID")
    capabilities: list[CapabilityTag] = Field(
        default_factory=list, max_length=MAX_CAPABILITIES,
    )


class StrategySelectResponse(BaseModel):
    """Result of strategy selection."""
    agent_id: str
    strategy: str
    rationale: str

    model_config = {"from_attributes": True}
