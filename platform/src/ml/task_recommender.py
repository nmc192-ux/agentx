"""
AgentX Platform — Task Recommendation Engine
══════════════════════════════════════════════
Hybrid content-based + collaborative filtering for personalised task feeds.

Algorithm:
  - Content score (0.6 weight): cosine similarity of agent capabilities vs task required skills
  - Collab score  (0.4 weight): domain-based co-completion similarity
  - Final score: 0.6 * content + 0.4 * collab

SOURCE: phase5_implementation_plan.md Sprint 4 — Task Recommender
"""
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# ── Weights ───────────────────────────────────────────────────────────────────

_CONTENT_WEIGHT = 0.6
_COLLAB_WEIGHT  = 0.4

# Capability level hierarchy (higher index = higher level)
_LEVEL_ORDER = ["basic", "intermediate", "advanced", "expert"]


# ── Output model ─────────────────────────────────────────────────────────────

@dataclass
class RecommendedTask:
    post_id:       UUID
    title:         str
    content:       str
    author_did:    str
    required_caps: list[str]
    content_score: float      # capability match component
    collab_score:  float      # collaborative component
    final_score:   float      # weighted hybrid score
    missing_caps:  list[str]  # capabilities the agent lacks


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_level(cap_id: str) -> str:
    """Extract level from capability ID like 'infra.kubernetes.advanced' → 'advanced'."""
    parts = cap_id.rsplit(".", 1)
    if len(parts) == 2 and parts[-1] in _LEVEL_ORDER:
        return parts[-1]
    return "basic"


def _parse_skill(cap_id: str) -> str:
    """Extract domain.skill from capability ID (strip level suffix)."""
    parts = cap_id.rsplit(".", 1)
    if len(parts) == 2 and parts[-1] in _LEVEL_ORDER:
        return parts[0]
    return cap_id


def _capability_content_score(
    required_caps: list[str],
    agent_caps: list[str],
) -> tuple[float, list[str]]:
    """
    Compute content-based capability match score.

    Returns:
        (score ∈ [0,1], missing_capabilities list)

    Scoring:
      - Exact or higher level match: full credit (1.0 per requirement)
      - Lower level match: partial credit (0.5 per requirement)
      - Missing: no credit
    """
    if not required_caps:
        return 1.0, []

    # Build lookup: skill → highest level agent has
    agent_skill_map: dict[str, int] = {}
    for cap in agent_caps:
        skill = _parse_skill(cap)
        level = _parse_level(cap)
        idx   = _LEVEL_ORDER.index(level) if level in _LEVEL_ORDER else 0
        if skill not in agent_skill_map or idx > agent_skill_map[skill]:
            agent_skill_map[skill] = idx

    total_credit = 0.0
    missing: list[str] = []

    for req in required_caps:
        req_skill = _parse_skill(req)
        req_level = _parse_level(req)
        req_idx   = _LEVEL_ORDER.index(req_level) if req_level in _LEVEL_ORDER else 0

        agent_idx = agent_skill_map.get(req_skill, -1)
        if agent_idx >= req_idx:
            total_credit += 1.0          # full match (same or higher)
        elif agent_idx >= 0:
            total_credit += 0.5          # partial match (lower level)
            missing.append(req)
        else:
            missing.append(req)          # capability missing entirely

    score = min(total_credit / len(required_caps), 1.0)
    return round(score, 4), missing


def _domain_of(cap_id: str) -> str:
    """Extract domain prefix: 'infrastructure.kubernetes.advanced' → 'infrastructure'."""
    return cap_id.split(".")[0] if cap_id else ""


def _collab_score_from_history(
    agent_domains: set[str],
    task_domains:  set[str],
    domain_scores: dict[str, float],
) -> float:
    """
    Simple domain-overlap collaborative score.

    Uses historical domain completion rates:
      - If agent has completed tasks in same domains → higher score
      - domain_scores: {domain → completion_rate} from past tasks
    """
    if not task_domains:
        return 0.5   # neutral

    overlap = agent_domains & task_domains
    if not overlap:
        return 0.2   # no domain overlap → low collaborative signal

    # Average completion rate for overlapping domains
    rates = [domain_scores.get(d, 0.3) for d in overlap]
    return round(sum(rates) / len(rates), 4)


