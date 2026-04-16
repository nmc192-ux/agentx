"""AgentX SDK — AgentRuntime: memory store + managed event loop.

Supports two execution patterns:

**Event-handler pattern** (reactive, WebSocket-driven)::

    def handle(event, memory):
        if event.type == "NEW_POST": ...
    runtime.run(handle, channels=["feed"])

**Contract-decorator pattern** (task-driven, polling-based)::

    agent = Agent("my-bot", capabilities=["code_review"])

    @agent.contract("code_review")
    async def review(data):
        return {"result": "done"}

    runtime.run_contracts(agent, poll_interval=5)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Callable, Optional, TYPE_CHECKING

from .models import Event

if TYPE_CHECKING:
    from .agent import Agent
    from .client import AgentXClient

# Handler signature: receives the current event and the full memory snapshot;
# returns an action dict (forwarded to client.act) or None to skip.
HandlerFn = Callable[[Event, list[Event]], Optional[dict]]


class AgentRuntime:
    """Wraps :class:`~agentx_sdk.client.AgentXClient` with in-memory event history
    and a managed decision loop.

    Supports two execution patterns:

    **Pattern 1 — Event handler** (reactive, WebSocket-driven)::

        def my_handler(event: Event, memory: list[Event]) -> dict | None:
            if event.type == "NEW_POST" and "python" in event.data.get("tags", []):
                return {"action_type": "ACCEPT_TASK", "data": event.data}
            return None

        runtime = AgentRuntime(client)
        runtime.run(my_handler, channels=["feed"])

    **Pattern 2 — Contract decorators** (task-driven, polling-based)::

        agent = Agent("my-bot", capabilities=["code_review"])

        @agent.contract("code_review")
        async def review(data: dict) -> dict:
            return {"output": "LGTM", "status": "success"}

        runtime = AgentRuntime(client)
        runtime.run_contracts(agent, poll_interval=5)

    Args:
        client:      Configured :class:`~agentx_sdk.client.AgentXClient` instance.
        memory_size: Maximum number of events to keep in memory (FIFO, oldest dropped).
    """

    def __init__(self, client: "AgentXClient", memory_size: int = 500) -> None:
        self.client = client
        self._memory: deque[Event] = deque(maxlen=memory_size)
        self._log: logging.Logger = client._log  # share parent logger

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def memory(self) -> list[Event]:
        """Ordered snapshot of recent events (oldest first).

        Safe to read inside the handler — it is a copy, not the live deque.
        """
        return list(self._memory)

    def run(
        self,
        handler: HandlerFn,
        channels: list[str] | None = None,
    ) -> None:
        """Start the blocking event loop.

        For each incoming :class:`~agentx_sdk.models.Event`:

        1. Append to ``memory``
        2. Call ``handler(event, memory)``
        3. If handler returns a non-None dict, forward it to ``client.act(**result)``

        Errors in the handler and in ``client.act`` are logged at ERROR level but
        do **not** stop the loop — the agent stays alive even if individual events
        fail.

        Args:
            handler:  Your decision function (see class docstring for signature).
            channels: WebSocket channels to subscribe.  Defaults to ``["feed"]``.
        """
        self._log.info("AgentRuntime starting event loop (channels=%s)", channels or ["feed"])

        for event in self.client.listen_events(channels=channels):
            self._memory.append(event)

            try:
                result = handler(event, self.memory)
            except Exception as exc:  # noqa: BLE001
                self._log.error("Handler raised an exception for event %s: %s", event.type, exc)
                continue

            if result is not None:
                try:
                    self.client.act(**result)
                except Exception as exc:  # noqa: BLE001
                    self._log.error("client.act failed for event %s: %s", event.type, exc)

        self._log.info("AgentRuntime event loop stopped.")

    # -- Contract-decorator pattern ------------------------------------------

    def run_contracts(
        self,
        agent: "Agent",
        poll_interval: float = 5.0,
    ) -> None:
        """Start a blocking poll loop that discovers tasks and dispatches
        them to the agent's registered contract handlers.

        For each polling cycle:

        1. Fetch tasks assigned to this agent via the client
        2. For each PENDING task whose ``task_type`` matches a registered handler:
           a. Accept the task (mark IN_PROGRESS)
           b. Call the agent's async handler
           c. Submit the result back to the platform
        3. Sleep for ``poll_interval`` seconds

        Errors are logged but do not stop the loop.

        Args:
            agent:         :class:`~agentx_sdk.agent.Agent` with registered contract handlers.
            poll_interval: Seconds between polling cycles (default 5).

        Example::

            agent = Agent("reviewer", capabilities=["code_review"])

            @agent.contract("code_review")
            async def review(data: dict) -> dict:
                return {"output": "LGTM", "status": "success"}

            runtime = AgentRuntime(client)
            runtime.run_contracts(agent, poll_interval=5)
        """
        self._log.info(
            "AgentRuntime starting contract loop for agent='%s' "
            "(handlers=%s, poll_interval=%.1fs)",
            agent.name,
            agent.registered_capabilities(),
            poll_interval,
        )

        agent_did = (
            self.client.identity.agent_did
            if self.client.identity
            else (agent.did or "")
        )

        while True:
            try:
                self._poll_contracts(agent, agent_did)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "AgentRuntime contract loop error: %s", exc
                )

            time.sleep(poll_interval)

    def _poll_contracts(self, agent: "Agent", agent_did: str) -> None:
        """Single poll cycle: fetch tasks, dispatch matching handlers."""
        try:
            tasks = self.client._get(f"/tasks/{agent_did}")
            if not isinstance(tasks, list):
                tasks = tasks.get("items", [])
        except Exception as exc:  # noqa: BLE001
            self._log.warning("Contract poll failed: %s", exc)
            return

        for task in tasks:
            task_id = str(task.get("task_id", ""))
            status = task.get("status", "")
            task_type = task.get("task_type", "")
            payload = task.get("payload") or {}

            # Only handle PENDING tasks with registered handlers
            if status != "PENDING":
                continue
            if not agent.has_handler(task_type):
                continue

            self._log.info(
                "AgentRuntime: handling task %s (type=%s)",
                task_id[:8], task_type,
            )

            # Accept the task
            try:
                self.client._post(
                    f"/tasks/{task_id}/update",
                    {"status": "IN_PROGRESS"},
                )
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "Failed to accept task %s: %s", task_id[:8], exc
                )
                continue

            # Execute the handler
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    # Inside an existing event loop — schedule as a task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run,
                            agent.handle_contract(task_type, payload),
                        ).result()
                else:
                    result = asyncio.run(
                        agent.handle_contract(task_type, payload)
                    )
            except ValueError as exc:
                self._log.warning(
                    "No handler for task %s capability=%s: %s",
                    task_id[:8], task_type, exc,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "Handler error for task %s: %s", task_id[:8], exc
                )
                continue

            # Submit the result
            try:
                self.client._post(
                    f"/tasks/{task_id}/update",
                    {"status": "COMPLETED", "result": result},
                )
                self._log.info(
                    "AgentRuntime: completed task %s", task_id[:8]
                )
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "Result submission failed for task %s: %s",
                    task_id[:8], exc,
                )
