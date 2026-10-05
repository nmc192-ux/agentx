"""042_task_status_cancelled - tasks.status may be 'cancelled'

Revision ID: 042
Revises: 041
Create Date: 2026-10-02

Sprint 9, S9-7b. A creator can now withdraw a marketplace task nobody has
taken (POST /tasks/{id}/cancel): the reward and the fee are refunded and the
task becomes 'cancelled'. Migration 015's CHECK on tasks.status does not
allow that value, so this migration widens it by one word. No row is changed.

The new constraint is added NOT VALID and validated in a second step, so the
table is not scanned under the exclusive lock. Every existing row satisfied
the old, narrower list, so validation cannot fail on a database that had the
old constraint; on one that somehow did not (and holds an odd status), the
validation failure is reported as a warning instead of failing the deploy —
new and updated rows are checked either way.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: the old list has no word for a cancelled task, so cancelled tasks
are relabelled 'FAILED' (the legacy "did not finish" status; their money was
already refunded) before the old constraint is put back.
"""

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_tasks_status")
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT chk_tasks_status
        CHECK (status IN (
            'open', 'assigned', 'cancelled',
            'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'
        )) NOT VALID
    """)
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE tasks VALIDATE CONSTRAINT chk_tasks_status;
        EXCEPTION WHEN check_violation THEN
            RAISE WARNING
                'chk_tasks_status left NOT VALID: existing tasks rows hold a '
                'status outside the allowed list (new rows are still checked)';
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_tasks_status")
    op.execute("UPDATE tasks SET status = 'FAILED' WHERE status = 'cancelled'")
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT chk_tasks_status
        CHECK (status IN (
            'open', 'assigned',
            'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'
        ))
    """)
