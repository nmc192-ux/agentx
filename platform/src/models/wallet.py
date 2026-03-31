"""
AgentX Platform — Wallet Pydantic Schemas
══════════════════════════════════════════
Request/response models for the wallet endpoints.

Token types (from DB enum):
  GOV   — Governance tokens (voting power)
  REP   — Reputation tokens (endorsements, rewards)
  WORK  — Work tokens (task bounties, service payments)

Transaction types (from DB enum):
  MINT, BURN, TRANSFER, REWARD, PENALTY,
  TASK_BOUNTY, ENDORSEMENT, SLA_PENALTY, TREASURY_GRANT
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Enumerations ───────────────────────────────────────────────────────────────

class TokenType(str, Enum):
    GOV  = "GOV"
    REP  = "REP"
    WORK = "WORK"


class TransactionType(str, Enum):
    MINT            = "MINT"
    BURN            = "BURN"
    TRANSFER        = "TRANSFER"
    REWARD          = "REWARD"
    PENALTY         = "PENALTY"
    TASK_BOUNTY     = "TASK_BOUNTY"
    ENDORSEMENT     = "ENDORSEMENT"
    SLA_PENALTY     = "SLA_PENALTY"
    TREASURY_GRANT  = "TREASURY_GRANT"


# ── Balance models ─────────────────────────────────────────────────────────────

class TokenBalance(BaseModel):
    """Single token balance for one token type."""
    token_type: TokenType
    balance: int = Field(ge=0, description="Current token balance")


class BalanceResponse(BaseModel):
    """Response for GET /wallet/balance."""
    balances:    List[TokenBalance] = Field(description="Balances per token type")
    total_value: int = Field(ge=0, description="Sum of all token balances")


# ── Transaction models ─────────────────────────────────────────────────────────

class TransactionResponse(BaseModel):
    """Single transaction record returned from history."""
    tx_id:            UUID
    token_type:       TokenType
    amount:           int = Field(gt=0)
    tx_type:          TransactionType
    counterparty_did: Optional[str] = Field(
        default=None,
        description="The other party in the transaction (from_did or to_did, relative to caller)",
    )
    reference_id:     Optional[str] = Field(
        default=None,
        description="Associated resource (post_id, task_id, etc.)",
    )
    memo:             Optional[str] = None
    direction:        str = Field(description="'IN' if received, 'OUT' if sent")
    created_at:       datetime


# ── Transfer models ────────────────────────────────────────────────────────────

class TransferRequest(BaseModel):
    """Body for POST /wallet/transfer."""
    to_did:     str = Field(description="Recipient agent DID")
    token_type: TokenType
    amount:     int = Field(gt=0, description="Positive token amount to transfer")
    memo:       Optional[str] = Field(
        default=None,
        max_length=280,
        description="Optional transfer note",
    )

    @field_validator("to_did")
    @classmethod
    def validate_did(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("did:"):
            raise ValueError("to_did must be a valid DID (starts with 'did:')")
        return v


class TransferResponse(BaseModel):
    """Response for POST /wallet/transfer."""
    tx_id:       UUID
    from_did:    str
    to_did:      str
    token_type:  TokenType
    amount:      int
    memo:        Optional[str]
    created_at:  datetime
