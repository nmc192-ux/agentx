"""
Phase 3.5 — Unique display_name (case-insensitive, ACTIVE only)
═════════════════════════════════════════════════════════════════

Security fix: enforces uniqueness of agent display_name across ACTIVE agents
at the database level so that ``POST /onboard`` cannot be used as an
account-takeover primitive.  The /onboard handler does its own pre-flight
``SELECT`` and returns ``409 Conflict`` for taken names; this index closes
the TOCTOU race between concurrent registrations and is the source of truth.

Changes (additive only):
  • Auto-resolve any pre-existing duplicate ACTIVE display_names by
    suffixing newer rows with the last 4 chars of agent_did.  The OLDEST
    row (by created_at, then agent_did) keeps the bare name.
  • Create UNIQUE INDEX on LOWER(display_name) WHERE status = 'ACTIVE'.
    Partial-index — soft-deleted (non-ACTIVE) agents do not block re-use.

Revision ID: 038
Revises:      037
"""
from alembic import op

revision      = "038"
down_revision = "037"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # 1. Resolve any existing duplicates among ACTIVE agents.
    #    Keep the oldest (by created_at NULLS LAST, then agent_did); rename
    #    every other collision by appending the last 4 chars of its DID.
    #    This is idempotent — re-running the migration on already-deduped
    #    data is a no-op (nothing matches rn > 1).
    op.execute(
        """
        WITH dups AS (
            SELECT agent_did,
                   ROW_NUMBER() OVER (
                       PARTITION BY LOWER(display_name)
                       ORDER BY created_at NULLS LAST, agent_did
                   ) AS rn
            FROM agents
            WHERE status = 'ACTIVE'
        )
        UPDATE agents a
        SET display_name = a.display_name
                           || '_'
                           || RIGHT(REPLACE(a.agent_did, ':', ''), 4)
        FROM dups d
        WHERE a.agent_did = d.agent_did
          AND d.rn > 1;
        """
    )

    # 2. Create the unique partial index.  Cannot use CREATE INDEX
    #    CONCURRENTLY inside an alembic transaction; for the table sizes
    #    we expect this is acceptable.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_display_name_lower_active
            ON agents (LOWER(display_name))
            WHERE status = 'ACTIVE';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agents_display_name_lower_active;")
    # We do NOT un-suffix the deduped names — that would require storing
    # the original collisions, and a downgrade is unlikely to be needed.
