"""037 — escrow holds table for token settlement

Revision ID: 037
Revises: 034
Create Date: 2026-03-30

Adds the escrow_holds table for the token settlement engine.
Escrow records track funds held during task assignment and released
on completion or refunded on cancellation.
"""
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS escrow_holds (
            escrow_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id         UUID NOT NULL,
            holder_did      TEXT NOT NULL,
            token_type      TEXT NOT NULL DEFAULT 'WORK',
            amount          BIGINT NOT NULL CHECK (amount > 0),
            status          TEXT NOT NULL DEFAULT 'HELD'
                            CHECK (status IN ('HELD', 'RELEASED', 'REFUNDED')),
            released_to_did TEXT,
            created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            released_at     TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_escrow_task
            ON escrow_holds(task_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_escrow_holder
            ON escrow_holds(holder_did, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_escrow_holder")
    op.execute("DROP INDEX IF EXISTS idx_escrow_task")
    op.execute("DROP TABLE IF EXISTS escrow_holds")
