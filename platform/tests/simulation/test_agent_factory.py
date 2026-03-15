"""
Tests: simulation/agent_factory.py
Phase 18 — Multi-Agent Local Simulation

Covers:
  create_agent         — name, capabilities, handler registration
  create_agents        — batch creation, count, uniqueness
  AgentFactory         — stateful counter, configurable pool
  CAPABILITY_POOL      — default pool is non-empty
  Handler execution    — handlers actually return correct dicts
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from simulation.agent_factory import (
    CAPABILITY_POOL,
    AgentFactory,
    create_agent,
    create_agents,
    _make_handler,
)
from agentx_sdk import Agent


# ─────────────────────────────────────────────────────────────────────────────
# CAPABILITY_POOL
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityPool:

    def test_pool_is_non_empty(self):
        assert len(CAPABILITY_POOL) > 0

    def test_pool_contains_forecast(self):
        assert "forecast" in CAPABILITY_POOL

    def test_pool_contains_research(self):
        assert "research" in CAPABILITY_POOL

    def test_pool_all_strings(self):
        assert all(isinstance(c, str) for c in CAPABILITY_POOL)

    def test_pool_at_least_five(self):
        assert len(CAPABILITY_POOL) >= 5


# ─────────────────────────────────────────────────────────────────────────────
# _make_handler
# ─────────────────────────────────────────────────────────────────────────────

class TestMakeHandler:

    @pytest.mark.asyncio
    async def test_returns_coroutine(self):
        handler = _make_handler("forecast", "agent_1")
        result  = await handler({})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_result_contains_capability(self):
        handler = _make_handler("research", "agent_2")
        result  = await handler({})
        assert result["capability"] == "research"

    @pytest.mark.asyncio
    async def test_result_contains_agent_name(self):
        handler = _make_handler("analysis", "sim_agent_5")
        result  = await handler({})
        assert result["agent"] == "sim_agent_5"

    @pytest.mark.asyncio
    async def test_result_has_status_completed(self):
        handler = _make_handler("forecast", "x")
        result  = await handler({})
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_result_passes_input_keys(self):
        handler = _make_handler("forecast", "x")
        result  = await handler({"param1": 1, "param2": 2})
        assert "param1" in result["input_keys"]
        assert "param2" in result["input_keys"]

    def test_handlers_for_different_caps_are_distinct(self):
        h1 = _make_handler("cap_a", "agent")
        h2 = _make_handler("cap_b", "agent")
        assert h1 is not h2


# ─────────────────────────────────────────────────────────────────────────────
# create_agent
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateAgent:

    def test_returns_agent_instance(self):
        agent = create_agent(1)
        assert isinstance(agent, Agent)

    def test_name_is_sim_agent_index(self):
        agent = create_agent(7)
        assert agent.name == "sim_agent_7"

    def test_index_zero(self):
        agent = create_agent(0)
        assert agent.name == "sim_agent_0"

    def test_explicit_capabilities_used(self):
        agent = create_agent(1, capabilities=["forecast", "research"])
        assert "forecast"  in agent.capabilities
        assert "research"  in agent.capabilities

    def test_single_explicit_capability(self):
        agent = create_agent(1, capabilities=["analysis"])
        assert agent.capabilities == ["analysis"]

    def test_random_capabilities_when_none_given(self):
        agent = create_agent(2)
        assert len(agent.capabilities) >= 1

    def test_random_capabilities_from_pool(self):
        agent = create_agent(3)
        for cap in agent.capabilities:
            assert cap in CAPABILITY_POOL

    def test_handlers_registered_for_all_capabilities(self):
        agent = create_agent(1, capabilities=["forecast", "research"])
        # Agent.has_handler() should be True for each declared capability
        for cap in agent.capabilities:
            assert agent.has_handler(cap), f"No handler for capability '{cap}'"

    def test_registered_capabilities_match_declared(self):
        caps  = ["forecast", "translation"]
        agent = create_agent(4, capabilities=caps)
        for cap in caps:
            assert cap in agent.registered_capabilities()

    def test_different_indices_produce_different_names(self):
        a1 = create_agent(1)
        a2 = create_agent(2)
        assert a1.name != a2.name

    def test_custom_capability_pool(self):
        custom = ["alpha", "beta"]
        with patch("simulation.agent_factory.CAPABILITY_POOL", custom):
            agent = create_agent(1)
        for cap in agent.capabilities:
            assert cap in custom

    @pytest.mark.asyncio
    async def test_handler_returns_correct_capability(self):
        """Each handler must return its OWN capability, not the last loop value."""
        agent = create_agent(1, capabilities=["forecast", "research", "analysis"])
        for cap in agent.capabilities:
            result = await agent.handle_contract(cap, {})
            assert result["capability"] == cap, (
                f"Handler for '{cap}' returned wrong capability: {result['capability']}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# create_agents
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateAgents:

    def test_returns_correct_count(self):
        agents = create_agents(5)
        assert len(agents) == 5

    def test_returns_zero_agents(self):
        agents = create_agents(0)
        assert agents == []

    def test_agents_are_agent_instances(self):
        agents = create_agents(3)
        assert all(isinstance(a, Agent) for a in agents)

    def test_names_are_sequential(self):
        agents = create_agents(4)
        names  = [a.name for a in agents]
        assert names == ["sim_agent_1", "sim_agent_2", "sim_agent_3", "sim_agent_4"]

    def test_all_names_unique(self):
        agents = create_agents(10)
        names  = [a.name for a in agents]
        assert len(set(names)) == 10

    def test_all_have_at_least_one_capability(self):
        agents = create_agents(5)
        for a in agents:
            assert len(a.capabilities) >= 1

    def test_all_have_handlers(self):
        agents = create_agents(3)
        for a in agents:
            for cap in a.capabilities:
                assert a.has_handler(cap)

    def test_custom_pool_respected(self):
        pool   = ["only_cap"]
        agents = create_agents(3, capability_pool=pool)
        for a in agents:
            for cap in a.capabilities:
                assert cap == "only_cap"

    def test_min_max_caps_respected(self):
        agents = create_agents(20, min_caps=2, max_caps=2)
        for a in agents:
            assert len(a.capabilities) == 2


# ─────────────────────────────────────────────────────────────────────────────
# AgentFactory
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentFactory:

    def test_default_pool_used(self):
        factory = AgentFactory()
        agent   = factory.create()
        for cap in agent.capabilities:
            assert cap in CAPABILITY_POOL

    def test_custom_pool(self):
        factory = AgentFactory(capability_pool=["x", "y", "z"])
        agent   = factory.create()
        for cap in agent.capabilities:
            assert cap in ["x", "y", "z"]

    def test_counter_increments(self):
        factory = AgentFactory()
        a1 = factory.create()
        a2 = factory.create()
        assert a1.name == "sim_agent_1"
        assert a2.name == "sim_agent_2"

    def test_agents_created_property(self):
        factory = AgentFactory()
        factory.create_many(4)
        assert factory.agents_created == 4

    def test_reset_counter(self):
        factory = AgentFactory()
        factory.create_many(3)
        factory.reset()
        assert factory.agents_created == 0
        a = factory.create()
        assert a.name == "sim_agent_1"

    def test_create_many_count(self):
        factory = AgentFactory()
        agents  = factory.create_many(7)
        assert len(agents) == 7

    def test_create_many_sequential_names(self):
        factory = AgentFactory()
        agents  = factory.create_many(3)
        names   = [a.name for a in agents]
        assert names == ["sim_agent_1", "sim_agent_2", "sim_agent_3"]

    def test_consecutive_batches_have_unique_names(self):
        factory = AgentFactory()
        batch1  = factory.create_many(3)
        batch2  = factory.create_many(3)
        all_names = [a.name for a in batch1 + batch2]
        assert len(set(all_names)) == 6

    def test_explicit_capabilities_override_random(self):
        factory = AgentFactory()
        agent   = factory.create(capabilities=["alpha"])
        assert agent.capabilities == ["alpha"]

    def test_min_caps_one(self):
        factory = AgentFactory(min_caps=1, max_caps=1)
        agents  = factory.create_many(10)
        for a in agents:
            assert len(a.capabilities) == 1

    def test_create_returns_agent(self):
        factory = AgentFactory()
        assert isinstance(factory.create(), Agent)
