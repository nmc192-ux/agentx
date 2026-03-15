"""
AgentX Platform — Task & Contract Executor
══════════════════════════════════════════
Phase 8.5:  Synchronous task execution used by the worker process.
Phase 10:   Contract execution dispatched by contract_id.

execute_task(task)         runs a task payload and publishes TASK_VALUE_GENERATED.
execute_contract(contract) runs a contract payload and publishes CONTRACT_COMPLETED.
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


def execute_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a contract payload and publish CONTRACT_COMPLETED.

    Phase 10 execution is a synchronous work-simulation step that publishes
    the CONTRACT_COMPLETED event via the synchronous Redis publisher so the
    worker process (which has no async event loop) can use it.

    Args:
        contract: dict containing at least:
                  - contract_id    (str UUID)
                  - contractor_did (str, optional)
                  - budget         (int, optional)
                  - contract_type  (str, optional)

    Returns:
        dict with status and output fields.
    """
    contract_id    = str(contract.get("contract_id", ""))
    contractor_did = contract.get("contractor_did", "")
    budget         = int(contract.get("budget", 0))
    contract_type  = contract.get("contract_type", "general")

    t_start = time.monotonic()

    # ── Execution logic ───────────────────────────────────────────────────────
    result: dict[str, Any] = {"status": "worker_ok"}

    if contract_type.startswith("nlp."):
        result["output"] = f"NLP result for contract {contract_id}"
    elif contract_type.startswith("data."):
        result["output"] = f"Data result for contract {contract_id}"
    else:
        result["output"] = f"Contract {contract_id} executed"

    compute_time_ms = int((time.monotonic() - t_start) * 1000)

    # ── Publish CONTRACT_COMPLETED ────────────────────────────────────────────
    publish_event_sync(
        "CONTRACT_COMPLETED",
        {
            "contract_id":     contract_id,
            "contractor":      contractor_did,
            "budget":          budget,
            "compute_time_ms": compute_time_ms,
            "contract_type":   contract_type,
        },
        source_agent_did=contractor_did or None,
    )

    return result
