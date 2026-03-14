"""
AgentX Platform — Economic Engine Models
═════════════════════════════════════════
Phase 8.5: Pydantic models for supply management, fee policies,
stake slashing, and economic metrics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Token Supply ───────────────────────────────────────────────────────────────

class TokenSupplyResponse(BaseModel):
    """Snapshot of total token supply."""
    supply_id:    UUID
    total_minted: int
    total_burned: int
    circulating:  int          # total_minted - total_burned (computed)
    updated_at:   datetime


# ── Fee Policy ─────────────────────────────────────────────────────────────────

class FeePolicyResponse(BaseModel):
    policy_id:  UUID
    name:       str
    rate_bps:   int            # basis points, e.g. 250 = 2.5 %
    active:     bool
    created_at: datetime


# ── Stake Slash ────────────────────────────────────────────────────────────────

class StakeSlashResponse(BaseModel):
    """Record of a slashed stake."""
    slash_id:   UUID
    stake_id:   UUID
    agent_id:   UUID
    amount:     int
    reason:     Optional[str] = None
    created_at: datetime


# ── Economic Metrics ───────────────────────────────────────────────────────────

class EconomicMetricsResponse(BaseModel):
    """Point-in-time economic snapshot."""
    metric_id:        UUID
    total_supply:     int
    treasury_balance: int
    total_staked:     int
    active_tasks:     int
    fees_collected:   int
    recorded_at:      datetime


# ── Request Bodies ─────────────────────────────────────────────────────────────

class MintRequest(BaseModel):
    """Request body for POST /economy/mint."""
    amount: int = Field(gt=0, description="Number of tokens to mint into treasury")
    reason: str = Field(default="mint", description="Reason label for the ledger entry")


class SlashRequest(BaseModel):
    """Request body for POST /economy/slash."""
    stake_id: UUID = Field(description="UUID of the stake to slash")
    reason:   str  = Field(default="", description="Human-readable reason for the slash")
