"""
AgentX SDK — Agent Class
═════════════════════════
Phase 13: Developer SDK

The ``Agent`` class is the primary developer interface.  It holds the
agent's identity, capabilities, and the registered contract handlers.

Usage
─────
    agent = Agent(name="data_agent", capabilities=["collect_data"])

    @agent.contract("collect_data")
    async def handle_collect(data: dict) -> dict:
        rows = await fetch_data()
        return {"rows": len(rows), "data": rows}

    # Later the runtime will call agent.handle_contract("collect_data", {...})

The ``@agent.contract`` decorator can also be stacked for agents that handle
multiple capabilities:

    @agent.contract("collect_data")
    @agent.contract("analyse_data")
    async def multi_handler(data: dict) -> dict:
        ...
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for an async contract handler function.
ContractHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class Agent:
    """
    Represents an agent on the AgentX network.

    Attributes:
        name:         Human-readable name of the agent.
        capabilities: List of capability slugs this agent can fulfil.
        did:          Decentralised Identifier (set after registration).
        agent_id:     Platform UUID (set after registration).
    """

    def __init__(
        self,
        name: str,
        capabilities: list[str],
        did: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.name = name
        self.capabilities = list(capabilities)
        self.did = did
        self.agent_id = agent_id
        self._handlers: dict[str, ContractHandler] = {}

    # ── Decorator ─────────────────────────────────────────────────────────────

    def contract(self, capability: str) -> Callable[[ContractHandler], ContractHandler]:
        """
        Decorator that registers an async function as the handler for a
        specific contract capability.

        Args:
            capability: The capability slug (must match what the agent advertises).

        Returns:
            A decorator that registers and returns the wrapped function.

        Example::

            @agent.contract("collect_data")
            async def handle_collect(data: dict) -> dict:
                return {"rows": 42}
        """
        def decorator(fn: ContractHandler) -> ContractHandler:
            if not callable(fn):
                raise TypeError(
                    f"@agent.contract handler must be callable, got {type(fn)}"
                )
            if not asyncio.iscoroutinefunction(fn):
                raise TypeError(
                    f"@agent.contract handler must be async (got sync function '{fn.__name__}')"
                )
            self._handlers[capability] = fn
            logger.debug(
                "Agent '%s': registered handler for capability '%s' → %s",
                self.name, capability, fn.__name__,
            )
            return fn

        return decorator

    # ── Execution ─────────────────────────────────────────────────────────────

    async def handle_contract(
        self,
        capability: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute the registered handler for the given capability.

        Args:
            capability: The capability slug to dispatch.
            data:       Contract payload forwarded to the handler.

        Returns:
            dict — handler result to be submitted back to the platform.

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

    # ── Introspection ─────────────────────────────────────────────────────────

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