# ── Recommender ───────────────────────────────────────────────────────────────

class TaskRecommender:
    """
    Personalised TASK post recommendations for a given agent.
    Fetches open TASKs from DB, scores each, returns top-N ranked list.
    """

    async def get_recommendations(
        self,
        agent_did: str,
        conn,
        limit: int = 5,
        min_trust_score: float = 0.0,
    ) -> list[RecommendedTask]:
        """
        Return up to `limit` recommended TASKs for the agent.

        Steps:
          1. Fetch agent capabilities from DB
          2. Fetch agent's past completed task domains (for collab score)
          3. Fetch open TASK posts matching min_trust_score
          4. Score each task (content + collab hybrid)
          5. Sort by final_score DESC, return top-N
        """
        # 1. Agent capabilities
        agent_caps = await self._fetch_agent_caps(agent_did, conn)

        # 2. Agent domain completion history
        domain_scores = await self._fetch_domain_history(agent_did, conn)
        agent_domains = set(domain_scores.keys())

        # 3. Open TASK posts
        task_rows = await self._fetch_open_tasks(conn, min_trust_score)

        # 4 & 5. Score and rank
        recommendations: list[RecommendedTask] = []
        for row in task_rows:
            required_caps = row.get("required_caps") or []
            content_score, missing = _capability_content_score(required_caps, agent_caps)

            task_domains  = {_domain_of(c) for c in required_caps if c}
            collab_score  = _collab_score_from_history(agent_domains, task_domains, domain_scores)
            final_score   = round(
                _CONTENT_WEIGHT * content_score + _COLLAB_WEIGHT * collab_score, 4
            )

            recommendations.append(RecommendedTask(
                post_id       = row["post_id"],
                title         = row["title"],
                content       = row["content"],
                author_did    = row["author_did"],
                required_caps = required_caps,
                content_score = content_score,
                collab_score  = collab_score,
                final_score   = final_score,
                missing_caps  = missing,
            ))

        recommendations.sort(key=lambda r: r.final_score, reverse=True)
        return recommendations[:limit]

    # ── DB helpers ────────────────────────────────────────────────────────────

    @staticmethod
    async def _fetch_agent_caps(agent_did: str, conn) -> list[str]:
        rows = await conn.fetch(
            """
            SELECT capability_id FROM agent_capabilities
            WHERE agent_did = $1
            """,
            agent_did,
        )
        return [r["capability_id"] for r in rows]

    @staticmethod
    async def _fetch_domain_history(agent_did: str, conn) -> dict[str, float]:
        """
        Build domain → completion rate map from agent's past closed tasks.
        Uses metadata JSONB to find required capabilities of completed tasks.
        """
        rows = await conn.fetch(
            """
            SELECT
                metadata->>'required_capabilities' AS caps_json
            FROM posts
            WHERE type = 'TASK'
              AND status = 'CLOSED'
              AND (metadata->>'assignee_did') = $1
            LIMIT 200
            """,
            agent_did,
        )
        domain_counts: dict[str, list[float]] = {}
        import json  # noqa: PLC0415
        for row in rows:
            caps_json = row["caps_json"]
            if not caps_json:
                continue
            try:
                caps = json.loads(caps_json) if isinstance(caps_json, str) else caps_json
                for cap in (caps or []):
                    domain = _domain_of(cap)
                    if domain:
                        domain_counts.setdefault(domain, []).append(1.0)
            except (ValueError, TypeError):
                continue

        # Return domain → average completion rate (1.0 since all are closed)
        return {d: 1.0 for d in domain_counts}

    @staticmethod
    async def _fetch_open_tasks(conn, min_trust_score: float) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT
                p.post_id, p.title, p.content, p.author_did,
                COALESCE(
                    ARRAY(
                        SELECT jsonb_array_elements_text(p.metadata->'required_capabilities')
                    ), ARRAY[]::TEXT[]
                ) AS required_caps
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE p.type = 'TASK'
              AND p.status = 'ACTIVE'
              AND p.visibility = 'PUBLIC'
              AND a.trust_score >= $1
            ORDER BY p.created_at DESC
            LIMIT 200
            """,
            min_trust_score,
        )
        return [dict(r) for r in rows]


# ── Singleton ─────────────────────────────────────────────────────────────────

task_recommender = TaskRecommender()
