"""
AgentX Platform — Agent Strategy Engine
════════════════════════════════════════
Phase 19: Autonomous Agent Economies.

Agents choose economic behaviour patterns (strategies) that govern how they
interact with the market: whether they create work, accept any contract,
evaluate others, or specialise deeply.

Public API
──────────
  select_strategy(agent_id, capabilities)       → AgentStrategy
  generate_work(agent_id, strategy, capability) → dict
  hire_agents(capability, available_agents)      → list[str]
  evaluate_market(bounties, agents)              → dict

Design notes
────────────
• Pure Python — no database calls.  All inputs come from callers.
• Strategies are additive; existing agents retain their behaviour.
• generate_work() returns a *proposal* dict, not a DB record.  Callers
  pass it to auto_bounty_service.create_agent_bounty() if they wish to
  persist it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


# ── Strategy definitions ──────────────────────────────────────────────────────


class AgentStrategy(str, Enum):
    """Economic behaviour pattern for a simulation agent."""

    specialist  = "specialist"   # Deep expertise in one capability
    generalist  = "generalist"   # Broad: accepts any contract
    coordinator = "coordinator"  # Creates bounties and delegates work
    validator   = "validator"    # Evaluates & scores submissions


# Per-strategy behaviour flags (informational; used by simulation engine)
STRATEGY_BEHAVIORS: dict[AgentStrategy, dict[str, Any]] = {
    AgentStrategy.specialist: {
        "max_capabilities":           1,
        "prefers_matching_capability": True,
        "creates_bounties":           False,
        "evaluates_submissions":      False,
        "description": (
            "Focuses on a single capability with deep expertise. "
            "Accepts only contracts that match its capability."
        ),
    },
    AgentStrategy.generalist: {
        "max_capabilities":           8,
        "prefers_matching_capability": False,
        "creates_bounties":           False,
        "evaluates_submissions":      False,
        "description": (
            "Accepts any contract regardless of capability. "
            "Prioritises volume over specialisation."
        ),
    },
    AgentStrategy.coordinator: {
        "max_capabilities":           3,
        "prefers_matching_capability": True,
        "creates_bounties":           True,
        "evaluates_submissions":      False,
        "description": (
            "Orchestrates work by creating bounties for other agents. "
            "Breaks large tasks into subtasks and delegates."
        ),
    },
    AgentStrategy.validator: {
        "max_capabilities":           2,
        "prefers_matching_capability": True,
        "creates_bounties":           False,
        "evaluates_submissions":      True,
        "description": (
            "Evaluates and scores submissions. "
            "Ensures quality in the market by acting as an impartial judge."
        ),
    },
}

# Work-generation title templates per strategy
_WORK_TITLES: dict[AgentStrategy, str] = {
    AgentStrategy.specialist:  "Specialist task: {capability} analysis required",
    AgentStrategy.coordinator: "Coordination task: delegate {capability} work",
    AgentStrategy.generalist:  "General task: {capability} service needed",
    AgentStrategy.validator:   "Validation task: review {capability} output",
}


# ── Public service functions ───────────────────────────────────────────────────


def select_strategy(
    agent_id: str,
    capabilities: list[str],
) -> AgentStrategy:
    """
    Select the most appropriate economic strategy for an agent based on its
    declared capabilities.

    Heuristic:
      • 0 capabilities → generalist (broadest possible acceptance)
      • 1 capability   → specialist (deep focus)
      • 2–3 caps       → generalist (moderate breadth)
      • 4+ caps        → coordinator (orchestrate others)

    Args:
        agent_id:     Agent identifier (used for logging / future ML).
        capabilities: List of the agent's declared capabilities.

    Returns:
        AgentStrategy enum value.
    """
    n = len(capabilities)
    if n == 0:
        return AgentStrategy.generalist
    if n == 1:
        return AgentStrategy.specialist
    if n >= 4:
        return AgentStrategy.coordinator
    return AgentStrategy.generalist


def generate_work(
    agent_id: str,
    strategy: AgentStrategy,
    capability: str,
    *,
    reward_pool: int = 50,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate a work-proposal dictionary based on the agent's strategy.

    The returned dict can be passed directly to
    ``auto_bounty_service.create_agent_bounty()`` to persist the work.

    Args:
        agent_id:    ID / DID of the proposing agent.
        strategy:    Economic strategy driving the proposal.
        capability:  Capability required to complete the work.
        reward_pool: Token reward for the winning solver (default 50).
        extra:       Optional additional metadata to embed in the proposal.

    Returns:
        Dict containing: agent_id, strategy, capability, title, description,
        reward_pool, priority, and any extra keys.
    """
    title = _WORK_TITLES.get(strategy, "Task: {capability}").format(
        capability=capability
    )
    description = (
        f"Autonomous work proposal from {agent_id} "
        f"using {strategy.value} strategy. "
        f"Capability required: {capability}."
    )
    priority = "high" if strategy == AgentStrategy.coordinator else "normal"

    proposal: dict[str, Any] = {
        "agent_id":    agent_id,
        "strategy":    strategy.value,
        "capability":  capability,
        "title":       title,
        "description": description,
        "reward_pool": reward_pool,
        "priority":    priority,
    }
    if extra:
        proposal.update(extra)
    return proposal


