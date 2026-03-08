"""
Tests — Task Recommender
═══════════════════════════
Verifies content-based filtering, collaborative scoring, hybrid ranking.
All DB calls are mocked.
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ml.task_recommender import (
    TaskRecommender,
    RecommendedTask,
    _capability_content_score,
    _collab_score_from_history,
    _parse_level,
    _parse_skill,
    _CONTENT_WEIGHT,
    _COLLAB_WEIGHT,
)


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestParsers:
    def test_parse_level_expert(self):
        assert _parse_level("infrastructure.kubernetes.expert") == "expert"

    def test_parse_level_basic(self):
        assert _parse_level("data.sql.basic") == "basic"

    def test_parse_level_unknown_defaults_basic(self):
        assert _parse_level("something.without.level_tag") == "basic"

    def test_parse_skill_full(self):
        assert _parse_skill("infrastructure.kubernetes.advanced") == "infrastructure.kubernetes"

    def test_parse_skill_simple(self):
        assert _parse_skill("data.sql.basic") == "data.sql"

    def test_parse_skill_no_level(self):
        # No valid level suffix → whole string is the skill
        assert _parse_skill("infrastructure.kubernetes") == "infrastructure.kubernetes"


# ── Content score tests ───────────────────────────────────────────────────────

class TestCapabilityContentScore:
    def test_no_requirements_returns_full_score(self):
        score, missing = _capability_content_score([], ["infra.k8s.expert"])
        assert score == 1.0
        assert missing == []

    def test_exact_match_returns_full_score(self):
        score, missing = _capability_content_score(
            ["infra.k8s.advanced"],
            ["infra.k8s.advanced"],
        )
        assert score == 1.0
        assert missing == []

    def test_higher_level_counts_as_match(self):
        """Agent with EXPERT satisfies ADVANCED requirement."""
        score, missing = _capability_content_score(
            ["infra.k8s.advanced"],
            ["infra.k8s.expert"],
        )
        assert score == 1.0
        assert missing == []

    def test_lower_level_gives_partial_credit(self):
        """Agent with BASIC satisfies ADVANCED requirement partially (0.5)."""
        score, missing = _capability_content_score(
            ["infra.k8s.advanced"],
            ["infra.k8s.basic"],
        )
        assert score == pytest.approx(0.5)
        assert len(missing) == 1

    def test_missing_capability_adds_to_missing(self):
        score, missing = _capability_content_score(
            ["infra.k8s.advanced", "data.ml.basic"],
            ["infra.k8s.expert"],
        )
        assert "data.ml.basic" in missing

    def test_partial_match_multiple_requirements(self):
        """2 requirements: 1 full match + 1 missing = 0.5 score."""
        score, missing = _capability_content_score(
            ["infra.k8s.advanced", "security.auth.basic"],
            ["infra.k8s.expert"],  # only has k8s
        )
        assert score == pytest.approx(0.5)
        assert "security.auth.basic" in missing

    def test_score_bounded_to_one(self):
        score, _ = _capability_content_score(
            ["a.b.basic"],
            ["a.b.expert", "a.b.advanced"],  # over-qualified
        )
        assert score <= 1.0

    def test_empty_agent_caps_all_missing(self):
        reqs   = ["infra.k8s.basic", "data.sql.basic"]
        score, missing = _capability_content_score(reqs, [])
        assert score == 0.0
        assert set(missing) == set(reqs)


# ── Collaborative score tests ─────────────────────────────────────────────────

class TestCollabScore:
    def test_no_overlap_returns_low_score(self):
        score = _collab_score_from_history(
            agent_domains={"marketing", "legal"},
            task_domains={"infrastructure", "security"},
            domain_scores={"marketing": 0.9, "legal": 0.8},
        )
        assert score == pytest.approx(0.2)

    def test_overlap_uses_agent_history(self):
        score = _collab_score_from_history(
            agent_domains={"infrastructure"},
            task_domains={"infrastructure"},
            domain_scores={"infrastructure": 0.9},
        )
        assert score == pytest.approx(0.9)

    def test_no_task_domains_neutral(self):
        score = _collab_score_from_history(set(), set(), {})
        assert score == pytest.approx(0.5)

    def test_multiple_overlapping_domains_averaged(self):
        score = _collab_score_from_history(
            agent_domains={"infra", "data"},
            task_domains={"infra", "data"},
            domain_scores={"infra": 1.0, "data": 0.6},
        )
        assert score == pytest.approx(0.8)


# ── Hybrid scoring tests ──────────────────────────────────────────────────────

class TestHybridScore:
    def test_weights_sum_to_one(self):
        assert _CONTENT_WEIGHT + _COLLAB_WEIGHT == pytest.approx(1.0)

    def test_hybrid_score_formula(self):
        content = 0.8
        collab  = 0.6
        expected = round(_CONTENT_WEIGHT * content + _COLLAB_WEIGHT * collab, 4)
        assert expected == pytest.approx(0.6 * 0.8 + 0.4 * 0.6)


# ── Full recommender tests ────────────────────────────────────────────────────

class TestRecommendations:
    def _make_task_row(self, required_caps=None, seed=1):
        return {
            "post_id":      uuid4(),
            "title":        f"Task {seed}",
            "content":      f"Do task {seed}",
            "author_did":   f"did:agentx:atlas-00{seed}",
            "required_caps": required_caps or [],
        }

    @pytest.mark.asyncio
    async def test_returns_top_5_by_default(self):
        recommender = TaskRecommender()
        tasks       = [self._make_task_row(seed=i) for i in range(10)]

        recommender._fetch_agent_caps   = AsyncMock(return_value=["infra.k8s.expert"])
        recommender._fetch_domain_history = AsyncMock(return_value={"infra": 1.0})
        recommender._fetch_open_tasks   = AsyncMock(return_value=tasks)

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:nova-001", conn, limit=5)
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        recommender = TaskRecommender()
        tasks       = [self._make_task_row(seed=i) for i in range(8)]

        recommender._fetch_agent_caps   = AsyncMock(return_value=[])
        recommender._fetch_domain_history = AsyncMock(return_value={})
        recommender._fetch_open_tasks   = AsyncMock(return_value=tasks)

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:nova-001", conn, limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_ranked_by_final_score_desc(self):
        recommender = TaskRecommender()
        tasks = [
            self._make_task_row(required_caps=["infra.k8s.expert"], seed=1),
            self._make_task_row(required_caps=["data.ml.basic"], seed=2),
            self._make_task_row(required_caps=[], seed=3),
        ]
        recommender._fetch_agent_caps   = AsyncMock(return_value=["infra.k8s.expert"])
        recommender._fetch_domain_history = AsyncMock(return_value={"infra": 1.0})
        recommender._fetch_open_tasks   = AsyncMock(return_value=tasks)

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:nova-001", conn, limit=10)
        scores = [r.final_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self):
        recommender = TaskRecommender()
        recommender._fetch_agent_caps   = AsyncMock(return_value=[])
        recommender._fetch_domain_history = AsyncMock(return_value={})
        recommender._fetch_open_tasks   = AsyncMock(return_value=[])

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:nova-001", conn)
        assert results == []

    @pytest.mark.asyncio
    async def test_content_score_in_result(self):
        recommender = TaskRecommender()
        task = self._make_task_row(required_caps=["infra.k8s.advanced"])
        recommender._fetch_agent_caps   = AsyncMock(return_value=["infra.k8s.expert"])
        recommender._fetch_domain_history = AsyncMock(return_value={"infra": 1.0})
        recommender._fetch_open_tasks   = AsyncMock(return_value=[task])

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:nova-001", conn)
        assert len(results) == 1
        assert results[0].content_score == 1.0   # expert meets advanced
        assert results[0].missing_caps == []

    @pytest.mark.asyncio
    async def test_kubernetes_agent_gets_k8s_task(self):
        """Agent with kubernetes capability should score high on k8s task."""
        recommender = TaskRecommender()
        k8s_task    = self._make_task_row(required_caps=["infrastructure.kubernetes.basic"])
        other_task  = self._make_task_row(required_caps=["data.ml.expert"])

        recommender._fetch_agent_caps   = AsyncMock(return_value=["infrastructure.kubernetes.advanced"])
        recommender._fetch_domain_history = AsyncMock(return_value={"infrastructure": 1.0})
        recommender._fetch_open_tasks   = AsyncMock(return_value=[k8s_task, other_task])

        conn = AsyncMock()
        results = await recommender.get_recommendations("did:agentx:marcus-001", conn)

        # k8s task should rank first
        assert results[0].post_id == k8s_task["post_id"]
        assert results[0].content_score == 1.0
