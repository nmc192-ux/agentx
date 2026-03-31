"""037 — Payment notification types for token economy

Revision ID: 037
Revises: 036
Create Date: 2026-03-30

Extends the notif_type enum with payment-related notification types:
  PAYMENT_RECEIVED  — tokens transferred to you
  TASK_PAYMENT      — payment received for completing a task
  ESCROW_HELD       — your funds held in escrow
  ESCROW_RELEASED   — escrow released to you

Also adds a ref_amount and ref_token_type column to notifications
so payment notifications can carry economic context without a separate join.
"""
from alembic import op

revision = "037b"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend the notif_type enum with payment notification values.
    # ALTER TYPE ... ADD VALUE is safe and non-destructive.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'notif_type'::regtype
                  AND enumlabel = 'PAYMENT_RECEIVED'
            ) THEN
                ALTER TYPE notif_type ADD VALUE 'PAYMENT_RECEIVED';
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'notif_type'::regtype
                  AND enumlabel = 'TASK_PAYMENT'
            ) THEN
                ALTER TYPE notif_type ADD VALUE 'TASK_PAYMENT';
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'notif_type'::regtype
                  AND enumlabel = 'ESCROW_HELD'
            ) THEN
                ALTER TYPE notif_type ADD VALUE 'ESCROW_HELD';
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'notif_type'::regtype
                  AND enumlabel = 'ESCROW_RELEASED'
            ) THEN
                ALTER TYPE notif_type ADD VALUE 'ESCROW_RELEASED';
            END IF;
        END $$
    """)

    # Add optional economic metadata columns to notifications.
    op.execute("""
        ALTER TABLE notifications
            ADD COLUMN IF NOT EXISTS ref_amount     BIGINT,
            ADD COLUMN IF NOT EXISTS ref_token_type TEXT,
            ADD COLUMN IF NOT EXISTS ref_tx_id      UUID
    """)


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; column removal is safe.
    op.execute("""
        ALTER TABLE notifications
            DROP COLUMN IF EXISTS ref_amount,
            DROP COLUMN IF EXISTS ref_token_type,
            DROP COLUMN IF EXISTS ref_tx_id
    """)
    # Note: enum values cannot be removed from notif_type without recreating the type.
