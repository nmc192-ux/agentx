"""051_collective_request_message - keep the note sent with a join request (Phase C, Sprint 22, CL-2)

Revision ID: 051
Revises: 050
Create Date: 2026-10-15

`POST /collectives/{id}/join` has always accepted an optional `message`
(max 500 characters) and thrown it away. The collective's OWNER/ADMIN now
read pending requests (`GET /collectives/{id}/requests`), and the note is
what tells them who is asking and why, so it is kept on the membership row.

Additive only: one nullable column, no existing row is read or changed.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the column (the notes; memberships are untouched).
"""

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE collective_members
            ADD COLUMN IF NOT EXISTS request_message TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE collective_members DROP COLUMN IF EXISTS request_message")
