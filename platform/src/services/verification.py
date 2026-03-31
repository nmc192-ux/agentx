"""
AgentX Platform — Result Verification Service
═══════════════════════════════════════════════
Auto-verification of stale results and pending verification queries.

Prevents task creators from withholding payment indefinitely by
auto-approving results after a configurable timeout (default 72h).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from ..database import get_db, transaction
from ..services.reputation import record_event

logger = logging.getLogger(__name__)


async def auto_verify_stale_results(hours: int = 72) -> dict[str, int]:
    """
    Find task results older than `hours` hours still in 'pending' status
    and auto-approve them.

    Returns a summary dict with count of auto-verified results.
    """
    auto_verified = 0

    async with transaction() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tr.result_id,
                tr.task_id,
                tr.agent_id,
                a.agent_did
            FROM task_results tr
            JOIN agents a ON a.agent_id = tr.agent_id
            WHERE tr.verification_status = 'pending'
              AND tr.created_at < CURRENT_TIMESTAMP - make_interval(hours => $1)
            ORDER BY tr.created_at ASC
            """,
            hours,
        )

        for row in rows:
            await conn.execute(
                """
                UPDATE task_results
                SET
                    verification_status = 'auto_verified',
                    verified_at         = CURRENT_TIMESTAMP
                WHERE result_id = $1
                """,
                row["result_id"],
            )
            auto_verified += 1

    # Record trust events outside the transaction to avoid nested locks
    for row in rows:
        agent_did = row["agent_did"]
        try:
            await record_event(
                agent_did,
                "task_success",
                {
                    "task_id": str(row["task_id"]),
                    "verdict": "auto_verified",
                    "reason": f"Auto-verified after {hours}h without creator review",
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to record trust event for auto-verified result "
                "result_id=%s agent_did=%s: %s",
                row["result_id"],
                agent_did,
                exc,
            )

    if auto_verified > 0:
        logger.info("auto_verify_stale_results count=%d hours=%d", auto_verified, hours)

    return {"auto_verified": auto_verified}


async def get_pending_verifications(creator_did: str) -> list[dict]:
    """
    Return task results awaiting the creator's review.

    Finds all results in 'pending' status for tasks created by `creator_did`.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tr.result_id,
                tr.task_id,
                tr.agent_id,
                a.agent_did AS executor_did,
                tr.result_payload,
                tr.verification_status,
                tr.created_at
            FROM task_results tr
            JOIN tasks t ON t.task_id = tr.task_id
            JOIN agents a ON a.agent_id = tr.agent_id
            WHERE tr.verification_status = 'pending'
              AND t.requester_agent_did = $1
            ORDER BY tr.created_at ASC
            """,
            creator_did,
        )

    results = []
    for row in rows:
        payload = row["result_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        results.append({
            "result_id": str(row["result_id"]),
            "task_id": str(row["task_id"]),
            "agent_id": str(row["agent_id"]),
            "executor_did": row["executor_did"],
            "result_payload": payload or {},
            "verification_status": row["verification_status"],
            "created_at": row["created_at"].isoformat(),
        })

    return results
