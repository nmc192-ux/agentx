"""001 — Initial schema (baseline from ATLAS agentx_db_schema.sql)

Revision ID: 001
Revises:
Create Date: 2026-03-07
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema is applied by docker-entrypoint-initdb.d/01_init.sql on first run.
    # This migration just marks the baseline in alembic_version.
    op.execute("SELECT 1")   # no-op — schema already exists


def downgrade() -> None:
    raise NotImplementedError("Downgrade to baseline not supported — would drop all data.")
