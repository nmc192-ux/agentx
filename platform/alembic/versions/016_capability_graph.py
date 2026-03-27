"""016 — capability graph

Revision ID: 016
Revises: 015
Create Date: 2026-03-15

Formalises the capability graph schema in Alembic:
  - capabilities       (IF NOT EXISTS — may already exist from init-db.sql)
  - agent_capabilities (IF NOT EXISTS — may already exist from init-db.sql)
  - capability_embeddings (NEW — stores vector embeddings per capability)

All statements are idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING).
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── capabilities ───────────────────────────────────────────────────────────
    # May already exist from docker-entrypoint-initdb.d/01_init.sql.
    # IF NOT EXISTS ensures idempotency on fresh vs. existing databases.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capabilities (
            capability_id         TEXT PRIMARY KEY
                                  CHECK (capability_id ~
                                         '^[a-z]+\.[a-z0-9_]+\.(basic|intermediate|advanced|expert)$'),
            name                  VARCHAR(100) NOT NULL,
            description           VARCHAR(500) NOT NULL DEFAULT '',
            domain                TEXT NOT NULL,
            level                 TEXT NOT NULL,
            requires_verification BOOLEAN NOT NULL DEFAULT FALSE,
            rep_reward            INTEGER NOT NULL DEFAULT 10
                                  CHECK (rep_reward >= 1 AND rep_reward <= 1000),
            prerequisites         TEXT[] NOT NULL DEFAULT '{}',
            verified_by           TEXT[] NOT NULL DEFAULT '{}',
            created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_capabilities_domain ON capabilities(domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_capabilities_level ON capabilities(level)"
    )

    # ── agent_capabilities ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_capabilities (
            agent_did          TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            capability_id      TEXT NOT NULL REFERENCES capabilities(capability_id),
            verified           BOOLEAN NOT NULL DEFAULT FALSE,
            verified_by_count  INTEGER NOT NULL DEFAULT 0
                               CHECK (verified_by_count >= 0),
            acquired_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (agent_did, capability_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_caps_agent ON agent_capabilities(agent_did)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_caps_cap ON agent_capabilities(capability_id)"
    )

    # ── capability_embeddings (NEW) ────────────────────────────────────────────
    # Stores pre-computed embeddings for semantic capability matching.
    # Uses JSONB for the vector until pgvector is enabled (Sprint 4+).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_embeddings (
            embedding_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            capability_id   TEXT NOT NULL
                            REFERENCES capabilities(capability_id) ON DELETE CASCADE,
            embedding_model TEXT NOT NULL DEFAULT 'text-embedding-ada-002',
            embedding       JSONB NOT NULL DEFAULT '[]'::jsonb,
            dimensions      INTEGER NOT NULL DEFAULT 1536,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (capability_id, embedding_model)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_capability_embeddings_cap
            ON capability_embeddings(capability_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_capability_embeddings_cap")
    op.execute("DROP TABLE IF EXISTS capability_embeddings")
    # Leave capabilities and agent_capabilities — they are owned by init-db.sql
    # and dropping them would destroy seed data on downgrade.
