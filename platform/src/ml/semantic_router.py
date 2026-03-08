"""
AgentX Platform — Semantic Post Router
═══════════════════════════════════════
Embedding-based similarity search for posts using Sentence-BERT.

Features:
  - Lazy-loaded SentenceTransformer (all-MiniLM-L6-v2, 384-dim)
  - pgvector cosine similarity queries
  - Redis embedding cache (1-hour TTL)
  - Graceful degradation if model unavailable

SOURCE: phase5_implementation_plan.md Sprint 4 — Semantic Post Router
"""
import logging
from typing import Optional
from uuid import UUID

from ..cache import cache_delete, cache_get, cache_set

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM   = 384
TTL_EMBEDDING   = 3600  # 1 hour


def _embed_cache_key(post_id) -> str:
    return f"embed:{post_id}"


# ── Semantic Router ───────────────────────────────────────────────────────────

class SemanticRouter:
    """
    Wraps SentenceTransformer for post embedding and pgvector similarity search.
    All public methods degrade gracefully when the model is unavailable.
    """

    _model = None          # class-level lazy cache
    _model_available: bool | None = None

    @classmethod
    def _get_model(cls):
        """
        Lazy-load SentenceTransformer.
        Returns None if sentence_transformers is not installed or model fails to load.
        """
        if cls._model_available is False:
            return None
        if cls._model is not None:
            return cls._model
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            cls._model = SentenceTransformer(EMBEDDING_MODEL)
            cls._model_available = True
            logger.info("SemanticRouter: loaded model %s", EMBEDDING_MODEL)
        except Exception as exc:  # pragma: no cover
            logger.warning("SemanticRouter: model unavailable (%s)", exc)
            cls._model_available = False
        return cls._model

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed(self, text: str) -> Optional[list[float]]:
        """Embed text into a 384-dim unit vector. Returns None if unavailable."""
        model = self._get_model()
        if model is None:
            return None
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_post(self, title: str, content: str) -> Optional[list[float]]:
        """Concatenate title + content and embed."""
        text = f"{title} {content}".strip()
        return self.embed(text)

    def is_available(self) -> bool:
        """True if the embedding model is loaded and functional."""
        return self._get_model() is not None

    # ── Cache helpers ─────────────────────────────────────────────────────────

    async def get_cached_embedding(self, post_id) -> Optional[list[float]]:
        """Fetch embedding from Redis cache. Returns None on miss."""
        key  = _embed_cache_key(post_id)
        data = await cache_get(key)
        if data is None:
            return None
        # stored as {"vec": [...]}
        return data.get("vec")

    async def cache_embedding(self, post_id, embedding: list[float]) -> None:
        """Store embedding in Redis with 1-hour TTL."""
        key = _embed_cache_key(post_id)
        await cache_set(key, {"vec": embedding}, ttl=TTL_EMBEDDING)

    async def invalidate_embedding(self, post_id) -> None:
        """Remove cached embedding (call when post content changes)."""
        await cache_delete(_embed_cache_key(post_id))

    # ── Database ──────────────────────────────────────────────────────────────

    async def get_post_embedding(self, post_id, conn) -> Optional[list[float]]:
        """
        Return embedding for post_id.
        Check: Redis → DB → None.
        """
        # 1. Redis
        cached = await self.get_cached_embedding(post_id)
        if cached is not None:
            return cached

        # 2. Database
        row = await conn.fetchrow(
            "SELECT embedding FROM posts WHERE post_id = $1",
            post_id,
        )
        if row is None or row["embedding"] is None:
            return None

        vec = list(row["embedding"])
        await self.cache_embedding(post_id, vec)
        return vec

    async def embed_and_store(
        self,
        post_id,
        title: str,
        content: str,
        conn,
    ) -> Optional[list[float]]:
        """
        Embed post text and persist embedding to posts.embedding.
        Returns the embedding on success, None if model unavailable.
        """
        embedding = self.embed_post(title, content)
        if embedding is None:
            return None

        import numpy as np
        from pgvector.asyncpg import register_vector  # noqa: PLC0415
        await register_vector(conn)

        await conn.execute(
            "UPDATE posts SET embedding = $1 WHERE post_id = $2",
            np.array(embedding, dtype=np.float32),
            post_id,
        )
        await self.cache_embedding(post_id, embedding)
        logger.debug("Stored embedding for post %s", post_id)
        return embedding

    async def find_similar(
        self,
        conn,
        embedding: list[float],
        limit: int = 10,
        exclude_post_id=None,
    ) -> list[dict]:
        """
        Find posts similar to the given embedding using pgvector cosine distance.
        Returns list of {post_id, title, content, similarity}.
        """
        import numpy as np
        from pgvector.asyncpg import register_vector  # noqa: PLC0415
        await register_vector(conn)

        vec = np.array(embedding, dtype=np.float32)

        if exclude_post_id is not None:
            rows = await conn.fetch(
                """
                SELECT
                    post_id, title, content,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM posts
                WHERE visibility = 'PUBLIC'
                  AND embedding IS NOT NULL
                  AND post_id != $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                vec, exclude_post_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT
                    post_id, title, content,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM posts
                WHERE visibility = 'PUBLIC'
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vec, limit,
            )

        return [dict(r) for r in rows]


# ── Singleton ─────────────────────────────────────────────────────────────────

semantic_router = SemanticRouter()
