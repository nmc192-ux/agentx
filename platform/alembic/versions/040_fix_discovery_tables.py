"""040_fix_discovery_tables - Reconcile discovery tables (agents/discover|top 500 fix)

Revision ID: 040
Revises: 039
Create Date: 2026-07-04

The /agents/discover and /agents/top endpoints 500 IN PRODUCTION ONLY (they
return 200 locally — the code and migration 027 are correct). Cause: the
production DB carries a legacy `agent_metrics` table keyed by `agent_did` with
NO `agent_id` column, and is missing `agent_capabilities_registry` entirely.
discovery_service's ranking query joins `agent_metrics.agent_id` and
`agent_capabilities_registry`, so it raises UndefinedColumn/UndefinedTable →
500. Migration 027's `CREATE TABLE IF NOT EXISTS agent_metrics` silently
no-ops over the wrong-shaped legacy table, so a plain re-run never fixes it.

This migration drops the legacy `agent_metrics` ONLY if it has the pre-027
shape (no `agent_id` column) — it is empty in production (verified 2026-07-04),
so nothing is lost — then re-issues migration 027's DDL verbatim (idempotent).
It is a NO-OP on any correctly-migrated DB (local/CI), and repairs production
on the next deploy via the existing release_command `alembic upgrade head`.

NOTE: this repairs the discovery tables specifically. The wider production
schema divergence (prod stamped 037 over a ~28-table baseline, missing rooms /
proposals / stakes / contracts / …) is a separate, larger reconciliation task —
see briefing_2026-07-04_chain.md. Do not treat this migration as fixing that.
"""

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the legacy pre-027 agent_metrics (keyed by agent_did, no agent_id)
    # ONLY if that wrong shape is present. Empty in production; no-op locally.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_name = 'agent_metrics')
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'agent_metrics'
                         AND column_name = 'agent_id')
            THEN
                DROP TABLE agent_metrics CASCADE;
            END IF;
        END $$
    """)

    # Re-issue migration 027's DDL verbatim (all idempotent). Creates the
    # correctly-shaped tables where missing; no-op where already correct.
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
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_capabilities_registry'
                  AND indexname = 'idx_capability_lookup') THEN
                CREATE INDEX idx_capability_lookup ON agent_capabilities_registry(capability);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_capabilities_registry'
                  AND indexname = 'idx_cap_registry_agent_id') THEN
                CREATE INDEX idx_cap_registry_agent_id ON agent_capabilities_registry(agent_id);
            END IF;
        END $$
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS discovery_embeddings (
            capability  TEXT    PRIMARY KEY,
            embedding   JSONB   NOT NULL DEFAULT '[]'::jsonb,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
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
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_metrics'
                  AND indexname = 'idx_agent_metrics_score') THEN
                CREATE INDEX idx_agent_metrics_score ON agent_metrics(contracts_completed DESC);
            END IF;
        END $$
    """)


def downgrade() -> None:
    # No-op: the discovery tables are owned by migration 027. This migration
    # only reconciles a divergent production copy; there is nothing of its own
    # to reverse, and dropping the tables would break the (correct) 027 state.
    op.execute("SELECT 1")
