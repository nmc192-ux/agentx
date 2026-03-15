"""
AgentX SDK — Contracts Client
═══════════════════════════════
Phase 13: Developer SDK

``ContractsClient`` provides a high-level interface for the full contract
lifecycle: creation, bidding, assignment, result submission, and verification.

Usage
─────
    contracts = ContractsClient(
        base_url="https://agentx.example.com",
        token="your-jwt",
    )

    contract = await contracts.create(
        title="Collect market data",
        capability_required="collect_data",
        budget=1000,
    )

    # Submit a bid (as an executor agent)
    bid = await contracts.submit_bid(contract["contract_id"], proposed_fee=800)

    # Assign the winning bid (as the contract creator)
    await contracts.assign(contract["contract_id"], bid["bid_id"])

    # Submit the result (as the assigned executor)
    result = await contracts.submit_result(
        contract["contract_id"],
        result_data={"rows": 42},
    )
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ContractsClient:
    """
    Client for the AgentX contract lifecycle endpoints.

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

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        title: str,
        capability_required: str,
        budget: int,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new contract.

        Args:
            title:               Short descriptive title.
            capability_required: Capability slug the executor must advertise.
            budget:              Max token budget.
            description:         Detailed work description (optional).

        Returns:
            dict — the created contract record (status = ``open``).
        """
        payload: dict[str, Any] = {
            "title":               title,
            "capability_required": capability_required,
            "budget":              budget,
        }
        if description is not None:
            payload["description"] = description

        async with self._client() as client:
            response = await client.post("/contracts", json=payload)
            response.raise_for_status()
            return response.json()

    async def get(self, contract_id: str) -> dict[str, Any]:
        """
        Fetch a single contract by UUID.

        Args:
            contract_id: UUID string of the contract.

        Returns:
            dict — the contract record.
        """
        async with self._client() as client:
            response = await client.get(f"/contracts/{contract_id}")
            response.raise_for_status()
            return response.json()

    async def list(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List contracts, optionally filtered by status.

        Args:
            status: Filter by lifecycle status (open | assigned | submitted |
                    completed | disputed).  Returns all statuses if ``None``.

        Returns:
            list[dict] — matching contract records.
        """
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status

        async with self._client() as client:
            response = await client.get("/contracts", params=params)
            response.raise_for_status()
            return response.json()

    # ── Bidding ───────────────────────────────────────────────────────────────

    async def submit_bid(
        self,
        contract_id: str,
        proposed_fee: int,
        proposal: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a bid to fulfil a contract (as an executor agent).

        Args:
            contract_id:  UUID of the target contract.
            proposed_fee: Token amount the executor requests.
            proposal:     Optional text description of the execution plan.

        Returns:
            dict — the created bid record.
        """
        payload: dict[str, Any] = {"proposed_fee": proposed_fee}
        if proposal is not None:
            payload["proposal"] = proposal

        async with self._client() as client:
            response = await client.post(
                f"/contracts/{contract_id}/bid", json=payload
            )
            response.raise_for_status()
            return response.json()

    async def assign(
        self,
        contract_id: str,
        bid_id: str,
    ) -> dict[str, Any]:
        """
        Assign the contract to the agent that submitted a specific bid.

        Only the contract creator can call this endpoint.

        Args:
            contract_id: UUID of the contract to assign.
            bid_id:      UUID of the bid to accept.

        Returns:
            dict — the updated contract record (status = ``assigned``).
        """
        async with self._client() as client:
            response = await client.post(
                f"/contracts/{contract_id}/assign",
                json={"bid_id": bid_id},
            )
            response.raise_for_status()
            return response.json()

    # ── Result submission ─────────────────────────────────────────────────────

    async def submit_result(
        self,
        contract_id: str,
        result_data: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit the execution result for an assigned contract.

        Args:
            contract_id: UUID of the contract.
            result_data: Arbitrary JSON-serialisable result payload.
            summary:     Optional human-readable summary.

        Returns:
            dict — the created result record.
        """
        payload: dict[str, Any] = {"result_data": result_data}
        if summary is not None:
            payload["summary"] = summary

        async with self._client() as client:
            response = await client.post(
                f"/contracts/{contract_id}/result", json=payload
            )
            response.raise_for_status()
            return response.json()

    async def complete(self, contract_id: str) -> dict[str, Any]:
        """
        Mark a submitted contract as completed (called by the creator).

        Args:
            contract_id: UUID of the contract.

        Returns:
            dict — the updated contract record (status = ``completed``).
        """
        async with self._client() as client:
            response = await client.post(f"/contracts/{contract_id}/complete")
            response.raise_for_status()
            return response.json()

    async def open_dispute(
        self,
        contract_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Open a dispute on a submitted contract (called by the creator).

        Args:
            contract_id: UUID of the contract.
            reason:      Human-readable explanation of the dispute.

        Returns:
            dict — the dispute record.
        """
        async with self._client() as client:
            response = await client.post(
                f"/contracts/{contract_id}/dispute",
                json={"reason": reason},
            )
            response.raise_for_status()
            return response.json()
