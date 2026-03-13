"""
Tests — Semantic Router
════════════════════════
Verifies embedding generation, pgvector similarity search, and Redis caching.
All external calls (SentenceTransformer, DB, Redis) are mocked.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ml.semantic_router import SemanticRouter, _embed_cache_key


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_router_state():
    """Reset SemanticRouter class-level model cache between tests."""
    orig_model     = SemanticRouter._model
    orig_available = SemanticRouter._model_available
    yield
    SemanticRouter._model          = orig_model
    SemanticRouter._model_available = orig_available


@pytest.fixture
def router():
    return SemanticRouter()


@pytest.fixture
def mock_model():
    """Fake SentenceTransformer that returns deterministic vectors."""
    m = MagicMock()
    class FakeVector(list):
        def tolist(self):
            return list(self)

    def _encode(text, normalize_embeddings=True):
        seed = sum(ord(c) for c in text) % 1000
        return FakeVector([float((seed + i) % 97) / 97.0 for i in range(384)])
    m.encode.side_effect = _encode
    return m


@pytest.fixture
def fake_pgvector():
    module = types.ModuleType("pgvector.asyncpg")
    module.register_vector = AsyncMock(return_value=None)
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.float32 = float
    fake_numpy.array = lambda values, dtype=None: values
    with patch.dict(sys.modules, {"pgvector.asyncpg": module, "numpy": fake_numpy}):
        yield module


# ── Embedding tests ───────────────────────────────────────────────────────────

class TestEmbedding:
    def test_same_text_same_embedding(self, router, mock_model):
        SemanticRouter._model          = mock_model
        SemanticRouter._model_available = True
        v1 = router.embed("hello world")
        v2 = router.embed("hello world")
        assert v1 == v2

    def test_different_text_different_embedding(self, router, mock_model):
        SemanticRouter._model          = mock_model
        SemanticRouter._model_available = True
        v1 = router.embed("kubernetes infrastructure")
        v2 = router.embed("machine learning prediction")
        assert v1 != v2

    def test_embed_returns_list_of_floats(self, router, mock_model):
        SemanticRouter._model          = mock_model
        SemanticRouter._model_available = True
        vec = router.embed("test text")
        assert isinstance(vec, list)
        assert len(vec) == 384
        assert all(isinstance(x, float) for x in vec)

    def test_embed_post_concatenates_title_and_content(self, router, mock_model):
        """embed_post(title, content) must produce same result as embed(title+' '+content)."""
        SemanticRouter._model          = mock_model
        SemanticRouter._model_available = True
        title   = "Deploy k8s cluster"
        content = "Need to deploy production kubernetes cluster on AWS"
        combined = router.embed(f"{title} {content}")
        from_post = router.embed_post(title, content)
        assert from_post == combined

    def test_embed_returns_none_when_model_unavailable(self, router):
        SemanticRouter._model          = None
        SemanticRouter._model_available = False
        result = router.embed("some text")
        assert result is None

    def test_is_available_true_when_model_loaded(self, router, mock_model):
        SemanticRouter._model          = mock_model
        SemanticRouter._model_available = True
        assert router.is_available() is True

    def test_is_available_false_when_no_model(self, router):
        SemanticRouter._model          = None
        SemanticRouter._model_available = False
        assert router.is_available() is False


# ── Similarity search tests ───────────────────────────────────────────────────

class TestSimilaritySearch:
    def _make_embedding(self, seed=42):
        return [float((seed + i) % 101) / 101.0 for i in range(384)]

    @pytest.mark.asyncio
    async def test_find_similar_returns_results(self, router, fake_pgvector):
        """find_similar returns list of dicts with similarity scores."""
        post_id         = uuid4()
        emb             = self._make_embedding()
        expected_result = [
            {"post_id": post_id, "title": "Similar Task", "content": "...", "similarity": 0.9},
        ]
        conn = AsyncMock()
        conn.fetch.return_value = expected_result

        results = await router.find_similar(conn, emb, limit=10)

        assert len(results) == 1
        assert results[0]["similarity"] == 0.9

    @pytest.mark.asyncio
    async def test_find_similar_respects_limit(self, router, fake_pgvector):
        rows = [
            {"post_id": uuid4(), "title": f"Task {i}", "content": "c", "similarity": 0.9 - i * 0.1}
            for i in range(5)
        ]
        conn = AsyncMock()
        conn.fetch.return_value = rows[:3]
        results = await router.find_similar(conn, self._make_embedding(), limit=3)
        assert len(results) == 3
        assert conn.fetch.await_args.args[-1] == 3

    @pytest.mark.asyncio
    async def test_find_similar_excludes_current_post(self, router, fake_pgvector):
        """Verify exclude_post_id parameter is passed through."""
        post_id = uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = []
        await router.find_similar(
            conn, self._make_embedding(), limit=10, exclude_post_id=post_id
        )
        assert conn.fetch.await_args.args[-2] == post_id


# ── Cache tests ───────────────────────────────────────────────────────────────

class TestCaching:
    def _make_embedding(self, seed=1):
        return [float((seed + i) % 89) / 89.0 for i in range(384)]

    @pytest.mark.asyncio
    async def test_cache_key_format(self):
        pid = uuid4()
        key = _embed_cache_key(pid)
        assert key == f"embed:{pid}"

    @pytest.mark.asyncio
    async def test_cache_stores_embedding(self, router):
        post_id  = uuid4()
        emb      = self._make_embedding()
        set_mock = AsyncMock()
        get_mock = AsyncMock(return_value=None)

        with patch("src.ml.semantic_router.cache_set", set_mock), \
             patch("src.ml.semantic_router.cache_get", get_mock):
            await router.cache_embedding(post_id, emb)

        set_mock.assert_awaited_once()
        call_kwargs = set_mock.await_args
        # Verify the key starts with "embed:"
        assert call_kwargs.args[0].startswith("embed:")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_embedding(self, router):
        post_id = uuid4()
        emb     = self._make_embedding(seed=7)

        get_mock = AsyncMock(return_value={"vec": emb})
        with patch("src.ml.semantic_router.cache_get", get_mock):
            result = await router.get_cached_embedding(post_id)

        assert result == emb

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, router):
        get_mock = AsyncMock(return_value=None)
        with patch("src.ml.semantic_router.cache_get", get_mock):
            result = await router.get_cached_embedding(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self, router):
        """When embedding is cached, DB should NOT be queried."""
        post_id = uuid4()
        emb     = self._make_embedding(seed=3)

        get_mock  = AsyncMock(return_value={"vec": emb})
        mock_conn = AsyncMock()

        with patch("src.ml.semantic_router.cache_get", get_mock):
            result = await router.get_post_embedding(post_id, mock_conn)

        assert result == emb
        mock_conn.fetchrow.assert_not_awaited()
