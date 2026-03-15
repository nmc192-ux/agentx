"""
AgentX SDK — Nodes Client
══════════════════════════
Phase 17: Federated AgentX Nodes.

Provides NodesClient for interacting with the /nodes REST endpoints.

Usage::

    from agentx_sdk.nodes import NodesClient

    client = NodesClient(base_url="https://agentx.example.com", token="jwt-token")

    # Register this node with a peer
    node = await client.register_node(node_url="https://my-node.example.com")

    # List all known peers
    peers = await client.list_nodes()

    # Send a federated event
    msg = await client.send_event(
        event_type="CONTRACT_COMPLETED",
        payload={"contract_id": "abc123"},
    )
"""
from __future__ import annotations

import httpx


class NodesClient:
    """HTTP client for the AgentX federated nodes API.

    All methods are async and use httpx.AsyncClient internally.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    # ── Public API ────────────────────────────────────────────────────────────

    async def register_node(
        self,
        node_url: str,
        node_name: str | None = None,
        public_key: str | None = None,
    ) -> dict:
        """POST /nodes/register — register (upsert) a peer node.

        Args:
            node_url:   Public URL of the peer node.
            node_name:  Optional human-readable name.
            public_key: Optional PEM / JWK public key for the node.

        Returns:
            Node record dict (node_id, node_url, status, …).

        Raises:
            httpx.HTTPStatusError: On HTTP 4xx/5xx responses.
        """
        body: dict = {"node_url": node_url}
        if node_name is not None:
            body["node_name"] = node_name
        if public_key is not None:
            body["public_key"] = public_key

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/nodes/register",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def list_nodes(self, active_only: bool = False) -> list[dict]:
        """GET /nodes — list known peer nodes.

        Args:
            active_only: When True, only return nodes with status='active'.

        Returns:
            List of node record dicts.
        """
        params: dict = {}
        if active_only:
            params["active_only"] = "true"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/nodes",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_event(
        self,
        event_type: str,
        payload: dict | None = None,
        source_node_url: str | None = None,
    ) -> dict:
        """POST /nodes/events — submit a federated event to a node.

        Args:
            event_type:      Event type string (e.g. "CONTRACT_COMPLETED").
            payload:         Optional event payload dict.
            source_node_url: Optional URL identifying the originating node.

        Returns:
            NodeMessageResponse dict (message_id, direction, …).

        Raises:
            httpx.HTTPStatusError: On HTTP 4xx/5xx responses.
        """
        body: dict = {
            "event_type": event_type,
            "payload": payload or {},
        }
        if source_node_url is not None:
            body["source_node_url"] = source_node_url

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/nodes/events",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
