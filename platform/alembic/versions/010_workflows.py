"""011 - workflow engine

Revision ID: 011
Revises: 010
Create Date: 2026-03-12
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            workflow_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_type TEXT NOT NULL,
            initiator_agent_did TEXT NOT NULL REFERENCES agents(agent_did),
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_steps (
            step_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL,
            task_id UUID REFERENCES tasks(task_id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow
            ON workflow_steps(workflow_id, step_order)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_steps_workflow")
    op.execute("DROP TABLE IF EXISTS workflow_steps")
    op.execute("DROP TABLE IF EXISTS workflows")
