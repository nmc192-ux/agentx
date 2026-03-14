"""
019 — Economic Engine
═════════════════════
Phase 8.5: Extended token economy with treasury, supply management,
fee collection, stake slashing, and economic metrics.

Schema changes
──────────────
wallets      — agent_id now nullable (treasury wallet has agent_id = NULL)
               + wallet_type TEXT NOT NULL DEFAULT 'agent'
tasks        — + task_fee BIGINT NOT NULL DEFAULT 0

New tables
──────────
token_supply      — singleton supply tracker (total_minted / total_burned)
fee_policies      — configurable fee schedules (rate in basis points)
stake_slashes     — immutable record of slashed stake events
economic_metrics  — periodic economic-state snapshots
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── wallets: make agent_id nullable for treasury wallet ───────────────────
    op.execute(
        "ALTER TABLE wallets ALTER COLUMN agent_id DROP NOT NULL"
    )

    # ── wallets: add wallet_type ───────────────────────────────────────────────
    op.execute("""
        ALTER TABLE wallets
            ADD COLUMN IF NOT EXISTS wallet_type TEXT NOT NULL DEFAULT 'agent'
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'wallets_type_valid'
            ) THEN
                ALTER TABLE wallets
                    ADD CONSTRAINT wallets_type_valid
                    CHECK (wallet_type IN ('agent', 'treasury'));
            END IF;
        END $$
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_treasury_singleton
            ON wallets(wallet_type)
            WHERE wallet_type = 'treasury'
    """)

    # ── tasks: add task_fee ───────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS task_fee BIGINT NOT NULL DEFAULT 0
    """)

    # ── token_supply ──────────────────────────────────────────────────────────
    # Singleton table — at most one row.
    op.execute("""
        CREATE TABLE IF NOT EXISTS token_supply (
            supply_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            total_minted BIGINT      NOT NULL DEFAULT 0,
            total_burned BIGINT      NOT NULL DEFAULT 0,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'token_supply_nonneg_minted'
            ) THEN
                ALTER TABLE token_supply
                    ADD CONSTRAINT token_supply_nonneg_minted CHECK (total_minted >= 0);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'token_supply_nonneg_burned'
            ) THEN
                ALTER TABLE token_supply
                    ADD CONSTRAINT token_supply_nonneg_burned CHECK (total_burned >= 0);
            END IF;
        END $$
    """)

    # ── fee_policies ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS fee_policies (
            policy_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name       TEXT        NOT NULL UNIQUE,
            rate_bps   INTEGER     NOT NULL DEFAULT 0,
            active     BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fee_policies_rate_valid'
            ) THEN
                ALTER TABLE fee_policies
                    ADD CONSTRAINT fee_policies_rate_valid
                    CHECK (rate_bps >= 0 AND rate_bps <= 10000);
            END IF;
        END $$
    """)

    # ── stake_slashes ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stake_slashes (
            slash_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            stake_id   UUID        NOT NULL REFERENCES stakes(stake_id),
            agent_id   UUID        NOT NULL REFERENCES agents(agent_id),
            amount     BIGINT      NOT NULL,
            reason     TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'stake_slashes_amount_pos'
            ) THEN
                ALTER TABLE stake_slashes
                    ADD CONSTRAINT stake_slashes_amount_pos CHECK (amount > 0);
            END IF;
        END $$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_slashes_agent
            ON stake_slashes(agent_id, created_at DESC)
    """)

    # ── economic_metrics ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS economic_metrics (
            metric_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            total_supply     BIGINT      NOT NULL DEFAULT 0,
            treasury_balance BIGINT      NOT NULL DEFAULT 0,
            total_staked     BIGINT      NOT NULL DEFAULT 0,
            active_tasks     INTEGER     NOT NULL DEFAULT 0,
            fees_collected   BIGINT      NOT NULL DEFAULT 0,
            recorded_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_metrics_recorded
            ON economic_metrics(recorded_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_metrics_recorded")
    op.execute("DROP TABLE IF EXISTS economic_metrics")
    op.execute("DROP INDEX IF EXISTS idx_slashes_agent")
    op.execute("DROP TABLE IF EXISTS stake_slashes")
    op.execute("DROP TABLE IF EXISTS fee_policies")
    op.execute("DROP TABLE IF EXISTS token_supply")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS task_fee")
    op.execute("DROP INDEX IF EXISTS idx_wallets_treasury_singleton")
    op.execute("""
        ALTER TABLE wallets
            DROP CONSTRAINT IF EXISTS wallets_type_valid
    """)
    op.execute("ALTER TABLE wallets DROP COLUMN IF EXISTS wallet_type")
    op.execute("ALTER TABLE wallets ALTER COLUMN agent_id SET NOT NULL")
