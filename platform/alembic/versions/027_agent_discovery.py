"""027_agent_discovery - Agent Discovery & Capability Registry

Revision ID: 027
Revises: 026
Create Date: 2026-03-15

Adds the Agent Discovery & Capability Registry tables:
  agent_capabilities_registry  — per-agent capability + confidence declarations
  discovery_embeddings         — capability-level embeddings for semantic search
                                 (stored as JSONB; ready for pgvector promotion)
  agent_metrics                — aggregated performance counters used for ranking
"""

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────── agent_capabilities_registry ─────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_capabilities_registry (
            registry_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id     UUID        NOT NULL
                                     REFERENCES agents(agent_id) ON DELETE CASCADE,
            capability   TEXT        NOT NULL,
            confidence   FLOAT       NOT NULL DEFAULT 1.0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (agent_id, capability)
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_capabilities_registry'
                  AND indexname = 'idx_capability_lookup'
            ) THEN
                CREATE INDEX idx_capability_lookup
                    ON agent_capabilities_registry(capability);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_capabilities_registry'
                  AND indexname = 'idx_cap_registry_agent_id'
            ) THEN
                CREATE INDEX idx_cap_registry_agent_id
                    ON agent_capabilities_registry(agent_id);
            END IF;
        END $$
    """)

    # ────────────────────────────────── discovery_embeddings ─────────────────
    # NOTE: deliberately named 'discovery_embeddings' (not 'capability_embeddings')
    # to avoid collision with the JSONB capability_embeddings table from migration 016.
    # When pgvector is activated, the 'embedding' column can be migrated to VECTOR(384).
    op.execute("""
        CREATE TABLE IF NOT EXISTS discovery_embeddings (
            capability  TEXT    PRIMARY KEY,
            embedding   JSONB   NOT NULL DEFAULT '[]'::jsonb,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ──────────────────────────────────── agent_metrics ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_metrics (
            agent_id              UUID        PRIMARY KEY
                                              REFERENCES agents(agent_id) ON DELETE CASCADE,
            contracts_completed   INT         NOT NULL DEFAULT 0,
            contracts_failed      INT         NOT NULL DEFAULT 0,
            verification_success  FLOAT       NOT NULL DEFAULT 0.0,
            bounties_won          INT         NOT NULL DEFAULT 0,
            last_active           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_metrics'
                  AND indexname = 'idx_agent_metrics_score'
            ) THEN
                CREATE INDEX idx_agent_metrics_score
                    ON agent_metrics(contracts_completed DESC);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_metrics CASCADE")
    op.execute("DROP TABLE IF EXISTS discovery_embeddings CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_capabilities_registry CASCADE")
