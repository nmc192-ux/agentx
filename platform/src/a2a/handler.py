"""AgentX Platform — A2A JSON-RPC method handlers.

Implements the server-side logic for A2A JSON-RPC methods:

  message/send  — Accept an inbound A2A message, create a platform task,
                  and return an A2ATask in the "submitted" state.
  tasks/get     — Retrieve a task by ID and return its current A2ATask status.

Both handlers translate between A2A protocol concepts and the existing
platform task_service, so external A2A clients (LangGraph, CrewAI, etc.)
can interoperate with AgentX without any changes to the core task system.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from ..database import get_db
from ..services import task_service
from .jsonrpc import (
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
    A2ATaskStatus,
    MessageSendParams,
    TasksGetParams,
)

logger = logging.getLogger(__name__)

# DID used when an external A2A caller has not authenticated.
_ANONYMOUS_DID = "did:agentx:a2a-external-001"


def _task_response_to_a2a(task_row) -> A2ATask:
    """Convert a platform TaskResponse to an A2ATask.

    Maps platform task states to A2A lifecycle states:
      open / pending → submitted
      in_progress    → working
      completed      → completed
      failed         → failed
      cancelled      → canceled
    """
    platform_status = str(getattr(task_row, "status", "open")).lower()
    state_map = {
        "open":        "submitted",
        "pending":     "submitted",
        "in_progress": "working",
        "assigned":    "working",
        "completed":   "completed",
        "failed":      "failed",
        "cancelled":   "canceled",
        "canceled":    "canceled",
    }
    a2a_state = state_map.get(platform_status, "submitted")

    task_id = str(getattr(task_row, "task_id", ""))

    # Build a status message summarising the task
    status_text = (
        f"Task {task_id} is {a2a_state}. "
        f"Type: {getattr(task_row, 'task_type', 'general')}. "
        f"Reward: {getattr(task_row, 'reward', 0)} AXP."
    )
    status_msg = A2AMessage(
        role="agent",
        parts=[A2APart(kind="text", text=status_text)],
    )

    # If completed, package the payload as an artifact
    artifacts: list[A2AArtifact] = []
    if a2a_state == "completed":
        payload = getattr(task_row, "payload", None) or {}
        artifacts.append(
            A2AArtifact(
                name="task_result",
                parts=[A2APart(kind="data", data=payload)],
            )
        )

    return A2ATask(
        id=task_id,
        status=A2ATaskStatus(
            state=a2a_state,
            message=status_msg,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        artifacts=artifacts,
        metadata={
            "task_type": getattr(task_row, "task_type", "general"),
            "reward":    getattr(task_row, "reward", 0),
            "created_at": str(getattr(task_row, "created_at", "")),
        },
    )


async def handle_message_send(params: dict) -> dict:
    """Handle an A2A ``message/send`` JSON-RPC call.

    Workflow:
      1. Parse params into MessageSendParams (validates A2A message structure)
      2. Extract the text content from the message parts
      3. Create a platform task via task_service.create_task()
      4. Return an A2ATask in the "submitted" state

    Args:
        params: Raw JSON-RPC params dict from the request.

    Returns:
        A2ATask serialised as a plain dict.

    Raises:
        ValueError: If params are malformed or task creation fails.
    """
    try:
        send_params = MessageSendParams(**params)
    except Exception as exc:
        raise ValueError(f"Invalid message/send params: {exc}") from exc

    message = send_params.message
    text_content = message.full_text() or "(no text)"

    # Determine task type from the message role / context
    task_type = "a2a_request"

    # Determine caller DID — from metadata if provided, else anonymous
    caller_did: str = (
        send_params.metadata.get("caller_did")
        or message.metadata.get("caller_did")  # type: ignore[attr-defined]
        if hasattr(message, "metadata")
        else _ANONYMOUS_DID
    )
    if not caller_did:
        caller_did = _ANONYMOUS_DID

    logger.info(
        "a2a: message/send from %s — task_type=%s text=%r",
        caller_did, task_type, text_content[:80],
    )

    task = await task_service.create_task(
        creator_agent_did=caller_did,
        task_type=task_type,
        payload={
            "a2a_message_id": message.messageId,
            "a2a_context_id": message.contextId,
            "text":           text_content,
            "parts":          [p.model_dump(exclude_none=True) for p in message.parts],
            "metadata":       send_params.metadata,
        },
        reward=0,   # external A2A tasks start with no reward
    )

    a2a_task = _task_response_to_a2a(task)

    # Wire the A2A contextId and taskId back through
    if message.contextId:
        a2a_task.contextId = message.contextId

    logger.info("a2a: created task %s for message %s", task.task_id, message.messageId)
    return a2a_task.model_dump(exclude_none=True)


async def handle_tasks_get(params: dict) -> dict:
    """Handle an A2A ``tasks/get`` JSON-RPC call.

    Fetches a platform task by its UUID and returns it as an A2ATask.

    Args:
        params: Raw JSON-RPC params dict; must contain ``id`` (task UUID).

    Returns:
        A2ATask serialised as a plain dict.

    Raises:
        ValueError: If ``id`` is missing, not a valid UUID, or task not found.
    """
    try:
        get_params = TasksGetParams(**params)
    except Exception as exc:
        raise ValueError(f"Invalid tasks/get params: {exc}") from exc

    try:
        task_id = UUID(get_params.id)
    except ValueError:
        raise ValueError(f"Invalid task ID (not a UUID): {get_params.id!r}")

    # Fetch directly from DB — task_service.list_tasks() doesn't support get-by-id
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT task_id, task_type, payload, reward, status, created_at
            FROM   tasks
            WHERE  task_id = $1
            """,
            task_id,
        )

    if row is None:
        raise ValueError(f"Task not found: {get_params.id}")

    # Wrap row in a namespace so _task_response_to_a2a can use getattr
    class _Row:
        def __init__(self, r):
            self.task_id   = r["task_id"]
            self.task_type = r["task_type"]
            self.payload   = r.get("payload") or {}
            self.reward    = r["reward"]
            self.status    = r["status"]
            self.created_at = r["created_at"]

    a2a_task = _task_response_to_a2a(_Row(row))

    # Optionally trim history (no history stored server-side yet)
    if get_params.historyLength is not None:
        a2a_task.history = a2a_task.history[: get_params.historyLength]

    return a2a_task.model_dump(exclude_none=True)
