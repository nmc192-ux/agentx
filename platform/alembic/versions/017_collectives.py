"""017 — collectives

Revision ID: 017
Revises: 016
Create Date: 2026-03-15

Phase 6 — Agent Collectives schema:
  - collectives        (IF NOT EXISTS — may already exist from init-db.sql)
  - collective_members (IF NOT EXISTS — may already exist from init-db.sql)
  - collective_tasks   (NEW — links marketplace tasks to executing collectives)
  - executor_collective_id column added to tasks (Phase 6 Step 5)

All statements are idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── collectives ─────────────────────────────────────────────────────────────
    # May already exist from docker-entrypoint-initdb.d/01_init.sql.
    # IF NOT EXISTS ensures idempotency on fresh vs. existing databases.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS collectives (
            collective_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(128) NOT NULL,
            description     VARCHAR(1024) NOT NULL DEFAULT '',
            charter         TEXT,
            is_public       BOOLEAN NOT NULL DEFAULT TRUE,
            owner_did       TEXT NOT NULL REFERENCES agents(agent_did),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_collectives_owner ON collectives(owner_did)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_collectives_created ON collectives(created_at DESC)"
    )

    # ── collective_members ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS collective_members (
            collective_id   UUID NOT NULL REFERENCES collectives(collective_id) ON DELETE CASCADE,
            agent_did       TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            role            TEXT NOT NULL DEFAULT 'MEMBER'
                            CHECK (role IN ('OWNER', 'ADMIN', 'MEMBER')),
            status          TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING', 'ACTIVE', 'BANNED')),
            joined_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (collective_id, agent_did)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_col_members_agent ON collective_members(agent_did)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_col_members_status
            ON collective_members(collective_id, status)
        """
    )

    # ── collective_tasks (NEW) ──────────────────────────────────────────────────
    # Links marketplace tasks to a collective for collaborative execution.
    # Each task may only be assigned to one collective at a time (UNIQUE).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS collective_tasks (
            collective_task_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            collective_id       UUID NOT NULL
                                REFERENCES collectives(collective_id) ON DELETE CASCADE,
            task_id             UUID NOT NULL
                                REFERENCES tasks(task_id) ON DELETE CASCADE,
            assigned_by_did     TEXT NOT NULL REFERENCES agents(agent_did),
            status              TEXT NOT NULL DEFAULT 'assigned'
                                CHECK (status IN ('assigned', 'running', 'completed', 'failed')),
            assigned_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (collective_id, task_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_col_tasks_collective
            ON collective_tasks(collective_id, assigned_at DESC)
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_col_tasks_task ON collective_tasks(task_id)"
    )

    # ── Extend tasks with executor_collective_id ────────────────────────────────
    # Allows a task to be routed to a collective instead of (or in addition to)
    # a single executor agent.
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS executor_collective_id UUID
            REFERENCES collectives(collective_id)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS executor_collective_id")
    op.execute("DROP INDEX IF EXISTS idx_col_tasks_task")
    op.execute("DROP INDEX IF EXISTS idx_col_tasks_collective")
    op.execute("DROP TABLE IF EXISTS collective_tasks")
    # Leave collectives and collective_members — they are owned by init-db.sql.
    # Dropping them here would destroy seed data on rollback.
