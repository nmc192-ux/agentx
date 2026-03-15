"""
AgentX Simulation — Trust Network Simulation
═════════════════════════════════════════════
Phase 20: Agent Reputation Graph.

Simulates the formation and evolution of trust relationships between agents.
Supports three relationship archetypes:

  Alliance  — two agents with high positive interaction history
  Rivalry   — two agents with negative interactions (adversarial)
  TrustedTeam — a group of agents with strong mutual trust

Pure-Python; no real DB or network connections are required.  All interactions
are tracked in in-memory dicts, making this fully usable in tests.

Classes
───────
  TrustEdge                  — a lightweight in-memory edge record
  TrustNetworkSimulation     — simulates alliance/rivalry/team dynamics
  TrustNetworkEngine         — orchestrates multi-agent trust evolution

Usage::

    from simulation.trust_network_simulation import TrustNetworkEngine

    engine = TrustNetworkEngine(num_agents=10)
    await engine.run(cycles=5)
    summary = engine.summary()
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Interaction weights ────────────────────────────────────────────────────────

_WEIGHTS: dict[str, float] = {
    "task_completed":         0.10,
    "contract_completed":     0.12,
    "verification_submitted": 0.08,
    "rivalry":               -0.05,
    "alliance_bonus":         0.15,
    "general":                0.05,
}

_CLAMP_LO = 0.0
_CLAMP_HI = 1.0


def _clamp(value: float) -> float:
    return max(_CLAMP_LO, min(_CLAMP_HI, value))


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class TrustEdge:
    """In-memory directed trust edge between two simulated agents."""
    source: str
    target: str
    trust_weight: float = 0.0
    interaction_count: int = 0
    interaction_type: str = "general"

    def apply_delta(self, delta: float, itype: str = "general") -> None:
        self.trust_weight = _clamp(self.trust_weight + delta)
        self.interaction_count += 1
        self.interaction_type = itype

    def __repr__(self) -> str:
        return (
            f"TrustEdge({self.source!r} → {self.target!r} "
            f"w={self.trust_weight:.3f} n={self.interaction_count})"
        )


@dataclass
class Alliance:
    """Two agents with an ongoing positive-trust relationship."""
    agent_a: str
    agent_b: str
    strength: float = 0.0  # mean trust weight across both directions

    def __repr__(self) -> str:
        return f"Alliance({self.agent_a!r} ↔ {self.agent_b!r} strength={self.strength:.3f})"


@dataclass
class Rivalry:
    """Two agents whose interactions are adversarial."""
    agent_a: str
    agent_b: str
    intensity: float = 0.0  # mean negative-impact magnitude

    def __repr__(self) -> str:
        return f"Rivalry({self.agent_a!r} ↔ {self.agent_b!r} intensity={self.intensity:.3f})"


@dataclass
class TrustedTeam:
    """A group of agents with strong mutual trust (clique)."""
    members: list[str]
    avg_trust: float = 0.0

    def __repr__(self) -> str:
        return (
            f"TrustedTeam(members={self.members!r} "
            f"avg_trust={self.avg_trust:.3f})"
        )


# ── Core simulation ────────────────────────────────────────────────────────────

class TrustNetworkSimulation:
    """
    Simulates trust-edge evolution for a fixed set of agent IDs.

    Maintains an in-memory adjacency structure (source, target) → TrustEdge.
    Every cycle:
      1. Each alliance pair exchanges a positive interaction.
      2. Each rivalry pair exchanges a negative interaction.
      3. Each trusted-team member interacts with every other team member.
      4. A small number of random interactions are fired.
    """

    def __init__(
        self,
        agent_ids: list[str],
        alliances: list[tuple[str, str]] | None = None,
        rivalries: list[tuple[str, str]] | None = None,
        trusted_teams: list[list[str]] | None = None,
        cycle_interval: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.agent_ids: list[str] = list(agent_ids)
        self._alliances: list[tuple[str, str]] = list(alliances or [])
        self._rivalries: list[tuple[str, str]] = list(rivalries or [])
        self._trusted_teams: list[list[str]] = list(trusted_teams or [])
        self.cycle_interval = cycle_interval
        self._rng: random.Random = rng if rng is not None else random.Random()

        # (source, target) → TrustEdge
        self._edges: dict[tuple[str, str], TrustEdge] = {}

        self.cycles_run: int = 0
        self.total_interactions: int = 0
        self.is_running: bool = False

    # ── Edge helpers ──────────────────────────────────────────────────────────

    def _get_or_create(self, source: str, target: str) -> TrustEdge:
        key = (source, target)
        if key not in self._edges:
            self._edges[key] = TrustEdge(source=source, target=target)
        return self._edges[key]

    def _interact(self, source: str, target: str, delta: float, itype: str) -> None:
        if source == target:
            return
        edge = self._get_or_create(source, target)
        edge.apply_delta(delta, itype)
        self.total_interactions += 1

    def get_edge(self, source: str, target: str) -> TrustEdge | None:
        return self._edges.get((source, target))

    def get_trust_weight(self, source: str, target: str) -> float:
        edge = self._edges.get((source, target))
        return edge.trust_weight if edge else 0.0

    def all_edges(self) -> list[TrustEdge]:
        return list(self._edges.values())

    # ── Cycle ─────────────────────────────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one simulation cycle and return a stats dict."""
        interactions_before = self.total_interactions

        # 1. Alliance interactions (bidirectional positive)
        for a, b in self._alliances:
            w = _WEIGHTS["alliance_bonus"]
            self._interact(a, b, w, "alliance_bonus")
            self._interact(b, a, w, "alliance_bonus")

        # 2. Rivalry interactions (bidirectional negative)
        for a, b in self._rivalries:
            w = _WEIGHTS["rivalry"]
            self._interact(a, b, w, "rivalry")
            self._interact(b, a, w, "rivalry")

        # 3. Trusted-team interactions (all pairs, bidirectional)
        for team in self._trusted_teams:
            for i, a in enumerate(team):
                for b in team[i + 1 :]:
                    w = _WEIGHTS["task_completed"]
                    self._interact(a, b, w, "task_completed")
                    self._interact(b, a, w, "task_completed")

        # 4. Random interactions (2 per cycle if enough agents)
        if len(self.agent_ids) >= 2:
            for _ in range(2):
                a, b = self._rng.sample(self.agent_ids, 2)
                self._interact(a, b, _WEIGHTS["general"], "general")

        if self.cycle_interval > 0:
            await asyncio.sleep(self.cycle_interval)

        self.cycles_run += 1
        interactions_this_cycle = self.total_interactions - interactions_before

        return {
            "cycle": self.cycles_run,
            "interactions": interactions_this_cycle,
            "total_interactions": self.total_interactions,
            "edge_count": len(self._edges),
        }

    async def run(self, cycles: int = 10) -> None:
        """Run the simulation for *cycles* cycles."""
        self.is_running = True
        try:
            for _ in range(cycles):
                await self.run_cycle()
        finally:
            self.is_running = False

    # ── Analytics ─────────────────────────────────────────────────────────────

    def detect_alliances(self, threshold: float = 0.3) -> list[Alliance]:
        """Return pairs whose mean bidirectional trust exceeds *threshold*."""
        seen: set[frozenset[str]] = set()
        result: list[Alliance] = []
        for (a, b), edge in self._edges.items():
            key = frozenset([a, b])
            if key in seen:
                continue
            reverse = self._edges.get((b, a))
            if reverse is None:
                continue
            mean = (edge.trust_weight + reverse.trust_weight) / 2
            if mean >= threshold:
                seen.add(key)
                result.append(Alliance(agent_a=a, agent_b=b, strength=mean))
        return sorted(result, key=lambda x: x.strength, reverse=True)

    def detect_rivalries(self, threshold: float = 0.0) -> list[Rivalry]:
        """Return pairs that exchanged rivalry-type interactions."""
        seen: set[frozenset[str]] = set()
        result: list[Rivalry] = []
        for (a, b), edge in self._edges.items():
            if edge.interaction_type != "rivalry":
                continue
            key = frozenset([a, b])
            if key in seen:
                continue
            seen.add(key)
            reverse = self._edges.get((b, a))
            intensity = abs(edge.trust_weight - 0.5)
            if reverse:
                intensity = (abs(edge.trust_weight) + abs(reverse.trust_weight)) / 2
            result.append(Rivalry(agent_a=a, agent_b=b, intensity=intensity))
        return result

    def detect_trusted_teams(self, min_trust: float = 0.2, min_size: int = 2) -> list[TrustedTeam]:
        """Detect cliques where all pairs have trust ≥ *min_trust*."""
        # Build adjacency set
        high_trust: dict[str, set[str]] = {a: set() for a in self.agent_ids}
        for (a, b), edge in self._edges.items():
            if edge.trust_weight >= min_trust:
                high_trust.setdefault(a, set()).add(b)

        # Greedy clique extraction
        used: set[str] = set()
        teams: list[TrustedTeam] = []
        for agent in self.agent_ids:
            if agent in used:
                continue
            clique = [agent]
            for peer in sorted(high_trust.get(agent, [])):
                if peer in used:
                    continue
                # Check peer trusts all clique members
                if all(m in high_trust.get(peer, set()) for m in clique):
                    clique.append(peer)
            if len(clique) >= min_size:
                used.update(clique)
                # Compute avg trust within clique
                weights = []
                for i, a in enumerate(clique):
                    for b in clique[i + 1 :]:
                        e = self._edges.get((a, b))
                        if e:
                            weights.append(e.trust_weight)
                avg = sum(weights) / len(weights) if weights else 0.0
                teams.append(TrustedTeam(members=clique, avg_trust=avg))
        return teams

    def top_trusted_pairs(self, n: int = 5) -> list[TrustEdge]:
        """Return the *n* edges with the highest trust_weight."""
        return sorted(self._edges.values(), key=lambda e: e.trust_weight, reverse=True)[:n]

    def summary(self) -> dict[str, Any]:
        """Return a summary of the current simulation state."""
        weights = [e.trust_weight for e in self._edges.values()]
        return {
            "cycles_run": self.cycles_run,
            "total_interactions": self.total_interactions,
            "edge_count": len(self._edges),
            "agent_count": len(self.agent_ids),
            "alliance_count": len(self._alliances),
            "rivalry_count": len(self._rivalries),
            "team_count": len(self._trusted_teams),
            "avg_trust": round(sum(weights) / len(weights), 4) if weights else 0.0,
            "max_trust": round(max(weights), 4) if weights else 0.0,
            "min_trust": round(min(weights), 4) if weights else 0.0,
        }


