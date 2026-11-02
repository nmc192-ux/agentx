"""055_mention_cap_index - index for the per-author mention notification cap (Layer 1, S3-5)

Revision ID: 055
Revises: 054
Create Date: 2026-11-03

`services/mentions.py` asks, on every write that names someone, how many
MENTION notifications the author has sent in the last 24 hours
(``WHERE from_did = $1 AND notif_type = 'MENTION' AND created_at > ...``).
The only index on ``notifications`` (003) starts with ``to_did``, so that
question was a sequential scan on the write path. This partial index answers
it directly and stays small (mention notifications only).

Additive, index only, no data change. Idempotent (IF NOT EXISTS).
Downgrade drops the index.
"""
from __future__ import annotations

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifs_from_mention
            ON notifications (from_did, created_at DESC)
            WHERE notif_type = 'MENTION'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notifs_from_mention")
