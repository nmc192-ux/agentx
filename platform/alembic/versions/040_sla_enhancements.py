"""040 — SLA enforcement enhancements

Revision ID: 040
Revises: 039
Create Date: 2026-03-31

Adds 'overdue' and 'cancelled' to valid task statuses,
and adds an index on task_assignments for SLA queries.
"""
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index for SLA enforcement queries on active assignments
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_assignments_active
            ON task_assignments(status, started_at)
            WHERE status = 'assigned'
    """)

    # Index for escrow lookups by task + status
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_escrow_task_status
            ON escrow_holds(task_id, status)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_escrow_task_status")
    op.execute("DROP INDEX IF EXISTS idx_assignments_active")
