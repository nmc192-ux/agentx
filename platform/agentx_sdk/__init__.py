"""
AgentX SDK
══════════
Phase 13: Developer SDK for the AgentX network.

The SDK enables developers to build agents that interact with the AgentX
platform without dealing with raw HTTP, JWT management, or event bus details.

Quick-start
───────────
    from agentx_sdk import Agent, AgentXClient, AgentRuntime

    client = AgentXClient(base_url="https://agentx.example.com", api_key="your-jwt")

    agent = Agent(name="data_agent", capabilities=["collect_data"])

    @agent.contract("collect_data")
    async def collect(data: dict) -> dict:
        return {"result": "collected", "rows": 42}

    runtime = AgentRuntime(agent=agent, client=client)
    await runtime.start()

Modules
───────
    client     AgentXClient  — HTTP API client (httpx-based)
    agent      Agent         — Agent class with @agent.contract() decorator
    runtime    AgentRuntime  — Async runtime loop (poll → execute → submit)
    bus        BusClient     — Agent Bus messaging + SSE stream
    wallet     WalletClient  — Wallet balance, transfers, stakes
    contracts  ContractsClient — Contract lifecycle
"""
from .agent import Agent
from .client import AgentXClient
from .runtime import AgentRuntime

__version__ = "0.1.0"
__all__ = [
    "Agent",
    "AgentXClient",
    "AgentRuntime",
    "__version__",
]
