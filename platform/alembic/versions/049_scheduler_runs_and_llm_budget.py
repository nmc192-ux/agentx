"""049_scheduler_runs_and_llm_budget - broker-free scheduler state in Postgres

Revision ID: 049
Revises: 048
Create Date: 2026-10-10

Production went down on 9 Oct 2026 when the Upstash free plan ran out of
requests (Celery's broker polling used it up in three days). The scheduler no
longer needs Redis (src/jobs/scheduler.py); the two things it kept there now
live here:

  • scheduler_job_runs — one row per scheduled job: when it last started and
                         finished, and how it ended. The scheduler takes a
                         transaction-level advisory lock for the job, then
                         reads this row, so a second scheduler process (an
                         overlapping deploy) neither runs the job at the same
                         time nor runs it again before its interval is over.
  • founder_llm_calls  — the founder LLM daily call budget
                         (FOUNDER_LLM_DAILY_CALLS): one row per UTC day,
                         counted up by an atomic upsert that refuses once the
                         cap is reached.

Additive only: two new tables, no existing row is read or changed.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops both tables (the run history and the day counts).
"""

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_job_runs (
            job_name          TEXT        PRIMARY KEY,
            last_started_at   TIMESTAMPTZ NOT NULL,
            last_finished_at  TIMESTAMPTZ,
            last_status       TEXT        NOT NULL DEFAULT 'running',
            last_summary      JSONB       NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT scheduler_job_runs_status
                CHECK (last_status IN ('running', 'ok', 'failed'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS founder_llm_calls (
            day    DATE    PRIMARY KEY,
            calls  INTEGER NOT NULL DEFAULT 0 CHECK (calls >= 0)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS founder_llm_calls")
    op.execute("DROP TABLE IF EXISTS scheduler_job_runs")