# ── Orchestrating engine ───────────────────────────────────────────────────────

class TrustNetworkEngine:
    """
    High-level orchestrator that creates a TrustNetworkSimulation with
    auto-generated agent IDs and randomised alliances, rivalries and teams.

    Args:
        num_agents:       Number of simulated agents.
        alliance_ratio:   Fraction of agent pairs that form alliances (0–1).
        rivalry_ratio:    Fraction of agent pairs that form rivalries (0–1).
        team_size:        Size of each auto-generated trusted team.
        cycle_interval:   asyncio.sleep between cycles (0 in tests).
        seed:             Random seed for reproducibility (None = random).
    """

    def __init__(
        self,
        num_agents: int = 10,
        alliance_ratio: float = 0.2,
        rivalry_ratio: float = 0.1,
        team_size: int = 3,
        cycle_interval: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.num_agents = num_agents
        self.alliance_ratio = alliance_ratio
        self.rivalry_ratio = rivalry_ratio
        self.team_size = team_size
        self.cycle_interval = cycle_interval
        self._seed = seed
        self._rng = random.Random(seed)

        self._sim: TrustNetworkSimulation | None = None
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self.is_running: bool = False

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _build_agents(self) -> list[str]:
        return [f"trust_agent_{i + 1}" for i in range(self.num_agents)]

    def _build_alliances(self, agents: list[str]) -> list[tuple[str, str]]:
        if len(agents) < 2:
            return []
        pairs = [
            (agents[i], agents[j])
            for i in range(len(agents))
            for j in range(i + 1, len(agents))
        ]
        k = max(1, int(len(pairs) * self.alliance_ratio))
        return self._rng.sample(pairs, min(k, len(pairs)))

    def _build_rivalries(self, agents: list[str]) -> list[tuple[str, str]]:
        if len(agents) < 2:
            return []
        pairs = [
            (agents[i], agents[j])
            for i in range(len(agents))
            for j in range(i + 1, len(agents))
        ]
        k = max(1, int(len(pairs) * self.rivalry_ratio))
        return self._rng.sample(pairs, min(k, len(pairs)))

    def _build_teams(self, agents: list[str]) -> list[list[str]]:
        if len(agents) < self.team_size:
            return [agents[:]] if agents else []
        shuffled = agents[:]
        self._rng.shuffle(shuffled)
        teams = []
        for i in range(0, len(shuffled) - self.team_size + 1, self.team_size):
            teams.append(shuffled[i : i + self.team_size])
        return teams

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(self, cycles: int = 10) -> None:
        """Build the simulation, run it for *cycles* cycles, then stop."""
        agents = self._build_agents()
        # Derive a child RNG from the engine's seeded RNG so cycle-level
        # random interactions are also reproducible.
        child_rng = random.Random(self._rng.getrandbits(32))
        self._sim = TrustNetworkSimulation(
            agent_ids=agents,
            alliances=self._build_alliances(agents),
            rivalries=self._build_rivalries(agents),
            trusted_teams=self._build_teams(agents),
            cycle_interval=self.cycle_interval,
            rng=child_rng,
        )
        self.is_running = True
        try:
            await self._sim.run(cycles=cycles)
        finally:
            self.is_running = False

    async def start_background(self, cycles: int = 10) -> None:
        """Start the simulation as a background asyncio task."""
        self._task = asyncio.create_task(self.run(cycles=cycles))

    async def stop(self) -> None:
        """Cancel the background task if running."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.is_running = False

    # ── Analytics delegation ──────────────────────────────────────────────────

    @property
    def simulation(self) -> TrustNetworkSimulation | None:
        return self._sim

    def summary(self) -> dict[str, Any]:
        if self._sim is None:
            return {
                "cycles_run": 0,
                "total_interactions": 0,
                "edge_count": 0,
                "agent_count": 0,
                "alliance_count": 0,
                "rivalry_count": 0,
                "team_count": 0,
                "avg_trust": 0.0,
                "max_trust": 0.0,
                "min_trust": 0.0,
                "is_running": self.is_running,
            }
        s = self._sim.summary()
        s["is_running"] = self.is_running
        return s

    def detected_alliances(self, threshold: float = 0.3) -> list[Alliance]:
        if self._sim is None:
            return []
        return self._sim.detect_alliances(threshold)

    def detected_rivalries(self) -> list[Rivalry]:
        if self._sim is None:
            return []
        return self._sim.detect_rivalries()

    def detected_teams(self, min_trust: float = 0.2) -> list[TrustedTeam]:
        if self._sim is None:
            return []
        return self._sim.detect_trusted_teams(min_trust=min_trust)
