"""Phase 17 — Federated AgentX Nodes

Revision ID: 028
Revises:     027
Create Date: 2026-03-15

Tables added
────────────
  agentx_nodes   — known peer AgentX nodes
  node_messages  — log of events sent/received with peer nodes
"""
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agentx_nodes ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agentx_nodes (
            node_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            node_url      TEXT        NOT NULL UNIQUE,
            node_name     TEXT,
            public_key    TEXT,
            status        TEXT        NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'inactive', 'banned')),
            trust_level   FLOAT       NOT NULL DEFAULT 0.5
                          CHECK (trust_level >= 0 AND trust_level <= 1),
            registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at  TIMESTAMPTZ
        )
    """)

    # ── node_messages ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS node_messages (
            message_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            node_id     UUID        REFERENCES agentx_nodes(node_id) ON DELETE SET NULL,
            event_type  TEXT        NOT NULL,
            payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
            direction   TEXT        NOT NULL DEFAULT 'inbound'
                        CHECK (direction IN ('inbound', 'outbound')),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_node_messages_event_type'
            ) THEN
                CREATE INDEX idx_node_messages_event_type
                    ON node_messages(event_type);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_node_messages_node_id'
            ) THEN
                CREATE INDEX idx_node_messages_node_id
                    ON node_messages(node_id);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_agentx_nodes_status'
            ) THEN
                CREATE INDEX idx_agentx_nodes_status
                    ON agentx_nodes(status);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS node_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS agentx_nodes CASCADE")
