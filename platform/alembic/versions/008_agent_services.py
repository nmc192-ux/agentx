"""009 — agent services marketplace

Revision ID: 009
Revises: 008
Create Date: 2026-03-12
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS services (
            service_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID REFERENCES agents(agent_id),
            agent_did TEXT,
            service_name TEXT NOT NULL,
            service_type TEXT NOT NULL,
            description TEXT,
            pricing_model TEXT,
            price DOUBLE PRECISION,
            capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_services_type
            ON services(service_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_services_agent
            ON services(agent_did)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_services_agent")
    op.execute("DROP INDEX IF EXISTS idx_services_type")
    op.execute("DROP TABLE IF EXISTS services")
