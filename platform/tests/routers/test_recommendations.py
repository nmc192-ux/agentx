"""
Tests — Recommendation Endpoints (Sprint 4)
════════════════════════════════════════════
Verifies:
  GET /posts/similar?post_id={id}&limit=10
  GET /agents/{did}/recommended-tasks

Uses FastAPI dependency_overrides for clean auth mocking.
DB and ML service calls mocked via unittest.mock.patch.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.auth.jwt import create_access_token, TokenClaims
from src.auth.middleware import AgentRecord, get_current_agent


# ── Fixtures ──────────────────────────────────────────────────────────────────

AGENT_DID   = "did:agentx:nova-001"
TOKEN       = create_access_token(AGENT_DID, role="MEMBER", tier="STANDARD")
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}

SAMPLE_POST_ID  = uuid4()
SIMILAR_POST_ID = uuid4()


def _make_fake_agent(did=AGENT_DID, role="MEMBER") -> AgentRecord:
    """Build an AgentRecord for dependency override."""
    fake_claims = TokenClaims({
        "sub": did, "role": role, "tier": "STANDARD",
        "type": "access", "jti": "test-jti",
        "iat": 0, "exp": 9_999_999_999,
    })
    return AgentRecord(
        row={
            "agent_did":      did,
            "display_name":   "Nova",
            "governance_role": role,
            "tier":           "STANDARD",
            "trust_score":    0.75,
            "status":         "ACTIVE",
        },
        claims=fake_claims,
    )


@asynccontextmanager
async def _fake_get_db_exists():
    """Context manager that yields a mock connection where agent/post EXISTS."""
    conn = AsyncMock()
    conn.fetchval.return_value = AGENT_DID   # truthy → exists
    yield conn


@asynccontextmanager
async def _fake_get_db_not_found():
    """Context manager that yields a mock connection where agent/post NOT FOUND."""
    conn = AsyncMock()
    conn.fetchval.return_value = None
    yield conn


# ── GET /posts/similar ────────────────────────────────────────────────────────

class TestSimilarPosts:
    @pytest.mark.asyncio
    async def test_find_similar_returns_200(self):
        """Post exists + embedding available → 200 with similar posts."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 1

        mock_router = MagicMock()
        mock_router.get_post_embedding = AsyncMock(return_value=[0.1] * 384)
        mock_router.find_similar       = AsyncMock(return_value=[
            {"post_id": SIMILAR_POST_ID, "title": "Similar",
             "content": "content", "similarity": 0.92},
        ])

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        with patch("src.routers.posts.get_db", fake_get_db), \
             patch("src.routers.posts.semantic_router", mock_router):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/posts/similar?post_id={SAMPLE_POST_ID}&limit=10")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_find_similar_returns_correct_shape(self):
        """Response items must have post_id, title, content, similarity keys."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 1

        similar_pid = uuid4()
        mock_router = MagicMock()
        mock_router.get_post_embedding = AsyncMock(return_value=[0.1] * 384)
        mock_router.find_similar       = AsyncMock(return_value=[
            {"post_id": similar_pid, "title": "Task Alpha",
             "content": "Do alpha", "similarity": 0.88},
        ])

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        with patch("src.routers.posts.get_db", fake_get_db), \
             patch("src.routers.posts.semantic_router", mock_router):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/posts/similar?post_id={SAMPLE_POST_ID}")

        assert resp.status_code == 200
        data = resp.json()
        if data:
            item = data[0]
            assert "post_id"    in item
            assert "title"      in item
            assert "similarity" in item

    @pytest.mark.asyncio
    async def test_nonexistent_post_returns_404(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = None   # post does not exist

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        with patch("src.routers.posts.get_db", fake_get_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/posts/similar?post_id={uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_embedding_returns_empty_list(self):
        """Post exists but no embedding yet → 200 with empty list."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 1

        mock_router = MagicMock()
        mock_router.get_post_embedding = AsyncMock(return_value=None)

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        with patch("src.routers.posts.get_db", fake_get_db), \
             patch("src.routers.posts.semantic_router", mock_router):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/posts/similar?post_id={SAMPLE_POST_ID}")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_missing_post_id_returns_422(self):
        """post_id query param is required."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/posts/similar")
        assert resp.status_code == 422


# ── GET /agents/{did}/recommended-tasks ──────────────────────────────────────

class TestRecommendedTasks:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self):
        """No auth header → 401."""
        # Override dependency to require real auth so we can test unauthenticated
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/agents/{AGENT_DID}/recommended-tasks")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_agent_returns_404(self):
        """Known DID but agent not in DB → 404."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = None   # agent not found

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        fake_agent = _make_fake_agent()
        app.dependency_overrides[get_current_agent] = lambda: fake_agent

        with patch("src.routers.agents.get_db", fake_get_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/agents/{AGENT_DID}/recommended-tasks",
                    headers=AUTH_HEADER,
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_agent_tasks_returns_200_and_list(self):
        """Authenticated request for existing agent → 200 with task list."""
        from src.ml.task_recommender import RecommendedTask
        mock_recs = [
            RecommendedTask(
                post_id=uuid4(), title="Deploy k8s cluster", content="...",
                author_did="did:agentx:atlas-001",
                required_caps=["infrastructure.kubernetes.advanced"],
                content_score=0.9, collab_score=0.8, final_score=0.86,
                missing_caps=[],
            ),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = AGENT_DID   # agent exists

        mock_recommender = MagicMock()
        mock_recommender.get_recommendations = AsyncMock(return_value=mock_recs)

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        fake_agent = _make_fake_agent()
        app.dependency_overrides[get_current_agent] = lambda: fake_agent

        with patch("src.routers.agents.get_db", fake_get_db), \
             patch("src.routers.agents.task_recommender", mock_recommender):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/agents/{AGENT_DID}/recommended-tasks",
                    headers=AUTH_HEADER,
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_recommendations_respect_limit(self):
        """limit=2 → returns at most 2 tasks."""
        from src.ml.task_recommender import RecommendedTask
        mock_recs = [
            RecommendedTask(
                post_id=uuid4(), title=f"Task {i}", content="...",
                author_did="did:agentx:atlas-001", required_caps=[],
                content_score=0.5, collab_score=0.5, final_score=0.5, missing_caps=[],
            )
            for i in range(2)
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = AGENT_DID

        mock_recommender = MagicMock()
        mock_recommender.get_recommendations = AsyncMock(return_value=mock_recs)

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        fake_agent = _make_fake_agent()
        app.dependency_overrides[get_current_agent] = lambda: fake_agent

        with patch("src.routers.agents.get_db", fake_get_db), \
             patch("src.routers.agents.task_recommender", mock_recommender):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/agents/{AGENT_DID}/recommended-tasks?limit=2",
                    headers=AUTH_HEADER,
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    @pytest.mark.asyncio
    async def test_response_shape(self):
        """Response items must include final_score and required_caps."""
        from src.ml.task_recommender import RecommendedTask
        task_pid = uuid4()
        mock_recs = [
            RecommendedTask(
                post_id=task_pid, title="K8s Task", content="Deploy cluster",
                author_did="did:agentx:atlas-001",
                required_caps=["infrastructure.kubernetes.advanced"],
                content_score=0.9, collab_score=0.8, final_score=0.86,
                missing_caps=[],
            ),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = AGENT_DID

        mock_recommender = MagicMock()
        mock_recommender.get_recommendations = AsyncMock(return_value=mock_recs)

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        fake_agent = _make_fake_agent()
        app.dependency_overrides[get_current_agent] = lambda: fake_agent

        with patch("src.routers.agents.get_db", fake_get_db), \
             patch("src.routers.agents.task_recommender", mock_recommender):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/agents/{AGENT_DID}/recommended-tasks",
                    headers=AUTH_HEADER,
                )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        item = resp.json()[0]
        assert "post_id"      in item
        assert "final_score"  in item
        assert "required_caps" in item
