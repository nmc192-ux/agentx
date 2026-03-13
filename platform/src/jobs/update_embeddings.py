"""
AgentX Platform — Update Embeddings Job
════════════════════════════════════════
Celery task: re-embed posts created/updated in last hour.

Runs every hour via beat schedule.
Updates posts.embedding for new/stale records.

SOURCE: phase5_implementation_plan.md Sprint 4 — Data Pipeline
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

try:
    from .celery_app import celery_app
except ModuleNotFoundError:  # pragma: no cover - unit tests can run without Celery installed
    class _CeleryStub:
        def task(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

    celery_app = _CeleryStub()
from ..database           import get_db             # module-level for test patching
from ..ml.semantic_router import semantic_router    # module-level for test patching

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

BATCH_LIMIT    = 100       # max posts per run
LOOKBACK_HOURS = 1         # process posts from last N hours


# ── Job logic (async inner function for testability) ─────────────────────────

async def _run_update_embeddings(lookback_hours: int = LOOKBACK_HOURS,
                                 limit: int = BATCH_LIMIT) -> dict:
    """
    Core logic for update_embeddings job.
    Returns summary dict: {processed, skipped, errors}.
    Separated from Celery task so it can be tested without a running broker.
    """

    processed = skipped = errors = 0
    since     = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT post_id, title, content
            FROM posts
            WHERE (created_at >= $1 OR updated_at >= $1)
              AND embedding IS NULL
            ORDER BY created_at DESC
            LIMIT $2
            """,
            since, limit,
        )

        logger.info("update_embeddings: found %d posts to embed", len(rows))

        for row in rows:
            post_id = row["post_id"]
            title   = row["title"]   or ""
            content = row["content"] or ""

            try:
                embedding = await semantic_router.embed_and_store(
                    post_id, title, content, conn
                )
                if embedding is None:
                    logger.debug("Skipped post %s (model unavailable)", post_id)
                    skipped += 1
                else:
                    processed += 1
            except Exception as exc:
                logger.error("Embedding failed for post %s: %s", post_id, exc)
                errors += 1

    summary = {"processed": processed, "skipped": skipped, "errors": errors}
    logger.info("update_embeddings: %s", summary)
    return summary


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(name="jobs.update_embeddings", bind=True, max_retries=2)
def update_post_embeddings(self):
    """
    Celery task: embed posts created/updated in the last hour.
    Scheduled every hour by Celery Beat.
    """
    try:
        loop    = asyncio.new_event_loop()
        summary = loop.run_until_complete(_run_update_embeddings())
        loop.close()
        return summary
    except Exception as exc:
        logger.error("update_embeddings task failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
