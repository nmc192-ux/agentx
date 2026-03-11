"""004 — add Agent Registry columns to existing agents table

Revision ID: 004
Revises: 003
Create Date: 2026-03-11
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS agent_id UUID
    """)
    op.execute("""
        UPDATE agents
        SET agent_id = gen_random_uuid()
        WHERE agent_id IS NULL
    """)
    op.execute("""
        ALTER TABLE agents
            ALTER COLUMN agent_id SET DEFAULT gen_random_uuid()
    """)
    op.execute("""
        ALTER TABLE agents
            ALTER COLUMN agent_id SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS name TEXT
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS description TEXT
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS skills JSONB NOT NULL DEFAULT '[]'::jsonb
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '[]'::jsonb
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS endpoint TEXT
    """)
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS owner TEXT
    """)
    op.execute("""
        UPDATE agents
        SET
            name = COALESCE(name, display_name),
            description = COALESCE(description, bio)
        WHERE name IS NULL OR description IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_agent_id
            ON agents(agent_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agents_agent_id")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS owner")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS endpoint")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS capabilities")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS skills")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS name")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS agent_id")
