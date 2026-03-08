"""
Tests: Trust score service
Sprint 2 — services/trust_score.py

Coverage:
  - compute_composite() formula and bounds
  - get_trust_score() cache hit / miss paths
  - recalculate_trust_score() DB write + cache invalidation
  - Bootstrap score for new agents
  - Edge cases (all zeros, all ones, float precision)
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.trust_score import (
    TrustScore,
    compute_composite,
    get_trust_score,
    recalculate_trust_score,
    WEIGHT_EXECUTION_SUCCESS,
    WEIGHT_SLA_COMPLIANCE,
    WEIGHT_PEER_ENDORSEMENTS,
    WEIGHT_AUDIT_TRANSPARENCY,
    WEIGHT_SECURITY_RECORD,
)


# ── Weight sanity ─────────────────────────────────────────────────────────────

class TestWeights:
    """Module-level constants must be correct."""

    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_EXECUTION_SUCCESS +
            WEIGHT_SLA_COMPLIANCE   +
            WEIGHT_PEER_ENDORSEMENTS +
            WEIGHT_AUDIT_TRANSPARENCY +
            WEIGHT_SECURITY_RECORD
        )
        assert abs(total - 1.0) < 1e-9

    def test_execution_success_dominates(self):
        """execution_success (35%) is the largest single weight."""
        assert WEIGHT_EXECUTION_SUCCESS > WEIGHT_SLA_COMPLIANCE
        assert WEIGHT_EXECUTION_SUCCESS > WEIGHT_PEER_ENDORSEMENTS


# ── compute_composite ─────────────────────────────────────────────────────────

class TestComputeComposite:
    """compute_composite() applies the weighted formula correctly."""

    def test_all_zeros(self):
        result = compute_composite(0, 0, 0, 0, 0)
        assert result == 0.0

    def test_all_ones(self):
        result = compute_composite(1, 1, 1, 1, 1)
        assert result == 1.0

    def test_formula_correctness(self):
        """Manual calculation of a known input."""
        # 0.8*0.35 + 0.9*0.25 + 0.7*0.20 + 0.6*0.12 + 1.0*0.08
        # = 0.280 + 0.225 + 0.140 + 0.072 + 0.080
        # = 0.797
        result = compute_composite(
            execution_success=0.8,
            sla_compliance=0.9,
            peer_endorsements=0.7,
            audit_transparency=0.6,
            security_record=1.0,
        )
        assert abs(result - 0.80) < 0.01  # rounded to 2 decimal places

    def test_output_clamped_to_zero(self):
        """Negative input values are clamped to 0."""
        result = compute_composite(-1, -1, -1, -1, -1)
        assert result == 0.0

    def test_output_clamped_to_one(self):
        """Values > 1 are clamped to 1."""
        result = compute_composite(2, 2, 2, 2, 2)
        assert result == 1.0

    def test_result_rounded_to_2_decimals(self):
        result = compute_composite(0.333, 0.333, 0.333, 0.333, 0.333)
        # Result should be rounded to 2 decimal places
        assert result == round(result, 2)

    def test_partial_perfect_score(self):
        """High execution success pulls score up even with poor peer endorsements."""
        with_good_exec  = compute_composite(1.0, 0.5, 0.0, 0.5, 1.0)
        with_poor_exec  = compute_composite(0.0, 0.5, 0.0, 0.5, 1.0)
        assert with_good_exec > with_poor_exec

    def test_bounds_in_range(self):
        for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = compute_composite(val, val, val, val, val)
            assert 0.0 <= result <= 1.0


# ── get_trust_score ───────────────────────────────────────────────────────────

AGENT_DID = "did:agentx:atlas-001"

_SAMPLE_BREAKDOWN = {
    "execution_success":  0.95,
    "sla_compliance":     0.90,
    "peer_endorsements":  0.85,
    "audit_transparency": 0.80,
    "security_record":    1.00,
}

class TestGetTrustScore:
    """get_trust_score() reads from cache or DB."""

    @pytest.mark.asyncio
    async def test_returns_cached_score_on_hit(self):
        cached_data = {
            "agent_did":          AGENT_DID,
            "execution_success":  0.9,
            "sla_compliance":     0.85,
            "peer_endorsements":  0.8,
            "audit_transparency": 0.75,
            "security_record":    1.0,
            "composite":          0.87,
        }
        with patch("src.services.trust_score.cache_get", new=AsyncMock(return_value=cached_data)):
            result = await get_trust_score(AGENT_DID, use_cache=True)

        assert result.composite == 0.87
        assert result.execution_success == 0.9

    @pytest.mark.asyncio
    async def test_falls_back_to_db_on_cache_miss(self):
        with (
            patch("src.services.trust_score.cache_get",    new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",    new=AsyncMock()),
        ):
            result = await get_trust_score(AGENT_DID, use_cache=True)

        assert 0.0 <= result.composite <= 1.0
        assert result.agent_did == AGENT_DID

    @pytest.mark.asyncio
    async def test_returns_bootstrap_for_unknown_agent(self):
        """New agents with no breakdown record get bootstrap score."""
        with (
            patch("src.services.trust_score.cache_get",    new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=None)),
        ):
            result = await get_trust_score("did:agentx:new-001", use_cache=True)

        assert result.composite >= 0.0
        assert result.composite <= 1.0
        assert result.security_record == 1.0  # bootstrap has clean security record

    @pytest.mark.asyncio
    async def test_bypasses_cache_when_use_cache_false(self):
        with (
            patch("src.services.trust_score.cache_get",    new=AsyncMock()) as mock_cache_get,
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",    new=AsyncMock()),
        ):
            await get_trust_score(AGENT_DID, use_cache=False)

        mock_cache_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_to_cache_after_db_read(self):
        mock_cache_set = AsyncMock()
        with (
            patch("src.services.trust_score.cache_get",    new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",    new=mock_cache_set),
        ):
            await get_trust_score(AGENT_DID, use_cache=True)

        mock_cache_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_composite_in_bounds(self):
        with (
            patch("src.services.trust_score.cache_get",    new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",    new=AsyncMock()),
        ):
            result = await get_trust_score(AGENT_DID)

        assert 0.0 <= result.composite <= 1.0


# ── recalculate_trust_score ───────────────────────────────────────────────────

class TestRecalculateTrustScore:
    """recalculate_trust_score() invalidates cache and writes to DB."""

    @pytest.mark.asyncio
    async def test_invalidates_cache(self):
        mock_cache_delete = AsyncMock()
        with (
            patch("src.services.trust_score.cache_delete",  new=mock_cache_delete),
            patch("src.services.trust_score.cache_get",     new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",     new=AsyncMock()),
            patch("src.services.trust_score._update_composite_in_db", new=AsyncMock()),
        ):
            await recalculate_trust_score(AGENT_DID)

        mock_cache_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_writes_composite_to_db(self):
        mock_update = AsyncMock()
        with (
            patch("src.services.trust_score.cache_delete",  new=AsyncMock()),
            patch("src.services.trust_score.cache_get",     new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",     new=AsyncMock()),
            patch("src.services.trust_score._update_composite_in_db", new=mock_update),
        ):
            result = await recalculate_trust_score(AGENT_DID)

        mock_update.assert_called_once_with(AGENT_DID, result.composite)

    @pytest.mark.asyncio
    async def test_returns_trust_score_object(self):
        with (
            patch("src.services.trust_score.cache_delete",  new=AsyncMock()),
            patch("src.services.trust_score.cache_get",     new=AsyncMock(return_value=None)),
            patch("src.services.trust_score._fetch_breakdown_from_db", new=AsyncMock(return_value=_SAMPLE_BREAKDOWN)),
            patch("src.services.trust_score.cache_set",     new=AsyncMock()),
            patch("src.services.trust_score._update_composite_in_db", new=AsyncMock()),
        ):
            result = await recalculate_trust_score(AGENT_DID)

        assert isinstance(result, TrustScore)
        assert result.agent_did == AGENT_DID
