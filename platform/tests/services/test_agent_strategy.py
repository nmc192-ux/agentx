"""
Tests: src/services/agent_strategy.py
Phase 19 — Autonomous Agent Economies

Covers all public functions:
  AgentStrategy enum
  STRATEGY_BEHAVIORS
  select_strategy()
  generate_work()
  hire_agents()
  evaluate_market()
  list_strategies()

Pure-Python service — no mocking required.
"""
from __future__ import annotations

import pytest

from src.services.agent_strategy import (
    STRATEGY_BEHAVIORS,
    AgentStrategy,
    evaluate_market,
    generate_work,
    hire_agents,
    list_strategies,
    select_strategy,
)


# ── AgentStrategy enum ────────────────────────────────────────────────────────

class TestAgentStrategyEnum:

    def test_has_specialist(self):
        assert AgentStrategy.specialist == "specialist"

    def test_has_generalist(self):
        assert AgentStrategy.generalist == "generalist"

    def test_has_coordinator(self):
        assert AgentStrategy.coordinator == "coordinator"

    def test_has_validator(self):
        assert AgentStrategy.validator == "validator"

    def test_is_string_enum(self):
        assert isinstance(AgentStrategy.specialist, str)

    def test_four_strategies_total(self):
        assert len(AgentStrategy) == 4


# ── STRATEGY_BEHAVIORS ────────────────────────────────────────────────────────

class TestStrategyBehaviors:

    def test_all_strategies_present(self):
        for s in AgentStrategy:
            assert s in STRATEGY_BEHAVIORS

    def test_coordinator_creates_bounties(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.coordinator]["creates_bounties"] is True

    def test_validator_evaluates_submissions(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.validator]["evaluates_submissions"] is True

    def test_specialist_does_not_create_bounties(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.specialist]["creates_bounties"] is False

    def test_generalist_does_not_evaluate(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.generalist]["evaluates_submissions"] is False

    def test_specialist_max_capabilities_is_one(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.specialist]["max_capabilities"] == 1

    def test_coordinator_prefers_matching_capability(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.coordinator]["prefers_matching_capability"] is True

    def test_generalist_does_not_prefer_matching(self):
        assert STRATEGY_BEHAVIORS[AgentStrategy.generalist]["prefers_matching_capability"] is False

    def test_all_behaviors_have_description(self):
        for s, b in STRATEGY_BEHAVIORS.items():
            assert "description" in b and len(b["description"]) > 0, f"Missing description for {s}"


# ── select_strategy() ─────────────────────────────────────────────────────────

class TestSelectStrategy:

    def test_zero_caps_returns_generalist(self):
        assert select_strategy("agent1", []) == AgentStrategy.generalist

    def test_one_cap_returns_specialist(self):
        assert select_strategy("agent1", ["forecast"]) == AgentStrategy.specialist

    def test_two_caps_returns_generalist(self):
        assert select_strategy("agent1", ["forecast", "research"]) == AgentStrategy.generalist

    def test_three_caps_returns_generalist(self):
        assert select_strategy("agent1", ["a", "b", "c"]) == AgentStrategy.generalist

    def test_four_caps_returns_coordinator(self):
        assert select_strategy("agent1", ["a", "b", "c", "d"]) == AgentStrategy.coordinator

    def test_five_caps_returns_coordinator(self):
        assert select_strategy("agent1", ["a", "b", "c", "d", "e"]) == AgentStrategy.coordinator

    def test_returns_agent_strategy_type(self):
        result = select_strategy("agent1", ["cap"])
        assert isinstance(result, AgentStrategy)

    def test_agent_id_does_not_affect_result(self):
        caps = ["forecast", "research"]
        assert select_strategy("alpha", caps) == select_strategy("beta", caps)


# ── generate_work() ───────────────────────────────────────────────────────────

class TestGenerateWork:

    def _call(self, strategy, capability="forecast", reward_pool=50):
        return generate_work(
            agent_id="agent123",
            strategy=strategy,
            capability=capability,
            reward_pool=reward_pool,
        )

    def test_returns_dict(self):
        result = self._call(AgentStrategy.specialist)
        assert isinstance(result, dict)

    def test_contains_agent_id(self):
        result = self._call(AgentStrategy.specialist)
        assert result["agent_id"] == "agent123"

    def test_contains_strategy(self):
        result = self._call(AgentStrategy.coordinator)
        assert result["strategy"] == "coordinator"

    def test_contains_capability(self):
        result = self._call(AgentStrategy.generalist, capability="analysis")
        assert result["capability"] == "analysis"

    def test_contains_title(self):
        result = self._call(AgentStrategy.specialist)
        assert "title" in result and len(result["title"]) > 0

    def test_contains_description(self):
        result = self._call(AgentStrategy.specialist)
        assert "description" in result and "agent123" in result["description"]

    def test_reward_pool_respected(self):
        result = self._call(AgentStrategy.generalist, reward_pool=75)
        assert result["reward_pool"] == 75

    def test_coordinator_priority_is_high(self):
        result = self._call(AgentStrategy.coordinator)
        assert result["priority"] == "high"

    def test_specialist_priority_is_normal(self):
        result = self._call(AgentStrategy.specialist)
        assert result["priority"] == "normal"

    def test_generalist_priority_is_normal(self):
        result = self._call(AgentStrategy.generalist)
        assert result["priority"] == "normal"

    def test_validator_priority_is_normal(self):
        result = self._call(AgentStrategy.validator)
        assert result["priority"] == "normal"

    def test_extra_kwargs_are_included(self):
        result = generate_work(
            "a", AgentStrategy.specialist, "forecast",
            reward_pool=10, extra={"custom": "value"}
        )
        assert result["custom"] == "value"

    def test_capability_appears_in_title(self):
        result = self._call(AgentStrategy.specialist, capability="sentiment_analysis")
        assert "sentiment_analysis" in result["title"]

    def test_all_strategies_produce_unique_titles(self):
        titles = {
            generate_work("a", s, "forecast")["title"]
            for s in AgentStrategy
        }
        assert len(titles) == len(AgentStrategy)


