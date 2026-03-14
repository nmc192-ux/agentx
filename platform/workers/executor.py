"""
AgentX Platform — Task Executor
═════════════════════════════════
Phase 8.5: Synchronous task execution used by the worker process.

execute_task(task) runs a task payload and, on completion, publishes a
TASK_VALUE_GENERATED event to the agentx.events Redis Stream via the
synchronous publisher (no async loop required in the worker).
"""
from __future__ import annotations

import time
from typing import Any

from src.events.publisher import publish_event_sync


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a task payload and publish TASK_VALUE_GENERATED.

    Args:
        task: dict containing at least:
              - task_id       (str UUID)
              - executor_did  (str, optional)
              - reward        (int, optional)
              - task_type     (str, optional)
              - payload       (dict, optional)

    Returns:
        dict with status and any result fields.
    """
    task_id      = str(task.get("task_id", ""))
    executor_did = task.get("executor_did") or task.get("agent_did", "")
    reward       = int(task.get("reward", 0))
    task_type    = task.get("task_type", "generic")

    t_start = time.monotonic()

    # ── Execution logic ──────────────────────────────────────────────────────
    # Dispatch by task_type; extend as new task types are added.
    result: dict[str, Any] = {"status": "worker_ok"}

    if task_type.startswith("nlp."):
        result["output"] = f"NLP result for task {task_id}"
    elif task_type.startswith("data."):
        result["output"] = f"Data result for task {task_id}"
    else:
        result["output"] = f"Generic result for task {task_id}"

    compute_time_ms = int((time.monotonic() - t_start) * 1000)

    # ── Publish TASK_VALUE_GENERATED ─────────────────────────────────────────
    publish_event_sync(
        "TASK_VALUE_GENERATED",
        {
            "task_id":          task_id,
            "executor":         executor_did,
            "reward":           reward,
            "compute_time_ms":  compute_time_ms,
            "task_type":        task_type,
        },
        source_agent_did=executor_did or None,
    )

    return result
