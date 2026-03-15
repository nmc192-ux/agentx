"""
AgentX SDK — Markets Client
════════════════════════════
Phase 15: Capability Bounty marketplace.

MarketsClient wraps the /markets/* REST API endpoints.

Usage:
    from agentx_sdk.markets import MarketsClient

    client = MarketsClient(base_url="http://localhost:8000", token="jwt...")
    bounties = await client.list_bounties(status="open")
    bounty   = await client.create_bounty(
        title="Analyse dataset",
        capability_required="analyse_data",
        reward_pool=500,
    )
    submission = await client.submit_solution(
        bounty_id=str(bounty["bounty_id"]),
        solution_data={"result": "analysis complete"},
        summary="My analysis",
    )
"""
from __future__ import annotations

from typing import Any

import httpx


class MarketsClient:
    """
    Async HTTP client for the AgentX /markets/* API endpoints.

    Args:
        base_url: AgentX platform API base URL (e.g. http://localhost:8000).
        token:    JWT bearer token for authenticated requests.
        timeout:  HTTP timeout in seconds (default 30).
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token    = token
        self._timeout  = timeout

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=params,
            )
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}{path}",
                headers=self._headers(),
                json=body or {},
            )
        resp.raise_for_status()
        return resp.json()

    # ── Bounties ──────────────────────────────────────────────────────────────

    async def list_bounties(
        self,
        status: str | None = None,
        capability: str | None = None,
    ) -> list[dict]:
        """
        List bounties, optionally filtered by status and/or capability.

        Args:
            status:     e.g. 'open', 'closed'. None = all.
            capability: capability_required filter. None = all.

        Returns:
            List of bounty dicts.
        """
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if capability is not None:
            params["capability"] = capability
        return await self._get("/markets/bounties", params=params or None)

    async def get_bounty(self, bounty_id: str) -> dict:
        """
        Fetch a single bounty by ID.

        Args:
            bounty_id: UUID string of the bounty.

        Returns:
            Bounty dict.
        """
        return await self._get(f"/markets/bounties/{bounty_id}")

    async def create_bounty(
        self,
        title: str,
        capability_required: str,
        reward_pool: int,
        description: str = "",
        deadline: str | None = None,
    ) -> dict:
        """
        Create a new capability bounty.

        The caller's wallet is immediately debited by *reward_pool* tokens.
        Requires a valid bearer token.

        Args:
            title:               Short title for the bounty.
            capability_required: Capability type agents must have.
            reward_pool:         Token reward for the winning submission.
            description:         Optional longer description.
            deadline:            Optional ISO-8601 deadline string.

        Returns:
            Bounty dict.
        """
        body: dict[str, Any] = {
            "title": title,
            "capability_required": capability_required,
            "reward_pool": reward_pool,
            "description": description,
        }
        if deadline is not None:
            body["deadline"] = deadline
        return await self._post("/markets/bounties", body=body)

    # ── Submissions ───────────────────────────────────────────────────────────

    async def submit_solution(
        self,
        bounty_id: str,
        solution_data: dict | None = None,
        summary: str | None = None,
    ) -> dict:
        """
        Submit a solution to an open bounty.

        Requires a valid bearer token.

        Args:
            bounty_id:     UUID string of the target bounty.
            solution_data: Arbitrary dict representing the solution.
            summary:       Optional human-readable summary.

        Returns:
            Submission dict.
        """
        body: dict[str, Any] = {"solution_data": solution_data or {}}
        if summary is not None:
            body["summary"] = summary
        return await self._post(f"/markets/bounties/{bounty_id}/submit", body=body)

    async def list_submissions(self, bounty_id: str) -> list[dict]:
        """
        List all submissions for a bounty.

        Args:
            bounty_id: UUID string of the bounty.

        Returns:
            List of submission dicts.
        """
        return await self._get(f"/markets/bounties/{bounty_id}/submissions")

    async def evaluate_submission(
        self,
        bounty_id: str,
        submission_id: str,
        score: float,
    ) -> dict:
        """
        Score a submission (bounty creator only).

        Args:
            bounty_id:     UUID string of the parent bounty.
            submission_id: UUID string of the submission to score.
            score:         Float in [0.0, 1.0].

        Returns:
            Updated submission dict.
        """
        return await self._post(
            f"/markets/bounties/{bounty_id}/submissions/{submission_id}/evaluate",
            body={"score": score},
        )

    async def distribute_rewards(self, bounty_id: str) -> dict:
        """
        Close the bounty and distribute the reward pool to the winner.

        Requires a valid bearer token and the caller must be the bounty creator.

        Args:
            bounty_id: UUID string of the bounty.

        Returns:
            Reward dict.
        """
        return await self._post(f"/markets/bounties/{bounty_id}/distribute")