# ── hire_agents() ─────────────────────────────────────────────────────────────

class TestHireAgents:

    def _agents(self):
        return [
            {"did": "did:agentx:a1", "capabilities": ["forecast", "research"]},
            {"did": "did:agentx:a2", "capabilities": ["analysis"]},
            {"did": "did:agentx:a3", "capabilities": ["forecast"]},
            {"did": "did:agentx:a4", "capabilities": []},
        ]

    def test_returns_list(self):
        result = hire_agents("forecast", self._agents())
        assert isinstance(result, list)

    def test_returns_capable_agent_dids(self):
        result = hire_agents("forecast", self._agents())
        assert "did:agentx:a1" in result
        assert "did:agentx:a3" in result

    def test_excludes_incapable_agents(self):
        result = hire_agents("forecast", self._agents())
        assert "did:agentx:a2" not in result
        assert "did:agentx:a4" not in result

    def test_empty_agents_returns_empty(self):
        assert hire_agents("forecast", []) == []

    def test_no_matching_capability_returns_empty(self):
        result = hire_agents("unknown_cap", self._agents())
        assert result == []

    def test_all_agents_match_when_all_have_capability(self):
        agents = [
            {"did": f"did:{i}", "capabilities": ["forecast"]}
            for i in range(5)
        ]
        result = hire_agents("forecast", agents)
        assert len(result) == 5

    def test_agents_without_capabilities_key(self):
        agents = [{"did": "did:x"}]
        result = hire_agents("forecast", agents)
        assert result == []


# ── evaluate_market() ─────────────────────────────────────────────────────────

class TestEvaluateMarket:

    def _open_bounty(self, cap="forecast"):
        return {"status": "open", "capability_required": cap}

    def _closed_bounty(self):
        return {"status": "rewarded"}

    def _agent(self, *caps):
        return {"did": "did:x", "capabilities": list(caps)}

    def test_returns_dict(self):
        result = evaluate_market([], [])
        assert isinstance(result, dict)

    def test_total_bounties_counted(self):
        result = evaluate_market(
            [self._open_bounty(), self._closed_bounty()], []
        )
        assert result["total_bounties"] == 2

    def test_open_bounties_counted(self):
        result = evaluate_market(
            [self._open_bounty(), self._closed_bounty()], []
        )
        assert result["open_bounties"] == 1

    def test_total_agents_counted(self):
        result = evaluate_market([], [self._agent("a"), self._agent("b")])
        assert result["total_agents"] == 2

    def test_capability_supply_aggregated(self):
        agents = [self._agent("forecast"), self._agent("forecast", "research")]
        result = evaluate_market([], agents)
        assert result["capability_supply"]["forecast"] == 2
        assert result["capability_supply"]["research"] == 1

    def test_empty_market_health_is_empty(self):
        result = evaluate_market([], [])
        assert result["market_health"] == "empty"

    def test_no_open_bounties_health_is_idle(self):
        result = evaluate_market(
            [self._closed_bounty()],
            [self._agent("forecast")],
        )
        assert result["market_health"] == "idle"

    def test_healthy_market(self):
        agents = [self._agent("forecast")] * 5
        bounties = [self._open_bounty()]
        result = evaluate_market(bounties, agents)
        assert result["market_health"] == "healthy"

    def test_saturated_market(self):
        agents = [self._agent("forecast")]
        bounties = [self._open_bounty()] * 5
        result = evaluate_market(bounties, agents)
        assert result["market_health"] == "saturated"

    def test_recommended_capability_is_most_common(self):
        agents = [
            self._agent("forecast", "forecast"),
            self._agent("research"),
        ]
        result = evaluate_market([], agents)
        # forecast appears twice, research once
        assert result["recommended_capability"] == "forecast"

    def test_recommended_capability_none_when_no_agents(self):
        result = evaluate_market([], [])
        assert result["recommended_capability"] is None


# ── list_strategies() ─────────────────────────────────────────────────────────

class TestListStrategies:

    def test_returns_list(self):
        result = list_strategies()
        assert isinstance(result, list)

    def test_four_strategies_returned(self):
        result = list_strategies()
        assert len(result) == 4

    def test_each_has_name(self):
        for s in list_strategies():
            assert "name" in s

    def test_each_has_description(self):
        for s in list_strategies():
            assert "description" in s and s["description"]

    def test_each_has_creates_bounties(self):
        for s in list_strategies():
            assert "creates_bounties" in s

    def test_each_has_evaluates_submissions(self):
        for s in list_strategies():
            assert "evaluates_submissions" in s

    def test_strategy_names_are_valid(self):
        names = {s["name"] for s in list_strategies()}
        expected = {"specialist", "generalist", "coordinator", "validator"}
        assert names == expected
