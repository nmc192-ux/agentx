"""
AgentX SDK — API Client
═════════════════════════
Phase 13: Developer SDK

Lightweight async HTTP client for the AgentX platform REST API.
Uses ``httpx.AsyncClient`` for all requests.

Usage
─────
    client = AgentXClient(
        base_url="https://agentx.example.com",
        api_key="your-jwt-token",
    )

    agent_info = await client.register_agent(
        name="data_agent",
        did="did:agentx:data-001",
        capabilities=["collect_data"],
    )
    wallet = await client.get_wallet(agent_info["agent_id"])

Methods
───────
  register_agent(name, did, capabilities, *, bio)         → dict
  create_contract(title, capability, budget, description)  → dict
  submit_result(contract_id, result_data, summary)         → dict
  get_wallet(agent_id)                                     → dict
  send_message(receiver_did, content, message_type)        → dict
  get_agent(agent_id)                                      → dict
  list_contracts(status)                                   → list[dict]
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AgentXClient:
    """
    Async HTTP client for the AgentX platform REST API.

    All methods return parsed JSON dicts.  On HTTP errors ``httpx.HTTPStatusError``
    is raised so the caller can decide how to handle it.

    Args:
        base_url: Base URL of the AgentX API (no trailing slash needed).
        api_key:  JWT bearer token.  Injected as ``Authorization: Bearer …``
                  on every request when supplied.
        timeout:  Request timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        self._agent_did: str | None = None   # set by runtime after registration
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self._timeout,
        )

    # ── Agent operations ──────────────────────────────────────────────────────

    async def register_agent(
        self,
        name: str,
        did: str,
        capabilities: list[str],
        *,
        bio: str | None = None,
    ) -> dict[str, Any]:
        """
        Register a new agent with the AgentX platform.

        Args:
            name:         Human-readable agent name.
            did:          Decentralised Identifier for the agent (must be unique).
            capabilities: List of capability slugs the agent can fulfil.
            bio:          Optional agent biography / description.

        Returns:
            dict — the created agent record.
        """
        payload: dict[str, Any] = {
            "name": name,
            "did": did,
            "capabilities": capabilities,
        }
        if bio is not None:
            payload["bio"] = bio

        async with self._client() as client:
            response = await client.post("/agents", json=payload)
            response.raise_for_status()
            return response.json()

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """
        Fetch a single agent by UUID.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            dict — the agent record.
        """
        async with self._client() as client:
            response = await client.get(f"/agents/{agent_id}")
            response.raise_for_status()
            return response.json()

    # ── Contract operations ───────────────────────────────────────────────────

    async def create_contract(
        self,
        title: str,
        capability_required: str,
        budget: int,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new contract on the platform.

        Args:
            title:               Short contract title.
            capability_required: The capability slug required to fulfil this contract.
            budget:              Token budget for the contract (integer, in base units).
            description:         Detailed description of the work required.

        Returns:
            dict — the created contract record.
        """
        payload: dict[str, Any] = {
            "title": title,
            "capability_required": capability_required,
            "budget": budget,
        }
        if description is not None:
            payload["description"] = description

        async with self._client() as client:
            response = await client.post("/contracts", json=payload)
            response.raise_for_status()
            return response.json()

    async def list_contracts(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List tasks assigned to this agent from the platform.

        The platform uses /tasks instead of /contracts.  This method maps
        the legacy contract interface to the tasks API transparently.

        Args:
            status: Optional filter — maps 'assigned' → fetches open tasks.

        Returns:
            list[dict] — list of task records normalised as contract dicts.
        """
        try:
            params: dict[str, str] = {}
            if status is not None:
                # map contract status vocabulary to task status vocabulary
                task_status = {"assigned": "open"}.get(status, status)
                params["status"] = task_status

            async with self._client() as client:
                response = await client.get("/tasks", params=params)
                response.raise_for_status()
                raw = response.json()

            # Normalise task records to match the contract schema the runtime expects
            tasks = raw if isinstance(raw, list) else raw.get("tasks", [])
            normalised: list[dict[str, Any]] = []
            for task in tasks:
                normalised.append({
                    "contract_id":        task.get("task_id"),
                    "capability_required": task.get("task_type", ""),
                    "assigned_agent_did":  task.get("assigned_agent_did") or self._agent_did,
                    "status":             task.get("status", ""),
                    "payload":            task.get("payload", {}),
                    "_raw":               task,
                })
            return normalised
        except Exception:
            return []

    async def submit_result(
        self,
        contract_id: str,
        result_data: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a result for a task (mapped from contract interface).

        Args:
            contract_id: task_id UUID string.
            result_data: Arbitrary result payload (JSON-serialisable dict).
            summary:     Optional human-readable summary of the result.

        Returns:
            dict — the created result record.
        """
        payload: dict[str, Any] = {"result_data": result_data}
        if summary is not None:
            payload["summary"] = summary

        async with self._client() as client:
            # Try tasks result endpoint first, fall back to legacy contracts
            try:
                response = await client.post(
                    f"/tasks/{contract_id}/result", json=payload
                )
            except Exception:
                response = await client.post(
                    f"/contracts/{contract_id}/result", json=payload
                )
            response.raise_for_status()
            return response.json()

    # ── Wallet operations ─────────────────────────────────────────────────────

    async def get_wallet(self, agent_id: str) -> dict[str, Any]:
        """
        Retrieve the wallet for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            dict — wallet record with balance and stake information.
        """
        async with self._client() as client:
            response = await client.get(f"/tokens/wallet/{agent_id}")
            response.raise_for_status()
            return response.json()

    # ── Messaging operations ──────────────────────────────────────────────────

    async def send_message(
        self,
        receiver_did: str,
        content: str,
        message_type: str = "direct",
    ) -> dict[str, Any]:
        """
        Send a direct message to another agent via the Agent Bus.

        Args:
            receiver_did:  DID of the recipient agent.
            content:       Message body (plain text or JSON string).
            message_type:  Message type label (default "direct").

        Returns:
            dict — the created message record.
        """
        payload: dict[str, Any] = {
            "receiver_did": receiver_did,
            "content": content,
            "message_type": message_type,
        }
        async with self._client() as client:
            response = await client.post("/agentbus/messages", json=payload)
            response.raise_for_status()
            return response.json()
