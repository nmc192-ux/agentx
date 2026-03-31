"""038 — Add verification feedback columns to task_results

Revision ID: 038
Revises: 037
Create Date: 2026-03-31

Adds feedback, verified_by_did, and verified_at columns to task_results
for the result verification workflow.
"""
from alembic import op

revision = "038"
down_revision = "037b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE task_results
            ADD COLUMN IF NOT EXISTS feedback        TEXT,
            ADD COLUMN IF NOT EXISTS verified_by_did TEXT,
            ADD COLUMN IF NOT EXISTS verified_at     TIMESTAMPTZ
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE task_results
            DROP COLUMN IF EXISTS feedback,
            DROP COLUMN IF EXISTS verified_by_did,
            DROP COLUMN IF EXISTS verified_at
    """)
