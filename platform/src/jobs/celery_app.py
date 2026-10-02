"""
AgentX Platform — Celery Application
═════════════════════════════════════
Celery app configured with Redis broker/backend.
Includes the beat schedule for recurring jobs.

Run worker + scheduler as one process (one is enough):
    celery -A src.jobs.celery_app worker --beat --concurrency 1 --loglevel info
(Linux. On macOS the embedded beat fails to start under the default "spawn"
start method; there run `celery ... beat` and `celery ... worker` separately.)

SOURCE: phase5_implementation_plan.md Sprint 4 — Infrastructure
"""
import os

from celery import Celery

from ..cache import _resolve_redis_url

# ── Redis URL ─────────────────────────────────────────────────────────────────
# Same Redis as the API (REDIS_URL, else the REDIS_* settings, TLS included),
# unless CELERY_BROKER_URL says otherwise. Managed Redis often has only db 0.

def _broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or _resolve_redis_url()


# ── Celery app ────────────────────────────────────────────────────────────────

celery_app = Celery(
    "agentx",
    broker=_broker_url(),
    backend=_broker_url(),
    include=[
        "src.jobs.scheduled_maintenance",
        "src.jobs.founder_heartbeat",
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

# Two jobs are scheduled: maintenance (S9-9) and the founder heartbeat
# (S10-3; the task returns at once unless FOUNDER_HEARTBEAT_ENABLED is on, so
# scheduling it costs one Celery message per five minutes and nothing else).
# The two ML jobs stay registered but unscheduled: their dependencies (numpy,
# xgboost, an embedding provider) are not installed, and embedding calls can
# cost money.
MAINTENANCE_INTERVAL_SECONDS = 900.0        # every 15 minutes
FOUNDER_HEARTBEAT_INTERVAL_SECONDS = 300.0  # every 5 minutes

celery_app.conf.beat_schedule = {
    "scheduled-maintenance": {
        "task":     "jobs.scheduled_maintenance",
        "schedule": MAINTENANCE_INTERVAL_SECONDS,
    },
    "founder-heartbeat": {
        "task":     "jobs.founder_heartbeat",
        "schedule": FOUNDER_HEARTBEAT_INTERVAL_SECONDS,
    },
}
