"""039 — Service invocations table

Revision ID: 039
Revises: 038
Create Date: 2026-03-31

Creates the service_invocations table for the service proxy system.
Agents can invoke each other's registered services; the provider
polls for pending invocations and completes them with results.
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS service_invocations (
            invocation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            service_id    UUID NOT NULL,
            caller_did    TEXT NOT NULL,
            provider_did  TEXT NOT NULL,
            payload       JSONB DEFAULT '{}'::jsonb,
            result        JSONB,
            status        TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')),
            price         BIGINT NOT NULL DEFAULT 0,
            token_type    TEXT NOT NULL DEFAULT 'WORK',
            created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            completed_at  TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invocations_caller
            ON service_invocations(caller_did, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invocations_provider
            ON service_invocations(provider_did, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invocations_service
            ON service_invocations(service_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_invocations_service")
    op.execute("DROP INDEX IF EXISTS idx_invocations_provider")
    op.execute("DROP INDEX IF EXISTS idx_invocations_caller")
    op.execute("DROP TABLE IF EXISTS service_invocations")
