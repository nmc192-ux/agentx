"""047_contract_dispute_resolution - a FOUNDER's ruling on a disputed contract

Revision ID: 047
Revises: 046
Create Date: 2026-10-04

Sprint 12, S12-3 (decision D3b). A disputed contract used to keep its escrow
for ever: nothing resolved a dispute. From here on a FOUNDER settles it, once,
by paying the contractor or refunding the creator. The ruling is written on
the dispute row:

  • contract_disputes.resolution      — 'pay_contractor' | 'refund_creator';
                                        NULL while the dispute is open.
  • contract_disputes.resolved_by_did — the FOUNDER who ruled.
  • contract_disputes.resolved_at     — when (database clock).
  • contract_disputes.resolution_note — the FOUNDER's reason.

contract_disputes.status goes 'open' → 'resolved'. The contract itself ends
'completed' (contractor paid) or 'cancelled' (creator refunded), the two
words it already has for those outcomes.

No existing row is changed: all four columns are nullable with no default, so
adding them rewrites nothing, and a dispute opened before this migration is
simply still open. The CHECK only constrains the new column.

Idempotent (safe to re-run from `alembic stamp 001`).
"""

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contract_disputes ADD COLUMN IF NOT EXISTS resolution TEXT")
    op.execute("ALTER TABLE contract_disputes ADD COLUMN IF NOT EXISTS resolved_by_did TEXT")
    op.execute("ALTER TABLE contract_disputes ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contract_disputes ADD COLUMN IF NOT EXISTS resolution_note TEXT")

    op.execute(
        "ALTER TABLE contract_disputes DROP CONSTRAINT IF EXISTS chk_contract_disputes_resolution"
    )
    op.execute("""
        ALTER TABLE contract_disputes ADD CONSTRAINT chk_contract_disputes_resolution
        CHECK (resolution IS NULL OR resolution IN ('pay_contractor', 'refund_creator'))
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE contract_disputes DROP CONSTRAINT IF EXISTS chk_contract_disputes_resolution"
    )
    op.execute("ALTER TABLE contract_disputes DROP COLUMN IF EXISTS resolution_note")
    op.execute("ALTER TABLE contract_disputes DROP COLUMN IF EXISTS resolved_at")
    op.execute("ALTER TABLE contract_disputes DROP COLUMN IF EXISTS resolved_by_did")
    op.execute("ALTER TABLE contract_disputes DROP COLUMN IF EXISTS resolution")
