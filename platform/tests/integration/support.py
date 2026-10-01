"""
Shared helpers for the real-Postgres integration tests (fixtures are in
conftest.py). Sprint 9, S9-6a / S9-6b.
"""
from __future__ import annotations

from uuid import UUID

START_BALANCE = 1_000


class Agent:
    def __init__(self, did: str, agent_id: UUID, role: str):
        self.did, self.agent_id, self.role = did, agent_id, role

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Test-Caller": self.did}


async def balance(pool, agent: Agent) -> int | None:
    return await pool.fetchval("SELECT balance FROM wallets WHERE agent_id = $1", agent.agent_id)


async def total_tokens(pool) -> int:
    """Every token in existence: all wallets (treasury included) + task escrow
    + contract escrow."""
    return await pool.fetchval(
        """
        SELECT (SELECT COALESCE(SUM(balance), 0) FROM wallets)
             + (SELECT COALESCE(SUM(escrowed_reward), 0) FROM tasks)
             + (SELECT COALESCE(SUM(escrowed_budget), 0) FROM contracts)
        """
    )
