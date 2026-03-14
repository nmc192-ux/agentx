"""
018 — Agent Token Economy
═════════════════════════
Phase 8: Native token currency for the AgentX platform.

New tables:
  wallets      — one wallet per agent, tracks native-token balance
  transactions — immutable ledger; NULL from/to = system/escrow
  stakes       — locked token amounts per agent

Existing table changes:
  tasks — adds escrowed_reward BIGINT DEFAULT 0
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── wallets ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            wallet_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id   UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            balance    BIGINT      NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (agent_id)
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'wallets_balance_nonneg'
            ) THEN
                ALTER TABLE wallets
                    ADD CONSTRAINT wallets_balance_nonneg CHECK (balance >= 0);
            END IF;
        END $$
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallets_agent ON wallets(agent_id)"
    )

    # ── transactions ──────────────────────────────────────────────────────────
    # NULL from_wallet / to_wallet represents the "system" (escrow / mint / burn).
    op.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            from_wallet    UUID        REFERENCES wallets(wallet_id),
            to_wallet      UUID        REFERENCES wallets(wallet_id),
            amount         BIGINT      NOT NULL,
            type           TEXT        NOT NULL,
            related_id     UUID,
            timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'transactions_amount_positive'
            ) THEN
                ALTER TABLE transactions
                    ADD CONSTRAINT transactions_amount_positive CHECK (amount > 0);
            END IF;
        END $$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_txn_from
            ON transactions(from_wallet, timestamp DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_txn_to
            ON transactions(to_wallet, timestamp DESC)
    """)

    # ── stakes ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stakes (
            stake_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id     UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            amount       BIGINT      NOT NULL,
            locked_until TIMESTAMPTZ,
            released_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'stakes_amount_positive'
            ) THEN
                ALTER TABLE stakes
                    ADD CONSTRAINT stakes_amount_positive CHECK (amount > 0);
            END IF;
        END $$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stakes_agent
            ON stakes(agent_id, created_at DESC)
    """)

    # ── tasks: escrowed_reward column ─────────────────────────────────────────
    op.execute("""
        ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS escrowed_reward BIGINT NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS escrowed_reward")
    op.execute("DROP INDEX IF EXISTS idx_stakes_agent")
    op.execute("DROP TABLE IF EXISTS stakes")
    op.execute("DROP INDEX IF EXISTS idx_txn_to")
    op.execute("DROP INDEX IF EXISTS idx_txn_from")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP INDEX IF EXISTS idx_wallets_agent")
    op.execute("DROP TABLE IF EXISTS wallets")
