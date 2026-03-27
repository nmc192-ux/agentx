"""015 — task marketplace tables

Revision ID: 015
Revises: 014
Create Date: 2026-03-15

Adds the Agent Task Economy / Task Marketplace schema:
  - Extends existing tasks table with creator_agent_id and reward columns
  - Creates task_bids table for agent bidding
  - Creates task_assignments table for accepted bids
  - Creates task_results table for submitted results
  - Adds indexes and CHECK constraint on status
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend existing tasks table ────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS creator_agent_id UUID REFERENCES agents(agent_id)
        """
    )
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS reward INT NOT NULL DEFAULT 0
        """
    )

    # Backfill creator_agent_id from requester_agent_id for existing rows
    op.execute(
        """
        UPDATE tasks
        SET creator_agent_id = requester_agent_id
        WHERE creator_agent_id IS NULL
          AND requester_agent_id IS NOT NULL
        """
    )

    # CHECK constraint: restrict marketplace-visible status values
    # (existing PENDING/IN_PROGRESS/COMPLETED/FAILED + new open/assigned)
    # Use a DO block because ADD CONSTRAINT IF NOT EXISTS is only PG 16+.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_tasks_status'
                  AND conrelid = 'tasks'::regclass
            ) THEN
                ALTER TABLE tasks ADD CONSTRAINT chk_tasks_status
                CHECK (status IN (
                    'open', 'assigned',
                    'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'
                ));
            END IF;
        END $$
        """
    )

    # Index for marketplace status queries
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status, created_at DESC)
        """
    )

    # ── task_bids ──────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_bids (
            bid_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id     UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            agent_id    UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            confidence  DOUBLE PRECISION NOT NULL DEFAULT 1.0
                        CHECK (confidence >= 0.0 AND confidence <= 1.0),
            bid_price   INT NOT NULL DEFAULT 0 CHECK (bid_price >= 0),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_bids_task_id
            ON task_bids(task_id, created_at DESC)
        """
    )

    # ── task_assignments ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_assignments (
            assignment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id         UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            agent_id        UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            status          TEXT NOT NULL DEFAULT 'assigned'
                            CHECK (status IN ('assigned', 'running', 'completed', 'failed')),
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_assignments_agent_id
            ON task_assignments(agent_id, task_id)
        """
    )

    # ── task_results ───────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_results (
            result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id             UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            agent_id            UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            result_payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
            verification_status TEXT NOT NULL DEFAULT 'pending'
                                CHECK (verification_status IN ('pending', 'verified', 'rejected')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_results_task_id
            ON task_results(task_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_task_results_task_id")
    op.execute("DROP TABLE IF EXISTS task_results")

    op.execute("DROP INDEX IF EXISTS idx_task_assignments_agent_id")
    op.execute("DROP TABLE IF EXISTS task_assignments")

    op.execute("DROP INDEX IF EXISTS idx_task_bids_task_id")
    op.execute("DROP TABLE IF EXISTS task_bids")

    op.execute("DROP INDEX IF EXISTS idx_tasks_status")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_tasks_status")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS reward")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS creator_agent_id")
