"""
AgentX Platform — Trust Score Service
═══════════════════════════════════════
Computes and caches the 5-factor composite trust score for agents.

Formula (SOURCE: agent_identity_schema_v3.json):
  score = (
      execution_success  * 0.35 +
      sla_compliance     * 0.25 +
      peer_endorsements  * 0.20 +
      audit_transparency * 0.12 +
      security_record    * 0.08
  )

Cache: Redis key "trust:<agent_did>", TTL = 5 minutes (TTL_AGENT_PROFILE).
Triggers: recalculate on task completion, SLA breach, endorsement, incident.

The trust_score column on the agents table is the canonical value.
agent_trust_breakdown holds the per-factor breakdown.
This service reads breakdown → computes composite → updates both.

MARCUS P1 Gap 3: Service uses system connection (no RLS) because
trust scores are computed by the platform, not by individual agents.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from ..cache import TTL_AGENT_PROFILE, cache_delete, cache_get, cache_set, trust_score_key
from ..database import get_db

logger = logging.getLogger(__name__)

# ── Weight constants (must sum to 1.0) ────────────────────────────────────────
WEIGHT_EXECUTION_SUCCESS  = 0.35
WEIGHT_SLA_COMPLIANCE     = 0.25
WEIGHT_PEER_ENDORSEMENTS  = 0.20
WEIGHT_AUDIT_TRANSPARENCY = 0.12
WEIGHT_SECURITY_RECORD    = 0.08

_WEIGHT_SUM = (
    WEIGHT_EXECUTION_SUCCESS + WEIGHT_SLA_COMPLIANCE + WEIGHT_PEER_ENDORSEMENTS
    + WEIGHT_AUDIT_TRANSPARENCY + WEIGHT_SECURITY_RECORD
)
assert abs(_WEIGHT_SUM - 1.0) < 1e-9, f"Trust score weights must sum to 1.0, got {_WEIGHT_SUM}"


# ── Trust score data class ────────────────────────────────────────────────────

@dataclass
class TrustScore:
    """Composite trust score with per-factor breakdown."""
    agent_did:          str
    execution_success:  float
    sla_compliance:     float
    peer_endorsements:  float
    audit_transparency: float
    security_record:    float
    composite:          float

    def to_dict(self) -> dict:
        return {
            "agent_did":          self.agent_did,
            "execution_success":  round(self.execution_success, 4),
            "sla_compliance":     round(self.sla_compliance, 4),
            "peer_endorsements":  round(self.peer_endorsements, 4),
            "audit_transparency": round(self.audit_transparency, 4),
            "security_record":    round(self.security_record, 4),
            "composite":          round(self.composite, 4),
        }


# ── Calculation ───────────────────────────────────────────────────────────────

def compute_composite(
    execution_success:  float,
    sla_compliance:     float,
    peer_endorsements:  float,
    audit_transparency: float,
    security_record:    float,
) -> float:
    """
    Apply the weighted formula to compute the composite trust score.

    All inputs must be in [0.0, 1.0].
    Returns a float in [0.0, 1.0].
    """
    raw = (
        execution_success  * WEIGHT_EXECUTION_SUCCESS  +
        sla_compliance     * WEIGHT_SLA_COMPLIANCE     +
        peer_endorsements  * WEIGHT_PEER_ENDORSEMENTS  +
        audit_transparency * WEIGHT_AUDIT_TRANSPARENCY +
        security_record    * WEIGHT_SECURITY_RECORD
    )
    # Clamp to [0, 1] and round to 2 decimal places (matches DB multipleOf: 0.01)
    return round(max(0.0, min(1.0, raw)), 2)


# ── Database queries ──────────────────────────────────────────────────────────

async def _fetch_breakdown_from_db(agent_did: str) -> Optional[dict]:
    """
    Read the agent_trust_breakdown row for the given agent.
    Returns None if no breakdown exists yet (new agent).
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                execution_success,
                sla_compliance,
                peer_endorsements,
                audit_transparency,
                security_record
            FROM agent_trust_breakdown
            WHERE agent_did = $1
            """,
            agent_did,
        )
    if row is None:
        return None
    breakdown = dict(row)
    return {key: float(value) for key, value in breakdown.items()}


async def _update_composite_in_db(agent_did: str, composite: float) -> None:
    """Write the computed composite score back to the agents table."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE agents SET trust_score = $1, updated_at = now() WHERE agent_did = $2",
            composite,
            agent_did,
        )


# ── Public API ────────────────────────────────────────────────────────────────

# Bootstrap trust score for new agents with no history
_BOOTSTRAP_SCORE = TrustScore(
    agent_did="",
    execution_success=0.5,
    sla_compliance=0.5,
    peer_endorsements=0.0,
    audit_transparency=0.5,
    security_record=1.0,
    composite=0.50,
)


async def get_trust_score(agent_did: str, use_cache: bool = True) -> TrustScore:
    """
    Get the trust score for an agent, with Redis caching.

    Args:
        agent_did:  The agent's DID.
        use_cache:  If False, skip Redis and go straight to DB.

    Returns:
        TrustScore dataclass (never raises — returns bootstrap for unknown agents).
    """
    key = trust_score_key(agent_did)

    # ── 1. Redis cache hit ────────────────────────────────────────────────────
    if use_cache:
        cached = await cache_get(key)
        if cached:
            return TrustScore(**cached)

    # ── 2. Database lookup ────────────────────────────────────────────────────
    breakdown = await _fetch_breakdown_from_db(agent_did)

    if breakdown is None:
        # New agent: return bootstrap score (don't cache — not persisted yet)
        logger.debug("No trust breakdown for %s — returning bootstrap score", agent_did)
        return TrustScore(agent_did=agent_did, **{
            k: v for k, v in vars(_BOOTSTRAP_SCORE).items() if k != "agent_did"
        })

    composite = compute_composite(**breakdown)
    score = TrustScore(agent_did=agent_did, composite=composite, **breakdown)

    # ── 3. Write to Redis (5-min TTL) ─────────────────────────────────────────
    await cache_set(key, score.to_dict(), ttl=TTL_AGENT_PROFILE)

    return score


async def recalculate_trust_score(agent_did: str) -> TrustScore:
    """
    Force-recalculate trust score: read DB → compute → update agents table → invalidate cache.

    Called after:
      - Task completion / failure
      - SLA breach
      - Peer endorsement / revocation
      - Security incident
    """
    logger.info("Recalculating trust score for %s", agent_did)

    # Invalidate cache first (so concurrent reads hit DB)
    await cache_delete(trust_score_key(agent_did))

    # Fetch fresh breakdown
    score = await get_trust_score(agent_did, use_cache=False)

    # Write composite back to agents table
    await _update_composite_in_db(agent_did, score.composite)

    logger.info("Trust score recalculated: %s → %.2f", agent_did, score.composite)
    return score
