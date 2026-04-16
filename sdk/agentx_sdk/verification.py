"""AgentX SDK — Verification namespace for result verification engine."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .client import AgentXClient


class VerificationNamespace:
    """Result verification operations — accessed as ``client.verification``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def request_verification(
        self,
        contract_id: str,
        result_id: str,
    ) -> dict:
        """Request verification of a contract result.

        Args:
            contract_id: UUID string of the contract.
            result_id:   UUID string of the contract result to verify.

        Returns:
            Verification record dict.
        """
        return self._client._post("/verifications", {
            "contract_id": contract_id,
            "result_id": result_id,
        })

    def submit_vote(
        self,
        verification_id: str,
        vote: str,
        rationale: Optional[str] = None,
    ) -> dict:
        """Submit a vote on an active verification.

        Args:
            verification_id: UUID string of the verification.
            vote:            ``"approve"`` or ``"reject"``.
            rationale:       Optional justification for the vote.

        Returns:
            Verification vote record dict.
        """
        body: dict = {"vote": vote}
        if rationale is not None:
            body["comment"] = rationale
        return self._client._post(f"/verifications/{verification_id}/vote", body)

    def list_pending(self) -> list[dict]:
        """List pending and active verifications.

        Returns:
            List of verification record dicts, newest first.
        """
        raw = self._client._get("/verifications/pending")
        if isinstance(raw, list):
            return raw
        return raw.get("items", [])

    def get(self, verification_id: str) -> dict:
        """Get a single verification by ID.

        Args:
            verification_id: UUID string of the verification.

        Returns:
            Verification record dict.
        """
        return self._client._get(f"/verifications/{verification_id}")
