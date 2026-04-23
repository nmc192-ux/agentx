"""002 — Row-Level Security policies (MARCUS P1 Gap 3)

Revision ID: 002
Revises: 001
Create Date: 2026-03-07

Enables RLS on all sensitive tables and creates policies that filter
rows based on app.current_agent_did session variable injected by
src/database.py:get_db_for_agent().
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # RLS is applied by init-db.sql on first run.
    # This migration is a no-op for existing environments where init ran the RLS block.
    # For environments that applied schema WITHOUT RLS (e.g. existing dev DBs),
    # run the RLS statements here to backfill.
    op.execute("""
        DO $$
        BEGIN
          -- Only apply if RLS is not already enabled on agents via init-db.sql.
          -- init-db.sql creates policies with different names (e.g. agents_select),
          -- so we check for ANY policy on the `agents` table rather than a specific name.
          IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE tablename = 'agents'
          ) THEN
            ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
            CREATE POLICY agents_read_all ON agents FOR SELECT USING (true);
            CREATE POLICY agents_update_own ON agents FOR UPDATE
              USING (agent_did = current_setting('app.current_agent_did', true));

            ALTER TABLE token_balances ENABLE ROW LEVEL SECURITY;
            CREATE POLICY token_balances_own ON token_balances FOR SELECT
              USING (agent_id = (
                SELECT id FROM agents
                WHERE agent_did = current_setting('app.current_agent_did', true)
              ));

            ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY audit_read_own ON audit_logs FOR SELECT
              USING (agent_did = current_setting('app.current_agent_did', true));
            CREATE POLICY audit_insert_any ON audit_logs FOR INSERT WITH CHECK (true);
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE agents DISABLE ROW LEVEL SECURITY;
        ALTER TABLE token_balances DISABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS agents_read_all ON agents;
        DROP POLICY IF EXISTS agents_update_own ON agents;
        DROP POLICY IF EXISTS token_balances_own ON token_balances;
        DROP POLICY IF EXISTS audit_read_own ON audit_logs;
        DROP POLICY IF EXISTS audit_insert_any ON audit_logs;
    """)
