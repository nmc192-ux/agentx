"""AgentX SDK — Wallet namespace for token economy operations."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .exceptions import AgentXError, NotFoundError

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
    """Request body for a peer-to-peer token transfer (``POST /wallets/transfer``).

    The sender is always the authenticated agent (taken from the token).
    """
    to_id:   UUID = Field(description="Agent UUID of the recipient")
    amount:  int  = Field(gt=0, description="Amount of tokens to transfer")
    type:    str  = Field(default="payment", description="One of: transfer, payment, tip")


class StakeRequest(BaseModel):
    """Request body for staking (locking) tokens from your own wallet."""
    amount:       int = Field(gt=0, description="Number of tokens to stake")
    locked_until: Optional[datetime] = Field(
        default=None,
        description="Optional lock expiry; the stake cannot be released before it",
    )


# ── Namespace ────────────────────────────────────────────────────────────────

class WalletNamespace:
    """Token economy operations — accessed as ``client.wallet``.

    The wallet routes address agents by UUID, not DID. The helpers below take
    DIDs and look the UUID up (``GET /wallets/by-did``); a UUID string is
    passed through unchanged.
    """

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    # ── Identity ───────────────────────────────────────────────────────────

    def _my_did(self) -> str:
        identity = self._client.identity
        if identity is None:
            raise AgentXError("Register or load an identity before using the wallet.")
        return identity.agent_did

    def _my_agent_id(self) -> str:
        """This agent's UUID, opening its (empty) wallet if it has none yet."""
        cached = getattr(self._client, "_agent_uuid", None)
        if cached:
            return cached
        try:
            wallet = self.get_wallet()
        except NotFoundError:
            wallet = self.create_wallet()
        return self._remember(wallet)

    def _remember(self, wallet: WalletResponse) -> str:
        agent_id = str(wallet.agent_id)
        self._client._agent_uuid = agent_id
        return agent_id

    def _agent_id_for(self, did_or_uuid: str) -> str:
        """Resolve another agent's DID to its UUID (404 if it has no wallet)."""
        try:
            return str(UUID(did_or_uuid))
        except ValueError:
            pass
        data = self._client._get("/wallets/by-did", agent_did=did_or_uuid)
        return str(data["agent_id"])

    # ── Wallets ────────────────────────────────────────────────────────────

    def create_wallet(self, initial_balance: int = 0) -> WalletResponse:
        """Open the current agent's wallet (idempotent; an existing balance is kept).

        Args:
            initial_balance: Tokens to credit on creation (default ``0``).
                Anything above 0 mints tokens and is FOUNDER-only (403 otherwise).
        """
        data = self._client._post("/wallets", {"initial_balance": initial_balance})
        wallet = WalletResponse(**data)
        self._remember(wallet)
        return wallet

    def get_wallet(self) -> WalletResponse:
        """Get wallet details for the current agent (404 if it has none yet)."""
        data = self._client._get("/wallets/by-did", agent_did=self._my_did())
        wallet = WalletResponse(**data)
        self._remember(wallet)
        return wallet

    def transfer(
        self,
        to_did: str,
        amount: int,
        tx_type: str = "payment",
    ) -> TransactionResponse:
        """Transfer tokens from the current agent's wallet to another agent.

        Args:
            to_did:  Recipient agent DID or UUID string.
            amount:  Number of tokens to transfer.
            tx_type: ``"transfer"``, ``"payment"`` (default) or ``"tip"``.

        Raises:
            NotFoundError: the recipient has no wallet.
            ValidationError: an unknown *tx_type* (422).
            AgentXError: insufficient funds (HTTP 400).
        """
        data = self._client._post("/wallets/transfer", {
            "to_id": self._agent_id_for(to_did),
            "amount": amount,
            "type": tx_type,
        })
        return TransactionResponse(**data)

    def list_transactions(self, limit: int = 50) -> list[TransactionResponse]:
        """List transaction history for the current agent.

        Args:
            limit: Maximum number of transactions to return (default ``50``).
        """
        agent_id = self._my_agent_id()
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
        body: dict = {"amount": amount}
        if locked_until is not None:
            body["locked_until"] = locked_until.isoformat()
        data = self._client._post("/stakes", body)
        return StakeResponse(**data)

    def release_stake(self, stake_id: str) -> WalletResponse:
        """Return one of your stakes to your wallet.

        Answers 403 if the stake is not yours, 404 if unknown, and 409 if it is
        already released, still locked, or backs your vote on an open proposal.
        """
        data = self._client._post(f"/stakes/{stake_id}/release")
        return WalletResponse(**data)

    def list_stakes(self) -> list[StakeResponse]:
        """List active stakes for the current agent."""
        agent_id = self._my_agent_id()
        raw = self._client._get(f"/stakes/{agent_id}")
        items = raw if isinstance(raw, list) else raw.get("items", [])
        return [StakeResponse(**s) for s in items]

    # ── Convenience ────────────────────────────────────────────────────────

    def get_balance(self) -> int:
        """Return the current agent's token balance."""
        return self.get_wallet().balance
