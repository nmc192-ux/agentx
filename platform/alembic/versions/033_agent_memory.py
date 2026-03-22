"""
Phase 33 — Agent Memory Store
══════════════════════════════
Server-side persistent key-value memory for SDK agents.
Agents can store and retrieve arbitrary JSON values across sessions.

Changes:
  • Creates table agent_memory
      - memory_id   UUID PK (gen_random_uuid)
      - agent_did   TEXT FK → agents(agent_did) ON DELETE CASCADE
      - key         TEXT NOT NULL
      - value       JSONB NOT NULL
      - created_at  TIMESTAMPTZ DEFAULT now()
      - updated_at  TIMESTAMPTZ DEFAULT now()
  • UNIQUE constraint on (agent_did, key)  — one value per key per agent
  • Index on agent_did                      — fast per-agent key listing
"""

from alembic import op

revision      = "033"
down_revision = "032"
branch_labels = None
depends_on    = None


# ─────────────────────────────────────────────────────────────────────────────

def upgrade() -> None:

    # ── 1. agent_memory table ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            memory_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did   TEXT        NOT NULL
                        REFERENCES agents(agent_did) ON DELETE CASCADE,
            key         TEXT        NOT NULL,
            value       JSONB       NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_agent_memory_did_key UNIQUE (agent_did, key)
        )
    """)

    # ── 2. Index on agent_did (fast per-agent key listing) ───────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_did "
        "ON agent_memory(agent_did)"
    )


# ─────────────────────────────────────────────────────────────────────────────

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_memory CASCADE")
