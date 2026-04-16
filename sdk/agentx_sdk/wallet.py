"""AgentX SDK — Wallet namespace for token economy operations."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .client import AgentXClient


# ── Response models ──────────────────────────────────────────────────────────

class WalletResponse(BaseModel):
    """Wallet record returned by the API."""
    wallet_id:   UUID
    agent_id:    Optional[UUID] = None
    balance:     int
    updated_at:  datetime
    wallet_type: str = "agent"


class TransactionResponse(BaseModel):
    """Transaction record returned by the API."""
    transaction_id: UUID
    from_wallet:    Optional[UUID] = None
    to_wallet:      Optional[UUID] = None
    amount:         int
    type:           str
    related_id:     Optional[UUID] = None
    timestamp:      datetime


class StakeResponse(BaseModel):
    """Stake record returned by the API."""
    stake_id:     UUID
    agent_id:     UUID
    amount:       int
    locked_until: Optional[datetime] = None
    released_at:  Optional[datetime] = None
    created_at:   datetime


# ── Request models ───────────────────────────────────────────────────────────

class TransferRequest(BaseModel):
    """Request body for a peer-to-peer token transfer."""
    from_id: UUID = Field(description="Agent UUID of the sender")
    to_id:   UUID = Field(description="Agent UUID of the recipient")
    amount:  int  = Field(gt=0, description="Amount of tokens to transfer")
    type:    str  = Field(default="transfer", description="Transaction type label")


class StakeRequest(BaseModel):
    """Request body for staking (locking) tokens."""
    agent_id:     UUID
    amount:       int = Field(gt=0, description="Number of tokens to stake")
    locked_until: Optional[datetime] = Field(
        default=None,
        description="Optional lock expiry; None = no lock period enforced",
    )


# ── Namespace ────────────────────────────────────────────────────────────────

class WalletNamespace:
    """Token economy operations — accessed as ``client.wallet``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    # ── Wallets ────────────────────────────────────────────────────────────

    def create_wallet(self, initial_balance: int = 0) -> WalletResponse:
        """Create or fund a wallet for the current agent.

        Args:
            initial_balance: Tokens to credit on creation (default ``0``).
        """
        identity = self._client.identity
        agent_id = identity.agent_did if identity else ""
        data = self._client._post("/wallets", {
            "agent_id": agent_id,
            "initial_balance": initial_balance,
        })
        return WalletResponse(**data)

    def get_wallet(self) -> WalletResponse:
        """Get wallet details for the current agent."""
        identity = self._client.identity
        agent_id = identity.agent_did if identity else ""
        data = self._client._get(f"/wallets/{agent_id}")
        return WalletResponse(**data)

    def transfer(
        self,
        to_did: str,
        amount: int,
        tx_type: str = "PAYMENT",
    ) -> TransactionResponse:
        """Transfer tokens to another agent.

        Args:
            to_did:  Recipient agent DID or UUID string.
            amount:  Number of tokens to transfer.
            tx_type: Transaction type label (default ``"PAYMENT"``).
        """
        identity = self._client.identity
        from_id = identity.agent_did if identity else ""
        data = self._client._post("/wallets/transfer", {
            "from_id": from_id,
            "to_id": to_did,
            "amount": amount,
            "type": tx_type,
        })
        return TransactionResponse(**data)

    def list_transactions(self, limit: int = 50) -> list[TransactionResponse]:
        """List transaction history for the current agent.

        Args:
            limit: Maximum number of transactions to return (default ``50``).
        """
        identity = self._client.identity
        agent_id = identity.agent_did if identity else ""
        raw = self._client._get(f"/wallets/{agent_id}/transactions", limit=limit)
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [TransactionResponse(**t) for t in items]

    # ── Stakes ─────────────────────────────────────────────────────────────

    def stake(
        self,
        amount: int,
        locked_until: Optional[datetime] = None,
    ) -> StakeResponse:
        """Stake (lock) tokens from the current agent's wallet.

        Args:
            amount:       Number of tokens to stake.
            locked_until: Optional lock expiry datetime.
        """
        identity = self._client.identity
        agent_id = identity.agent_did if identity else ""
        body: dict = {
            "agent_id": agent_id,
            "amount": amount,
        }
        if locked_until is not None:
            body["locked_until"] = locked_until.isoformat()
        data = self._client._post("/stakes", body)
        return StakeResponse(**data)

    def list_stakes(self) -> list[StakeResponse]:
        """List active stakes for the current agent."""
        identity = self._client.identity
        agent_id = identity.agent_did if identity else ""
        raw = self._client._get(f"/stakes/{agent_id}")
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [StakeResponse(**s) for s in items]

    # ── Convenience ────────────────────────────────────────────────────────

    def get_balance(self) -> int:
        """Return the current agent's token balance."""
        return self.get_wallet().balance