def hire_agents(
    capability: str,
    available_agents: list[dict[str, Any]],
) -> list[str]:
    """
    Filter available agents to those capable of performing *capability*.

    Args:
        capability:       The required capability string.
        available_agents: List of agent dicts, each with at least a "did"
                          key and a "capabilities" list.

    Returns:
        List of agent DIDs that possess the requested capability.
    """
    return [
        agent["did"]
        for agent in available_agents
        if capability in agent.get("capabilities", [])
    ]


def evaluate_market(
    bounties: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Produce a market-health assessment from current bounties and agents.

    Args:
        bounties: List of bounty dicts (at minimum: status,
                  capability_required).
        agents:   List of agent dicts (at minimum: capabilities list).

    Returns:
        Dict with keys:
          total_bounties, open_bounties, total_agents,
          capability_supply (cap→count), market_health, recommended_capability.
    """
    open_bounties = [b for b in bounties if b.get("status") == "open"]

    # Count how many agents offer each capability
    cap_counts: dict[str, int] = {}
    for agent in agents:
        for cap in agent.get("capabilities", []):
            cap_counts[cap] = cap_counts.get(cap, 0) + 1

    # Simple health heuristic: saturated if open bounties ≥ agent count
    if not agents:
        health = "empty"
    elif len(open_bounties) == 0:
        health = "idle"
    elif len(open_bounties) >= len(agents):
        health = "saturated"
    else:
        health = "healthy"

    recommended: str | None = (
        max(cap_counts, key=cap_counts.get) if cap_counts else None   # type: ignore[arg-type]
    )

    return {
        "total_bounties":       len(bounties),
        "open_bounties":        len(open_bounties),
        "total_agents":         len(agents),
        "capability_supply":    cap_counts,
        "market_health":        health,
        "recommended_capability": recommended,
    }


def list_strategies() -> list[dict[str, Any]]:
    """
    Return a list of strategy descriptors for API consumption.

    Returns:
        List of dicts with keys: name, description, creates_bounties,
        evaluates_submissions, max_capabilities, prefers_matching_capability.
    """
    result = []
    for strategy, behavior in STRATEGY_BEHAVIORS.items():
        result.append({
            "name":                        strategy.value,
            "description":                 behavior["description"],
            "creates_bounties":            behavior["creates_bounties"],
            "evaluates_submissions":       behavior["evaluates_submissions"],
            "max_capabilities":            behavior["max_capabilities"],
            "prefers_matching_capability": behavior["prefers_matching_capability"],
        })
    return result
