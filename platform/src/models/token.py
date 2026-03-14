"""
AgentX Platform — Token Economy Models
═══════════════════════════════════════
Phase 8: Pydantic models for wallets, transactions, and stakes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Wallet ─────────────────────────────────────────────────────────────────────

class WalletCreate(BaseModel):
    """Request body for creating or funding a wallet."""
    agent_id: UUID
    initial_balance: int = Field(default=0, ge=0, description="Tokens to credit on creation")


class WalletResponse(BaseModel):
    """Serialised wallet returned by the API."""
    wallet_id:   UUID
    agent_id:    Optional[UUID] = None   # NULL for the treasury wallet (Phase 8.5)
    balance:     int
    updated_at:  datetime
    wallet_type: str = "agent"           # 'agent' | 'treasury'  (Phase 8.5)


# ── Transaction ────────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    """Request body for a peer-to-peer token transfer."""
    from_id: UUID = Field(description="Agent UUID of the sender")
    to_id: UUID = Field(description="Agent UUID of the recipient")
    amount: int = Field(gt=0, description="Amount of tokens to transfer")
    type: str = Field(default="transfer", description="Transaction type label")


class TransactionResponse(BaseModel):
    """Serialised transaction returned by the API / service."""
    transaction_id: UUID
    from_wallet: Optional[UUID] = None   # NULL = system/escrow
    to_wallet: Optional[UUID] = None     # NULL = system/escrow
    amount: int
    type: str
    related_id: Optional[UUID] = None
    timestamp: datetime


# ── Stake ──────────────────────────────────────────────────────────────────────

class StakeCreate(BaseModel):
    """Request body for staking (locking) tokens."""
    agent_id: UUID
    amount: int = Field(gt=0, description="Number of tokens to stake")
    locked_until: Optional[datetime] = Field(
        default=None,
        description="Optional lock expiry; None = no lock period enforced",
    )


class StakeResponse(BaseModel):
    """Serialised stake record returned by the API."""
    stake_id: UUID
    agent_id: UUID
    amount: int
    locked_until: Optional[datetime] = None
    released_at: Optional[datetime] = None
    created_at: datetime
