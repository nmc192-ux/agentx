"""008 — agent tasks

Revision ID: 008
Revises: 007
Create Date: 2026-03-12
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            requester_agent_id UUID REFERENCES agents(agent_id),
            executor_agent_id UUID REFERENCES agents(agent_id),
            requester_agent_did TEXT,
            executor_agent_did TEXT,
            task_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL,
            result JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_executor
            ON tasks(executor_agent_did, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_requester
            ON tasks(requester_agent_did, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_requester")
    op.execute("DROP INDEX IF EXISTS idx_tasks_executor")
    op.execute("DROP TABLE IF EXISTS tasks")
