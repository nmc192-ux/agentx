"""AgentX SDK — Agent class with contract decorator pattern.

The ``Agent`` class provides a declarative way to define contract handlers
using Python decorators.  It works alongside the event-handler pattern —
choose whichever fits your use case:

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
from collections.abc import Callable, Coroutine
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Type alias for an async contract handler function.
ContractHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class Agent:
    """Represents an agent on the AgentX network with contract handlers.

    Attributes:
        name:         Human-readable name of the agent.
        capabilities: List of capability slugs this agent can fulfil.
        strategy:     Agent type (AUTONOMOUS, SUPERVISED, HYBRID).
        did:          Decentralised Identifier (set after registration).
        agent_id:     Platform UUID (set after registration).
    """

    def __init__(
        self,
        name: str,
        capabilities: Optional[list[str]] = None,
        strategy: str = "AUTONOMOUS",
        did: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        self.name = name
        self.capabilities = list(capabilities or [])
        self.strategy = strategy
        self.did = did
        self.agent_id = agent_id
        self._handlers: dict[str, ContractHandler] = {}

    # -- Decorator ------------------------------------------------------------

    def contract(self, capability: str) -> Callable[[ContractHandler], ContractHandler]:
        """Decorator that registers an async function as the handler for a capability.

        Can be stacked to register the same handler for multiple capabilities::

            @agent.contract("code_review")
            @agent.contract("refactoring")
            async def handle(data: dict) -> dict:
                return {"result": "done"}

        Args:
            capability: The capability slug (should match an advertised capability).

        Returns:
            A decorator that registers and returns the wrapped function.

        Raises:
            TypeError: If the handler is not an async callable.
        """
        def decorator(fn: ContractHandler) -> ContractHandler:
            if not callable(fn):
                raise TypeError(
                    f"@agent.contract handler must be callable, got {type(fn)}"
                )
            if not asyncio.iscoroutinefunction(fn):
                raise TypeError(
                    f"@agent.contract handler must be async "
                    f"(got sync function '{fn.__name__}')"
                )
            self._handlers[capability] = fn
            logger.debug(
                "Agent '%s': registered handler for capability '%s' -> %s",
                self.name, capability, fn.__name__,
            )
            return fn

        return decorator

    # -- Execution ------------------------------------------------------------

    async def handle_contract(
        self,
        capability: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the registered handler for the given capability.

        Args:
            capability: The capability slug to dispatch.
            data:       Contract/task payload forwarded to the handler.

        Returns:
            dict -- handler result to be submitted back to the platform.

        Raises:
            ValueError: No handler is registered for ``capability``.
        """
        handler = self._handlers.get(capability)
        if handler is None:
            raise ValueError(
                f"Agent '{self.name}' has no handler for capability '{capability}'. "
                f"Registered: {list(self._handlers.keys())}"
            )
        logger.debug(
            "Agent '%s': executing handler for capability '%s'",
            self.name, capability,
        )
        return await handler(data)

    # -- Introspection --------------------------------------------------------

    def registered_capabilities(self) -> list[str]:
        """Return the list of capabilities for which handlers are registered."""
        return list(self._handlers.keys())

    def has_handler(self, capability: str) -> bool:
        """Return True if a handler is registered for ``capability``."""
        return capability in self._handlers

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.name!r}, capabilities={self.capabilities!r}, "
            f"did={self.did!r}, handlers={list(self._handlers.keys())!r})"
        )
