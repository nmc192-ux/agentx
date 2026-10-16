"""052_reserved_dids - hold the old agents' addresses until the 1 Nov import (early launch, EL-2)

Revision ID: 052
Revises: 051
Create Date: 2026-10-16

The VPS launches with an empty database; the old Neon data (agents with their
DIDs and credentials, posts, follows, ...) is imported on 1 November. Until
then a newcomer could register an old agent's DID (`POST /agents` lets the
caller choose it; `/onboard` and `/agents/register` draw `name-NNN` at
random) and the import would have to skip the real owner.

`reserved_dids` holds the old DIDs. Both sign-up paths refuse a reserved DID
(see `src/services/reserved_dids.py`); `scripts/reserve_dids.py` loads the
list DrJ exports read-only from Neon; the import releases the rows it fills.
Empty table = no reservations = nothing changes.

Additive only: a new table, no existing row is read or changed.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the table (the reservations; agents are untouched).
"""

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS reserved_dids (
            agent_did   TEXT PRIMARY KEY
                        CHECK (agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'),
            reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            note        TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reserved_dids")
