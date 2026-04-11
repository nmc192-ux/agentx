"""
AgentX Platform — Task & Contract Executor
══════════════════════════════════════════
Phase 8.5:  Synchronous task execution used by the worker process.
Phase 10:   Contract execution dispatched by contract_id.
Phase 11:   Agent Bus message consumption by worker processes.
Phase 19:   OpenTelemetry tracing added to all three execution paths.

execute_task(task)                runs a task payload and publishes TASK_VALUE_GENERATED.
execute_contract(contract)        runs a contract payload and publishes CONTRACT_COMPLETED.
execute_agentbus_message(message) processes an agent bus message and publishes
                                  AGENT_MESSAGE_RECEIVED.

Tracing:
    Each public function creates a root span named ``executor.<function>``.
    Attributes follow the AgentX semantic conventions:
      agentx.task.*       — task fields
      agentx.contract.*   — contract fields
      agentx.message.*    — message fields
      agentx.agent.did    — acting agent DID
    Exceptions are recorded on the span and re-raised; the span status is
    set to ERROR so alert rules can fire on error rate.
"""
from __future__ import annotations

import time
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from src.events.publisher import publish_event_sync

# ── Module-level tracer ───────────────────────────────────────────────────────
# get_tracer() is a no-op until setup_tracing() has been called from worker.py.
# This means executor.py is safe to import before the tracer provider is set.
tracer = trace.get_tracer(
    "agentx.workers.executor",
    schema_url="https://opentelemetry.io/schemas/1.25.0",
)


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Execute a task payload and publish TASK_VALUE_GENERATED.

    Args:
        task: dict containing at least:
              - task_id       (str UUID)
              - executor_did  (str, optional)
              - reward        (int, optional)
              - task_type     (str, optional)
              - payload       (dict, optional)

    Returns:
        dict with ``status`` and ``output`` fields.

    Raises:
        Exception: Any execution error is recorded as a span event and re-raised.
    """
    task_id      = str(task.get("task_id", ""))
    executor_did = task.get("executor_did") or task.get("agent_did", "")
    reward       = int(task.get("reward", 0))
    task_type    = task.get("task_type", "generic")

    with tracer.start_as_current_span(
        "executor.execute_task",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("agentx.task.id",       task_id)
        span.set_attribute("agentx.task.type",      task_type)
        span.set_attribute("agentx.task.reward",    reward)
        span.set_attribute("agentx.agent.did",      executor_did)

        t_start = time.monotonic()

        try:
            # ── Execution logic ──────────────────────────────────────────────
            # Dispatch by task_type; extend as new task types are added.
            result: dict[str, Any] = {"status": "worker_ok"}

            if task_type.startswith("nlp."):
                result["output"] = f"NLP result for task {task_id}"
            elif task_type.startswith("data."):
                result["output"] = f"Data result for task {task_id}"
            else:
                result["output"] = f"Generic result for task {task_id}"

            compute_time_ms = int((time.monotonic() - t_start) * 1000)
            span.set_attribute("agentx.task.compute_time_ms", compute_time_ms)

            # ── Publish TASK_VALUE_GENERATED ─────────────────────────────────
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

            span.set_status(StatusCode.OK)
            return result

        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


def execute_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Execute a contract payload and publish CONTRACT_COMPLETED.

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
        dict with ``status`` and ``output`` fields.

    Raises:
        Exception: Any execution error is recorded as a span event and re-raised.
    """
    contract_id    = str(contract.get("contract_id", ""))
    contractor_did = contract.get("contractor_did", "")
    budget         = int(contract.get("budget", 0))
    contract_type  = contract.get("contract_type", "general")

    with tracer.start_as_current_span(
        "executor.execute_contract",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("agentx.contract.id",     contract_id)
        span.set_attribute("agentx.contract.type",   contract_type)
        span.set_attribute("agentx.contract.budget", budget)
        span.set_attribute("agentx.agent.did",       contractor_did)

        t_start = time.monotonic()

        try:
            # ── Execution logic ──────────────────────────────────────────────
            result: dict[str, Any] = {"status": "worker_ok"}

            if contract_type.startswith("nlp."):
                result["output"] = f"NLP result for contract {contract_id}"
            elif contract_type.startswith("data."):
                result["output"] = f"Data result for contract {contract_id}"
            else:
                result["output"] = f"Contract {contract_id} executed"

            compute_time_ms = int((time.monotonic() - t_start) * 1000)
            span.set_attribute("agentx.contract.compute_time_ms", compute_time_ms)

            # ── Publish CONTRACT_COMPLETED ────────────────────────────────────
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

            span.set_status(StatusCode.OK)
            return result

        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


def execute_agentbus_message(message: dict[str, Any]) -> dict[str, Any]:
    """Process an agent bus message consumed by the worker process.

    Phase 11: Workers can consume agent bus messages from the queue,
    perform any required processing, and publish AGENT_MESSAGE_RECEIVED
    to acknowledge delivery.

    Args:
        message: dict containing at least:
                 - message_id   (str UUID)
                 - sender_did   (str, optional)
                 - receiver_did (str, optional)
                 - content      (str, optional)
                 - channel      (str, optional)

    Returns:
        dict with ``status`` and ``processed`` fields.

    Raises:
        Exception: Any processing error is recorded as a span event and re-raised.
    """
    message_id   = str(message.get("message_id", ""))
    sender_did   = message.get("sender_did", "")
    receiver_did = message.get("receiver_did", "")
    channel      = message.get("channel", "default")

    with tracer.start_as_current_span(
        "executor.execute_agentbus_message",
        kind=SpanKind.CONSUMER,
    ) as span:
        span.set_attribute("agentx.message.id",       message_id)
        span.set_attribute("agentx.message.channel",  channel)
        span.set_attribute("agentx.message.sender",   sender_did)
        span.set_attribute("agentx.message.receiver", receiver_did)
        # messaging.system semantic convention
        span.set_attribute("messaging.system",         "agentx-bus")
        span.set_attribute("messaging.destination",    channel)
        span.set_attribute("messaging.operation",      "receive")

        t_start = time.monotonic()

        try:
            # ── Processing logic ─────────────────────────────────────────────
            result: dict[str, Any] = {"status": "worker_ok", "processed": True}

            if channel.startswith("nlp."):
                result["output"] = f"NLP processing for message {message_id}"
            elif channel.startswith("data."):
                result["output"] = f"Data processing for message {message_id}"
            else:
                result["output"] = f"Message {message_id} delivered to {receiver_did}"

            compute_time_ms = int((time.monotonic() - t_start) * 1000)
            span.set_attribute("agentx.message.compute_time_ms", compute_time_ms)

            # ── Publish AGENT_MESSAGE_RECEIVED ───────────────────────────────
            publish_event_sync(
                "AGENT_MESSAGE_RECEIVED",
                {
                    "message_id":      message_id,
                    "sender_did":      sender_did,
                    "receiver_did":    receiver_did,
                    "channel":         channel,
                    "compute_time_ms": compute_time_ms,
                },
                source_agent_did=receiver_did or None,
            )

            span.set_status(StatusCode.OK)
            return result

        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
