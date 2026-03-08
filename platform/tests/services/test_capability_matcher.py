"""
Tests: CapabilityMatcher — agent eligibility scoring
Sprint 3 — services/capability_matcher.py
"""
import pytest
from unittest.mock import AsyncMock, patch

from src.services.capability_matcher import (
    EligibleAgent,
    _capability_match_score,
    _parse_level,
    _parse_skill,
    find_eligible_agents,
)


# ── Helper parsers ────────────────────────────────────────────────────────────

class TestParsers:
    def test_parse_level_expert(self):
        assert _parse_level("infrastructure.kubernetes.expert") == "expert"

    def test_parse_level_basic(self):
        assert _parse_level("security.auth.basic") == "basic"

    def test_parse_skill(self):
        assert _parse_skill("infrastructure.kubernetes.advanced") == "infrastructure.kubernetes"

    def test_parse_skill_simple(self):
        assert _parse_skill("ml.training.intermediate") == "ml.training"


# ── Capability match scoring ──────────────────────────────────────────────────

class TestCapabilityMatchScore:
    """_capability_match_score() computes correct match scores."""

    def test_no_requirements_returns_full_score(self):
        score, missing = _capability_match_score([], [])
        assert score == 1.0
        assert missing == []

    def test_exact_match_returns_full_score(self):
        required   = ["infrastructure.kubernetes.advanced"]
        agent_caps = [{"capability_id": "infrastructure.kubernetes.advanced", "verified": True}]
        score, missing = _capability_match_score(required, agent_caps)
        assert score == 1.0
        assert missing == []

    def test_higher_level_counts_as_match(self):
        """Agent with EXPERT meets ADVANCED requirement."""
        required   = ["infrastructure.kubernetes.advanced"]
        agent_caps = [{"capability_id": "infrastructure.kubernetes.expert", "verified": True}]
        score, missing = _capability_match_score(required, agent_caps)
        assert score == 1.0
        assert missing == []

    def test_lower_level_gives_partial_credit(self):
        """Agent with BASIC when ADVANCED required → partial credit, listed as missing."""
        required   = ["infrastructure.kubernetes.advanced"]
        agent_caps = [{"capability_id": "infrastructure.kubernetes.basic", "verified": True}]
        score, missing = _capability_match_score(required, agent_caps)
        assert 0.0 < score < 1.0
        assert "infrastructure.kubernetes.advanced" in missing

    def test_missing_capability_adds_to_missing(self):
        required   = ["ml.training.expert"]
        agent_caps = [{"capability_id": "security.auth.basic", "verified": True}]
        score, missing = _capability_match_score(required, agent_caps)
        assert "ml.training.expert" in missing

    def test_partial_match_multiple_requirements(self):
        """Agent has 1 of 2 required caps."""
        required = [
            "infrastructure.kubernetes.advanced",
            "security.tls.intermediate",
        ]
        agent_caps = [{"capability_id": "infrastructure.kubernetes.expert", "verified": True}]
        score, missing = _capability_match_score(required, agent_caps)
        assert 0.0 < score < 1.0
        assert "security.tls.intermediate" in missing

    def test_score_bounded_to_one(self):
        required   = ["ml.training.basic"]
        agent_caps = [{"capability_id": "ml.training.expert", "verified": True}]
        score, _ = _capability_match_score(required, agent_caps)
        assert score <= 1.0

    def test_empty_agent_caps_all_missing(self):
        required = ["ml.training.expert", "data.pipeline.advanced"]
        score, missing = _capability_match_score(required, [])
        assert score == 0.0
        assert len(missing) == 2


# ── find_eligible_agents (mocked DB) ─────────────────────────────────────────

class TestFindEligibleAgents:
    """find_eligible_agents() queries DB and returns ranked list."""

    def _make_db_row(self, did: str, trust: float, rep: int, caps: list):
        import json
        return {
            "agent_did":    did,
            "display_name": did.split(":")[-1],
            "trust_score":  trust,
            "rep_balance":  rep,
            "capabilities": caps,
        }

    @pytest.mark.asyncio
    async def test_returns_eligible_agents(self):
        rows = [
            self._make_db_row(
                "did:agentx:atlas-001", 0.98, 50000,
                [{"capability_id": "infrastructure.kubernetes.expert", "verified": True}],
            ),
        ]
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = rows
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents(["infrastructure.kubernetes.advanced"], limit=5)

        assert len(results) == 1
        assert results[0].agent_did == "did:agentx:atlas-001"

    @pytest.mark.asyncio
    async def test_fully_qualified_agents_ranked_first(self):
        rows = [
            self._make_db_row(
                "did:agentx:partial-001", 0.9, 40000,
                [{"capability_id": "infrastructure.kubernetes.basic", "verified": False}],
            ),
            self._make_db_row(
                "did:agentx:full-001", 0.7, 30000,
                [{"capability_id": "infrastructure.kubernetes.expert", "verified": True}],
            ),
        ]
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = rows
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents(["infrastructure.kubernetes.advanced"])

        # fully-qualified agent should be first despite lower trust
        assert results[0].agent_did == "did:agentx:full-001"
        assert len(results[0].missing_capabilities) == 0

    @pytest.mark.asyncio
    async def test_no_requirements_all_agents_eligible(self):
        rows = [
            self._make_db_row("did:agentx:agent-001", 0.8, 10000, []),
            self._make_db_row("did:agentx:agent-002", 0.6, 5000, []),
        ]
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = rows
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents([])

        assert len(results) == 2
        for r in results:
            assert r.capability_match_score == 1.0
            assert len(r.missing_capabilities) == 0

    @pytest.mark.asyncio
    async def test_score_in_bounds(self):
        rows = [
            self._make_db_row(
                "did:agentx:agent-001", 0.75, 50000,
                [{"capability_id": "ml.training.advanced", "verified": True}],
            ),
        ]
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = rows
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents(["ml.training.intermediate"])

        assert 0.0 <= results[0].score <= 1.0

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self):
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents(["any.cap.basic"])

        assert results == []

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        rows = [
            self._make_db_row(f"did:agentx:agent-{i:03d}", 0.7, 10000, [])
            for i in range(10)
        ]
        with patch("src.services.capability_matcher.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = rows
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            results = await find_eligible_agents([], limit=3)

        assert len(results) == 3
