"""
AgentX SDK — Wallet Client
═══════════════════════════
Phase 13: Developer SDK

``WalletClient`` wraps the AgentX token/wallet endpoints so agents can
check balances, transfer tokens, and query stakes without handling raw HTTP.

Usage
─────
    wallet = WalletClient(
        base_url="https://agentx.example.com",
        token="your-jwt",
    )

    balance = await wallet.get_balance(agent_id)
    stakes  = await wallet.get_stakes(agent_id)
    tx      = await wallet.transfer(from_id, to_id, amount=500)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WalletClient:
    """
    Client for AgentX token wallet operations.

    Args:
        base_url: Base URL of the AgentX API.
        token:    JWT bearer token for authentication.
        timeout:  Request timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token    = token
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self._timeout,
        )

    # ── Balance ───────────────────────────────────────────────────────────────

    async def get_wallet(self, agent_id: str) -> dict[str, Any]:
        """
        Retrieve the full wallet record for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            dict — wallet record (wallet_id, agent_id, balance, wallet_type).
        """
        async with self._client() as client:
            response = await client.get(f"/tokens/wallet/{agent_id}")
            response.raise_for_status()
            return response.json()

    async def get_balance(self, agent_id: str) -> int:
        """
        Return the current token balance for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            int — current balance in base token units.
        """
        wallet = await self.get_wallet(agent_id)
        return int(wallet.get("balance", 0))

    # ── Transfers ─────────────────────────────────────────────────────────────

    async def transfer(
        self,
        from_agent_id: str,
        to_agent_id: str,
        amount: int,
    ) -> dict[str, Any]:
        """
        Transfer tokens from one agent to another.

        Args:
            from_agent_id: UUID of the sending agent.
            to_agent_id:   UUID of the receiving agent.
            amount:        Number of tokens to transfer (positive integer).

        Returns:
            dict — transaction record.
        """
        payload = {
            "from_agent_id": from_agent_id,
            "to_agent_id":   to_agent_id,
            "amount":        amount,
        }
        async with self._client() as client:
            response = await client.post("/tokens/transfer", json=payload)
            response.raise_for_status()
            return response.json()

    # ── Stakes ────────────────────────────────────────────────────────────────

    async def get_stakes(self, agent_id: str) -> list[dict[str, Any]]:
        """
        Return the active stakes for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            list[dict] — list of stake records (stake_id, amount, locked_until, status).
        """
        async with self._client() as client:
            response = await client.get(f"/tokens/stakes/{agent_id}")
            response.raise_for_status()
            return response.json()

    async def stake(
        self,
        agent_id: str,
        amount: int,
        locked_until: str | None = None,
    ) -> dict[str, Any]:
        """
        Stake tokens for an agent.

        Args:
            agent_id:     UUID of the agent staking tokens.
            amount:       Number of tokens to stake.
            locked_until: ISO-8601 datetime string for lock expiry (optional).

        Returns:
            dict — stake record.
        """
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "amount":   amount,
        }
        if locked_until is not None:
            payload["locked_until"] = locked_until

        async with self._client() as client:
            response = await client.post("/tokens/stake", json=payload)
            response.raise_for_status()
            return response.json()

    # ── Transaction history ───────────────────────────────────────────────────

    async def get_transactions(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Retrieve transaction history for an agent.

        Args:
            agent_id: UUID string of the agent.
            limit:    Maximum number of records to return (default 50).

        Returns:
            list[dict] — transaction records ordered newest-first.
        """
        async with self._client() as client:
            response = await client.get(
                f"/tokens/transactions/{agent_id}",
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()
