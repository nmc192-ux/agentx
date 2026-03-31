"""042 — Developer ecosystem: API keys and webhooks

Revision ID: 042
Revises: 041
Create Date: 2026-03-31

API keys provide programmatic access without JWT dance.
Webhooks enable push-based event delivery to agent endpoints.
"""
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── API Keys ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did     TEXT NOT NULL,
            key_prefix    TEXT NOT NULL,
            key_hash      TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT 'default',
            scopes        TEXT[] DEFAULT '{read,write}'::text[],
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            last_used_at  TIMESTAMPTZ,
            expires_at    TIMESTAMPTZ,
            created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_agent ON api_keys(agent_did, is_active)")

    # ── Webhooks ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhooks (
            webhook_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did     TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT 'default',
            callback_url  TEXT NOT NULL,
            secret        TEXT NOT NULL,
            event_types   TEXT[] NOT NULL DEFAULT '{*}'::text[],
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            failure_count INT NOT NULL DEFAULT 0,
            last_triggered_at TIMESTAMPTZ,
            created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_agent ON webhooks(agent_did, is_active)")

    # ── Webhook Delivery Log ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            delivery_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            webhook_id    UUID NOT NULL REFERENCES webhooks(webhook_id) ON DELETE CASCADE,
            event_id      UUID NOT NULL,
            event_type    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'delivered', 'failed', 'skipped')),
            response_code INT,
            attempt_count INT NOT NULL DEFAULT 0,
            last_attempt  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_status ON webhook_deliveries(status, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_webhook ON webhook_deliveries(webhook_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_deliveries CASCADE")
    op.execute("DROP TABLE IF EXISTS webhooks CASCADE")
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE")
