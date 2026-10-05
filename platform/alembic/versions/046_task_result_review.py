"""046_task_result_review - a task result waits for the creator's approval

Revision ID: 046
Revises: 045
Create Date: 2026-10-04

Sprint 12, S12-2 (decision D2c). A marketplace task used to pay its reward the
moment the executor submitted any result. From here on a submitted result
puts the task 'in_review': the reward stays in escrow until the creator
approves it, or until the automatic-release period has passed with the
creator silent. A rejected result sends the task back to 'assigned' so the
executor can submit again.

  • tasks.status may be 'in_review' (the CHECK is widened by one word).
  • tasks.submitted_at — when the result now under review was submitted;
    the automatic release counts from it. NULL outside 'in_review'.
  • task_results.review_note — the creator's reason for a rejection.
  • a partial index over the tasks under review, for the release job.

No existing row is changed: a task that was already paid stays 'COMPLETED',
and a task still 'assigned' simply follows the new rule when its result
arrives. Both columns are nullable with no default, so adding them rewrites
nothing.

The new constraint is added NOT VALID and validated in a second step, as in
042, so the table is not scanned under the exclusive lock.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: the old code has no word for a task under review, so such tasks
go back to 'assigned' (their reward is still in escrow and their executor
can submit again under the old rule) before the old constraint is put back.
"""

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE task_results ADD COLUMN IF NOT EXISTS review_note TEXT")

    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_tasks_status")
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT chk_tasks_status
        CHECK (status IN (
            'open', 'assigned', 'in_review', 'cancelled',
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

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_in_review_submitted_at
            ON tasks (submitted_at) WHERE status = 'in_review'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_in_review_submitted_at")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_tasks_status")
    op.execute("UPDATE tasks SET status = 'assigned' WHERE status = 'in_review'")
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT chk_tasks_status
        CHECK (status IN (
            'open', 'assigned', 'cancelled',
            'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'
        ))
    """)
    op.execute("ALTER TABLE task_results DROP COLUMN IF EXISTS review_note")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS submitted_at")
