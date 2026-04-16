"""
agentx_sdk — Agent class and contract decorator pattern tests.
"""
import asyncio

import pytest

from agentx_sdk import Agent


# -- Agent construction -------------------------------------------------------

class TestAgentInit:
    def test_basic_init(self):
        agent = Agent("my-bot", capabilities=["coding", "review"])
        assert agent.name == "my-bot"
        assert agent.capabilities == ["coding", "review"]
        assert agent.strategy == "AUTONOMOUS"
        assert agent.did is None
        assert agent.agent_id is None

    def test_custom_strategy(self):
        agent = Agent("bot", capabilities=[], strategy="SUPERVISED")
        assert agent.strategy == "SUPERVISED"

    def test_with_did(self):
        agent = Agent("bot", did="did:agentx:bot-001")
        assert agent.did == "did:agentx:bot-001"

    def test_default_capabilities(self):
        agent = Agent("bot")
        assert agent.capabilities == []

    def test_repr(self):
        agent = Agent("bot", capabilities=["x"])
        r = repr(agent)
        assert "bot" in r
        assert "Agent(" in r


# -- Contract decorator -------------------------------------------------------

class TestContractDecorator:
    def test_register_handler(self):
        agent = Agent("bot", capabilities=["review"])

        @agent.contract("review")
        async def handle_review(data):
            return {"result": "done"}

        assert agent.has_handler("review")
        assert "review" in agent.registered_capabilities()

    def test_multiple_handlers(self):
        agent = Agent("bot", capabilities=["review", "coding"])

        @agent.contract("review")
        async def handle_review(data):
            return {}

        @agent.contract("coding")
        async def handle_coding(data):
            return {}

        assert agent.has_handler("review")
        assert agent.has_handler("coding")
        assert len(agent.registered_capabilities()) == 2

    def test_stacked_decorators(self):
        agent = Agent("bot", capabilities=["review", "coding"])

        @agent.contract("review")
        @agent.contract("coding")
        async def handle_both(data):
            return {}

        assert agent.has_handler("review")
        assert agent.has_handler("coding")

    def test_sync_handler_raises(self):
        agent = Agent("bot")

        with pytest.raises(TypeError, match="must be async"):
            @agent.contract("review")
            def sync_handler(data):
                return {}

    def test_decorator_returns_function(self):
        agent = Agent("bot")

        @agent.contract("review")
        async def handle_review(data):
            return {"result": "ok"}

        # The decorated function should still be callable
        assert asyncio.iscoroutinefunction(handle_review)

    def test_has_handler_false(self):
        agent = Agent("bot")
        assert not agent.has_handler("nonexistent")


# -- handle_contract dispatch -------------------------------------------------

class TestHandleContract:
    def test_dispatch_returns_result(self):
        agent = Agent("bot")

        @agent.contract("review")
        async def handle_review(data):
            return {"output": data.get("input", "") + " reviewed"}

        result = asyncio.run(
            agent.handle_contract("review", {"input": "code"})
        )
        assert result == {"output": "code reviewed"}

    def test_dispatch_passes_data(self):
        agent = Agent("bot")
        received = {}

        @agent.contract("analyze")
        async def handle_analyze(data):
            received.update(data)
            return {"status": "ok"}

        asyncio.run(agent.handle_contract("analyze", {"key": "value"}))
        assert received == {"key": "value"}

    def test_dispatch_unknown_capability_raises(self):
        agent = Agent("bot")

        with pytest.raises(ValueError, match="no handler"):
            asyncio.run(agent.handle_contract("unknown", {}))

    def test_dispatch_handler_exception_propagates(self):
        agent = Agent("bot")

        @agent.contract("fail")
        async def handle_fail(data):
            raise RuntimeError("handler error")

        with pytest.raises(RuntimeError, match="handler error"):
            asyncio.run(agent.handle_contract("fail", {}))

    def test_handler_override(self):
        """Later registration for the same capability replaces the handler."""
        agent = Agent("bot")

        @agent.contract("review")
        async def handler_v1(data):
            return {"version": 1}

        @agent.contract("review")
        async def handler_v2(data):
            return {"version": 2}

        result = asyncio.run(agent.handle_contract("review", {}))
        assert result == {"version": 2}
