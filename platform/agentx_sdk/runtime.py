"""
AgentX SDK — Agent Runtime
═══════════════════════════
Phase 13: Developer SDK

``AgentRuntime`` is the execution engine that drives an ``Agent``:

  1. Registers the agent with the platform (idempotent — skips if already registered).
  2. Polls the API for contracts assigned to this agent.
  3. Dispatches assigned contracts to the agent's registered handlers.
  4. Submits handler results back to the platform.
  5. Handles verification requests when a submitted result is challenged.

Usage
─────
    agent = Agent(name="data_agent", capabilities=["collect_data"])

    @agent.contract("collect_data")
    async def collect(data: dict) -> dict:
        return {"rows": 42}

    client = AgentXClient(base_url="https://agentx.example.com", api_key="…")
    runtime = AgentRuntime(agent=agent, client=client)
    await runtime.start()

The runtime loop runs until cancelled (``asyncio.CancelledError``) or
``runtime.stop()`` is called.

Design notes
────────────
• Polling interval defaults to 5 seconds and is configurable.
• Result submission failures are logged but do not stop the runtime loop.
• ``stop()`` is safe to call from any coroutine including signal handlers.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .agent import Agent
from .client import AgentXClient

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    Async runtime that connects an Agent to the AgentX platform.

    Args:
        agent:            The configured Agent instance with registered handlers.
        client:           Authenticated AgentXClient instance.
        poll_interval:    Seconds between contract-polling cycles (default 5).
        auto_register:    If True, attempt to register the agent on start
                          (default True).
    """

    def __init__(
        self,
        agent: Agent,
        client: AgentXClient,
        *,
        poll_interval: float = 5.0,
        auto_register: bool = True,
    ) -> None:
        self.agent = agent
        self.client = client
        self.poll_interval = poll_interval
        self.auto_register = auto_register
        self._running = False
        self._task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the runtime loop.

        Registers the agent (if ``auto_register=True``) then enters the
        polling loop.  Runs until ``stop()`` is called or the coroutine is
        cancelled.
        """
        self._running = True
        logger.info("AgentRuntime: starting agent='%s'", self.agent.name)

        if self.auto_register:
            await self._register()

        await self._loop()

    async def stop(self) -> None:
        """Stop the runtime loop gracefully."""
        logger.info("AgentRuntime: stopping agent='%s'", self.agent.name)
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    # ── Registration ──────────────────────────────────────────────────────────

    async def _register(self) -> None:
        """
        Register the agent with the platform.

        Silently logs errors and continues — the agent may already be
        registered, or the platform may be temporarily unavailable.
        """
        if not self.agent.did:
            logger.warning(
                "AgentRuntime: agent.did is not set; skipping registration"
            )
            return

        try:
            result = await self.client.register_agent(
                name=self.agent.name,
                did=self.agent.did,
                capabilities=self.agent.capabilities,
            )
            self.agent.agent_id = result.get("agent_id")
            logger.info(
                "AgentRuntime: agent registered agent_id=%s did=%s",
                self.agent.agent_id, self.agent.did,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.debug("AgentRuntime: agent already registered (409)")
            else:
                logger.warning("AgentRuntime: registration failed: %s", exc)
        except Exception as exc:
            logger.warning("AgentRuntime: registration error: %s", exc)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Poll for assigned contracts and execute handlers."""
        while self._running:
            try:
                await self._poll_and_execute()
            except asyncio.CancelledError:
                logger.info("AgentRuntime: loop cancelled")
                raise
            except Exception as exc:
                logger.error("AgentRuntime: loop error: %s", exc)

            await asyncio.sleep(self.poll_interval)

    async def _poll_and_execute(self) -> None:
        """Fetch assigned contracts and execute handlers for each."""
        try:
            contracts = await self.client.list_contracts(status="assigned")
        except Exception as exc:
            logger.warning("AgentRuntime: contract poll failed: %s", exc)
            return

        agent_did = self.agent.did
        for contract in contracts:
            # Only handle contracts assigned to this agent
            if agent_did and contract.get("assigned_agent_did") != agent_did:
                continue
            await self._handle_contract(contract)

    async def _handle_contract(self, contract: dict[str, Any]) -> None:
        """
        Execute the contract handler and submit the result.

        Args:
            contract: Contract record dict from the platform API.
        """
        contract_id  = contract.get("contract_id")
        capability   = contract.get("capability_required", "")

        logger.info(
            "AgentRuntime: handling contract contract_id=%s capability=%s",
            contract_id, capability,
        )

        # Execute the handler
        try:
            result = await self.agent.handle_contract(capability, contract)
        except ValueError as exc:
            logger.warning(
                "AgentRuntime: no handler for contract_id=%s capability=%s: %s",
                contract_id, capability, exc,
            )
            return
        except Exception as exc:
            logger.error(
                "AgentRuntime: handler error contract_id=%s: %s",
                contract_id, exc,
            )
            return

        # Submit the result
        await self._submit_result(contract_id, result)

    async def _submit_result(
        self,
        contract_id: str | None,
        result: dict[str, Any],
    ) -> None:
        """Submit handler output to the platform."""
        if not contract_id:
            logger.warning("AgentRuntime: cannot submit result — no contract_id")
            return

        try:
            submitted = await self.client.submit_result(
                contract_id=contract_id,
                result_data=result,
                summary=result.get("summary"),
            )
            logger.info(
                "AgentRuntime: result submitted contract_id=%s result_id=%s",
                contract_id, submitted.get("result_id"),
            )
        except Exception as exc:
            logger.error(
                "AgentRuntime: result submission failed contract_id=%s: %s",
                contract_id, exc,
            )
