"""
Tests — Update Embeddings Job
══════════════════════════════
Verifies batch embedding logic: incremental processing, skip on existing,
error handling. Tests the async inner function directly (no Celery broker needed).
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_post_row(has_embedding=False):
    return {
        "post_id": uuid4(),
        "title":   "Deploy service to production",
        "content": "We need to deploy the new microservice to the AWS production cluster.",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestUpdateEmbeddingsJob:
    @pytest.mark.asyncio
    async def test_processes_posts_without_embeddings(self):
        """All posts returned by query (embedding IS NULL) should be embedded."""
        rows = [_make_post_row() for _ in range(5)]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = rows
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__  = AsyncMock(return_value=False)

        mock_embed_and_store = AsyncMock(return_value=[0.1] * 384)
        mock_router = MagicMock()
        mock_router.embed_and_store = mock_embed_and_store

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        from src.jobs import update_embeddings as job_module

        with patch.object(job_module, "get_db", fake_get_db), \
             patch.object(job_module, "semantic_router", mock_router):
            _run_update_embeddings = job_module._run_update_embeddings
            result = await _run_update_embeddings(lookback_hours=1, limit=100)

        assert result["processed"] == 5
        assert result["errors"]    == 0
        assert mock_embed_and_store.await_count == 5

    @pytest.mark.asyncio
    async def test_skips_when_model_unavailable(self):
        """When embed_and_store returns None (model unavailable), count as skipped."""
        rows = [_make_post_row() for _ in range(3)]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = rows
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__  = AsyncMock(return_value=False)

        mock_router = MagicMock()
        mock_router.embed_and_store = AsyncMock(return_value=None)  # model unavailable

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        from src.jobs import update_embeddings as job_module

        with patch.object(job_module, "get_db", fake_get_db), \
             patch.object(job_module, "semantic_router", mock_router):
            _run_update_embeddings = job_module._run_update_embeddings
            result = await _run_update_embeddings(lookback_hours=1, limit=100)

        assert result["processed"] == 0
        assert result["skipped"]   == 3
        assert result["errors"]    == 0

    @pytest.mark.asyncio
    async def test_batch_limit_respected(self):
        """Query must include LIMIT parameter from the limit arg."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []  # empty result
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__  = AsyncMock(return_value=False)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        mock_router = MagicMock()
        mock_router.embed_and_store = AsyncMock(return_value=None)

        from src.jobs import update_embeddings as job_module

        with patch.object(job_module, "get_db", fake_get_db), \
             patch.object(job_module, "semantic_router", mock_router):
            _run_update_embeddings = job_module._run_update_embeddings
            await _run_update_embeddings(lookback_hours=1, limit=25)

        # Verify the limit parameter was passed to the fetch query
        call_args = mock_conn.fetch.call_args
        assert 25 in call_args.args, "Limit=25 should appear in query args"

    @pytest.mark.asyncio
    async def test_errors_counted_not_raised(self):
        """Individual post embedding errors should be logged and counted, not re-raised."""
        rows = [_make_post_row() for _ in range(4)]

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = rows
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__  = AsyncMock(return_value=False)

        # First 2 succeed, last 2 raise
        side_effects = [[0.1]*384, [0.2]*384, Exception("DB error"), Exception("timeout")]
        mock_router  = MagicMock()
        mock_router.embed_and_store = AsyncMock(side_effect=side_effects)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        from src.jobs import update_embeddings as job_module

        with patch.object(job_module, "get_db", fake_get_db), \
             patch.object(job_module, "semantic_router", mock_router):
            _run_update_embeddings = job_module._run_update_embeddings
            result = await _run_update_embeddings(lookback_hours=1, limit=100)

        assert result["processed"] == 2
        assert result["errors"]    == 2

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_counts(self):
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__  = AsyncMock(return_value=False)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_get_db():
            yield mock_conn

        mock_router = MagicMock()
        from src.jobs import update_embeddings as job_module

        with patch.object(job_module, "get_db", fake_get_db), \
             patch.object(job_module, "semantic_router", mock_router):
            _run_update_embeddings = job_module._run_update_embeddings
            result = await _run_update_embeddings()

        assert result == {"processed": 0, "skipped": 0, "errors": 0}
