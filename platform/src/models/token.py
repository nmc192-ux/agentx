"""
AgentX Platform — Token Economy Models
═══════════════════════════════════════
Phase 8: Pydantic models for wallets, transactions, and stakes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


#: Upper bound for any single amount in a request. Balances are BIGINT; an
#: unbounded integer would overflow in Postgres and surface as a 500.
MAX_TOKEN_AMOUNT = 1_000_000_000_000


# ── Wallet ─────────────────────────────────────────────────────────────────────

class WalletCreate(BaseModel):
    """
    Request body for creating or funding a wallet.

    agent_id defaults to the authenticated caller. Naming another agent, or a
    non-zero initial_balance (which mints tokens), requires the FOUNDER role.
    """
    agent_id: Optional[UUID] = None
    initial_balance: int = Field(default=0, ge=0, le=MAX_TOKEN_AMOUNT, description="Tokens to credit (FOUNDER only if > 0)")


class WalletCreateByDID(BaseModel):
    """Request body for creating or funding a wallet using an agent DID (no UUID needed)."""
    agent_did: str = Field(description="Agent DID (did:agentx:...)")
    initial_balance: int = Field(default=0, ge=0, le=MAX_TOKEN_AMOUNT, description="Tokens to credit (FOUNDER only if > 0)")


class WalletResponse(BaseModel):
    """Serialised wallet returned by the API."""
    wallet_id:   UUID
    agent_id:    Optional[UUID] = None   # NULL for the treasury wallet (Phase 8.5)
    balance:     int
    updated_at:  datetime
    wallet_type: str = "agent"           # 'agent' | 'treasury'  (Phase 8.5)


# ── Transaction ────────────────────────────────────────────────────────────────

#: Labels a caller may put on a peer transfer. System labels (stake, escrow,
#: fee, reward, treasury moves, ...) are written only by the service layer.
PEER_TX_TYPES = frozenset({"transfer", "payment", "tip"})


class TransactionCreate(BaseModel):
    """
    Request body for a peer-to-peer token transfer.

    The sender is always the authenticated caller. from_id is accepted for
    backward compatibility but must match the caller (else 403).
    """
    from_id: Optional[UUID] = Field(default=None, description="Must be the caller's agent UUID if given")
    to_id: UUID = Field(description="Agent UUID of the recipient")
    amount: int = Field(gt=0, le=MAX_TOKEN_AMOUNT, description="Amount of tokens to transfer")
    type: str = Field(default="transfer", description="One of: transfer, payment, tip")

    @field_validator("type")
    @classmethod
    def _peer_type_only(cls, v: str) -> str:
        label = v.strip().lower()
        if label not in PEER_TX_TYPES:
            raise ValueError(f"type must be one of {sorted(PEER_TX_TYPES)}")
        return label


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
    """
    Request body for staking (locking) tokens from the caller's own wallet.
    agent_id is accepted for backward compatibility but must match the caller.
    """
    agent_id: Optional[UUID] = None
    amount: int = Field(gt=0, le=MAX_TOKEN_AMOUNT, description="Number of tokens to stake")
    locked_until: Optional[datetime] = Field(
        default=None,
        description=(
            "Optional lock expiry: the stake cannot be released before it. "
            "None = releasable at any time"
        ),
    )


class StakeResponse(BaseModel):
    """Serialised stake record returned by the API."""
    stake_id: UUID
    agent_id: UUID
    amount: int
    locked_until: Optional[datetime] = None
    released_at: Optional[datetime] = None
    created_at: datetime
