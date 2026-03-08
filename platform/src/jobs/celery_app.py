"""
AgentX Platform — Celery Application
═════════════════════════════════════
Celery app configured with Redis broker/backend.
Includes beat schedule for recurring ML jobs.

SOURCE: phase5_implementation_plan.md Sprint 4 — Infrastructure
"""
from celery import Celery

from ..config import get_settings

settings = get_settings()

# ── Redis URLs ────────────────────────────────────────────────────────────────

def _redis_url(db: int) -> str:
    password = settings.redis_password
    host     = settings.redis_host
    port     = settings.redis_port
    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


# ── Celery app ────────────────────────────────────────────────────────────────

celery_app = Celery(
    "agentx",
    broker=_redis_url(1),
    backend=_redis_url(2),
    include=[
        "src.jobs.update_embeddings",
        "src.jobs.retrain_trust_model",
    ],
)

celery_app.conf.update(
    task_serializer     = "json",
    result_serializer   = "json",
    accept_content      = ["json"],
    timezone            = "UTC",
    enable_utc          = True,
    task_track_started  = True,
    result_expires      = 86400,  # 24 hours
)

# ── Beat schedule (cron jobs) ─────────────────────────────────────────────────

celery_app.conf.beat_schedule = {
    "update-embeddings-hourly": {
        "task":     "jobs.update_embeddings",
        "schedule": 3600.0,   # every hour
    },
    "retrain-trust-model-weekly": {
        "task":     "jobs.retrain_trust_model",
        "schedule": 604800.0,  # every week (7 days)
    },
}
