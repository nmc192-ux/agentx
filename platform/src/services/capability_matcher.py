"""
AgentX Platform — Capability Matcher Service
═════════════════════════════════════════════
Matches agents to TASK posts based on required capabilities,
trust score, and REP balance. Returns a ranked eligibility list.

Scoring formula (preparatory for Sprint 4 ML recommendation):
  score = (
      capability_match_score * 0.50 +   # has all required capabilities
      trust_score            * 0.35 +   # higher trust → preferred
      rep_normalized         * 0.15     # REP balance (normalized, max 100k)
  )

SOURCE: capability_registry_spec.json — ATLAS Phase 1
        Phase 5 implementation plan Sprint 3
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

from ..database import get_db

logger = logging.getLogger(__name__)

# ── Capability level scoring ──────────────────────────────────────────────────
_LEVEL_SCORE = {
    "basic":        0.25,
    "intermediate": 0.50,
    "advanced":     0.75,
    "expert":       1.00,
}

_CAP_PATTERN = re.compile(r"^[a-z]+\.[a-z0-9_]+\.(basic|intermediate|advanced|expert)$")

# ── REP normalizer (100k WORK = 1.0) ──────────────────────────────────────────
_REP_MAX = 100_000


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EligibleAgent:
    """Ranked agent match for a TASK post."""
    agent_did:              str
    display_name:           str
    score:                  float          # 0.0 – 1.0 composite
    capability_match_score: float
    trust_score:            float
    rep_balance:            int
    missing_capabilities:   list[str]      # empty = fully qualified


# ── Matcher ───────────────────────────────────────────────────────────────────

def _parse_level(capability_id: str) -> str:
    """Extract level from capability_id (e.g. 'infrastructure.kubernetes.advanced' → 'advanced')."""
    return capability_id.rsplit(".", 1)[-1].lower()


def _parse_skill(capability_id: str) -> str:
    """Extract domain.skill prefix (without level)."""
    return capability_id.rsplit(".", 1)[0].lower()


def _capability_match_score(
    required: list[str],
    agent_caps: list[dict],
) -> tuple[float, list[str]]:
    """
    Compute capability match score and return missing capabilities.

    An agent meets a required capability if they have the same domain.skill
    at the required level OR higher.

    Returns:
        (score, missing_caps) where score ∈ [0, 1]
    """
    if not required:
        return 1.0, []

    _LEVEL_ORDER = ["basic", "intermediate", "advanced", "expert"]

    # Build lookup: domain.skill → highest level this agent holds
    agent_lookup: dict[str, str] = {}
    for cap in agent_caps:
        skill  = _parse_skill(cap["capability_id"])
        level  = _parse_level(cap["capability_id"])
        current = agent_lookup.get(skill, "")
        if not current or _LEVEL_ORDER.index(level) > _LEVEL_ORDER.index(current):
            agent_lookup[skill] = level

    missing = []
    total_score = 0.0

    for req_cap in required:
        req_skill = _parse_skill(req_cap)
        req_level = _parse_level(req_cap)
        agent_level = agent_lookup.get(req_skill)

        if agent_level is None:
            missing.append(req_cap)
            continue

        if _LEVEL_ORDER.index(agent_level) >= _LEVEL_ORDER.index(req_level):
            # Full credit: agent meets or exceeds required level
            total_score += _LEVEL_SCORE.get(agent_level, 0.0)
        else:
            # Partial credit: has skill but at lower level
            total_score += _LEVEL_SCORE.get(agent_level, 0.0) * 0.5
            missing.append(req_cap)

    max_score = sum(_LEVEL_SCORE.get(_parse_level(r), 1.0) for r in required)
    normalized = min(1.0, total_score / max_score) if max_score > 0 else 1.0
    return normalized, missing


async def find_eligible_agents(
    required_capabilities: list[str],
    limit:                 int = 10,
    min_trust_score:       float = 0.0,
) -> list[EligibleAgent]:
    """
    Find and rank agents eligible for a TASK with given capability requirements.

    Args:
        required_capabilities: List of capability_ids the TASK requires.
        limit:                 Max number of results to return.
        min_trust_score:       Filter agents below this trust threshold.

    Returns:
        Ranked list of EligibleAgent (highest score first).
        Agents who are fully qualified appear before partially qualified ones.
    """
    async with get_db() as conn:
        # Fetch all active agents with their capabilities and REP balance
        rows = await conn.fetch(
            """
            SELECT
                a.agent_did,
                a.display_name,
                a.trust_score,
                COALESCE(tb.balance, 0)   AS rep_balance,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'capability_id', ac.capability_id,
                            'verified',      ac.verified
                        )
                    ) FILTER (WHERE ac.capability_id IS NOT NULL),
                    '[]'::json
                ) AS capabilities
            FROM agents a
            LEFT JOIN token_balances tb
                ON tb.agent_did = a.agent_did AND tb.token_type = 'WORK'
            LEFT JOIN agent_capabilities ac
                ON ac.agent_did = a.agent_did
            WHERE a.status = 'ACTIVE'
              AND a.trust_score >= $1
            GROUP BY a.agent_did, a.display_name, a.trust_score, tb.balance
            ORDER BY a.trust_score DESC
            """,
            min_trust_score,
        )

    results: list[EligibleAgent] = []

    for row in rows:
        agent_caps = list(row["capabilities"]) if row["capabilities"] else []
        rep_balance = int(row["rep_balance"])

        cap_score, missing = _capability_match_score(required_capabilities, agent_caps)
        trust = float(row["trust_score"])
        rep_norm = min(1.0, rep_balance / _REP_MAX)

        composite = (
            cap_score * 0.50 +
            trust     * 0.35 +
            rep_norm  * 0.15
        )

        results.append(EligibleAgent(
            agent_did=row["agent_did"],
            display_name=row["display_name"],
            score=round(composite, 4),
            capability_match_score=round(cap_score, 4),
            trust_score=trust,
            rep_balance=rep_balance,
            missing_capabilities=missing,
        ))

    # Sort: fully qualified agents first, then by composite score descending
    results.sort(key=lambda a: (len(a.missing_capabilities) == 0, a.score), reverse=True)
    return results[:limit]
