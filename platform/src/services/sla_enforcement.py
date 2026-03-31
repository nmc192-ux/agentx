"""
AgentX Platform — SLA Enforcement Service
══════════════════════════════════════════
Detects overdue tasks and applies penalties.

Default SLA: 24 hours from assignment to result submission.
Tasks exceeding the SLA window are flagged, and repeat offenders
receive REP token penalties via the token settlement engine.
"""
from __future__ import annotations

import logging

from ..database import get_db, transaction
from ..services.reputation import record_event

logger = logging.getLogger(__name__)

DEFAULT_SLA_HOURS = 24


async def check_overdue_tasks(sla_hours: int = DEFAULT_SLA_HOURS) -> dict:
    """
    Find assigned tasks that have exceeded the SLA deadline.

    For each overdue task:
      1. Mark the task as 'overdue'
      2. Record a trust penalty event for the executor

    Returns summary with count of newly flagged tasks.
    """
    flagged = 0

    async with transaction() as conn:
        rows = await conn.fetch(
            """
            SELECT
                ta.assignment_id,
                ta.task_id,
                ta.agent_id,
                a.agent_did,
                ta.started_at,
                EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ta.started_at)) / 3600
                    AS hours_elapsed
            FROM task_assignments ta
            JOIN agents a ON a.agent_id = ta.agent_id
            JOIN tasks t ON t.task_id = ta.task_id
            WHERE ta.status = 'assigned'
              AND t.status IN ('assigned', 'in_progress')
              AND ta.started_at < CURRENT_TIMESTAMP - make_interval(hours => $1)
            ORDER BY ta.started_at ASC
            """,
            sla_hours,
        )

        for row in rows:
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'overdue', updated_at = CURRENT_TIMESTAMP
                WHERE task_id = $1 AND status IN ('assigned', 'in_progress')
                """,
                row["task_id"],
            )
            flagged += 1

    # Record trust events outside transaction
    for row in rows:
        try:
            await record_event(
                row["agent_did"],
                "sla_violation",
                {
                    "task_id": str(row["task_id"]),
                    "hours_elapsed": round(row["hours_elapsed"], 1),
                    "sla_hours": sla_hours,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to record SLA violation event for %s: %s",
                row["agent_did"], exc,
            )

    if flagged:
        logger.info("SLA enforcement: flagged %d overdue tasks (sla=%dh)", flagged, sla_hours)

    return {"overdue_flagged": flagged, "sla_hours": sla_hours}


async def get_task_sla_status(task_id) -> dict:
    """Return SLA status for a specific task assignment."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                ta.assignment_id,
                ta.task_id,
                ta.agent_id,
                a.agent_did,
                ta.status,
                ta.started_at,
                ta.completed_at,
                EXTRACT(EPOCH FROM (
                    COALESCE(ta.completed_at, CURRENT_TIMESTAMP) - ta.started_at
                )) / 3600 AS hours_elapsed
            FROM task_assignments ta
            JOIN agents a ON a.agent_id = ta.agent_id
            WHERE ta.task_id = $1
            ORDER BY ta.started_at DESC
            LIMIT 1
            """,
            task_id,
        )

    if row is None:
        return {"task_id": str(task_id), "assigned": False}

    hours = round(float(row["hours_elapsed"]), 2) if row["hours_elapsed"] else 0
    return {
        "task_id": str(row["task_id"]),
        "assigned": True,
        "agent_did": row["agent_did"],
        "status": row["status"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "hours_elapsed": hours,
        "sla_hours": DEFAULT_SLA_HOURS,
        "overdue": hours > DEFAULT_SLA_HOURS and row["status"] == "assigned",
    }
