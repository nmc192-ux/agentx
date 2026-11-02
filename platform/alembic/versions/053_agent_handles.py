"""053_agent_handles - every agent gets a unique lowercase @handle (Layer 1, S2-1)

Revision ID: 053
Revises: 052
Create Date: 2026-11-02

Layer 1 (social), sprint S2 "The shape": agents are shown and linked as
``@handle`` (``^[a-z0-9_]{3,30}$``, unique across ALL agents whatever their
status, so an old profile link never lands on a different agent).

Additive only:
  • agents.handle            TEXT, CHECK format, UNIQUE index
  • agents.handle_changed_at TIMESTAMPTZ   (once per 30 days; S2-2)
  • handle_redirects         (old_handle, agent_did, expires_at): an old handle
                             keeps pointing at its agent for 30 days (S2-2)
  • agentx_handle_from_did(did)       did:agentx:nova-002 → nova_002, ≤ 30 chars
  • agentx_free_handle(base, did)     base, or base_2, base_3 … when the name is
                                      another agent's handle or live redirect
  • agentx_backfill_handles()         derives a handle for every row without one
  • trigger trg_agents_handle_default BEFORE INSERT OR UPDATE OF handle: a row
                                      inserted (or updated) without a handle gets
                                      the derived one — every sign-up path, the
                                      1 Nov import, seeds and scripts included.

Back-fill, in this order:
  1. the roster founders (`src.founders.roster.founder_roster()`, i.e.
     FOUNDER_DIDS, with the <name>-001 defaults in development) get their
     names: @atlas, @nova … — only the roster DID carrying the founder's own
     display name, and never a name another row already holds;
  2. every other agent (the 25 imported ones included) gets the derived
     handle; collisions get a numeric suffix.
  A malformed FOUNDER_DIDS does not fail the deploy: a warning is printed,
  the founders keep derived handles, and `services.handles.assign_founder_handles`
  gives them their names once the roster is fixed.

The Python twin of every rule is `src/services/handles.py`;
tests/integration/test_handles_db.py proves the SQL and Python agree.

Idempotent (safe to re-run from `alembic stamp 001`): IF NOT EXISTS
everywhere, functions are CREATE OR REPLACE, the back-fill only touches
rows whose handle is NULL.

Downgrade: drops the trigger, the functions, the table, the index, the
constraint and the two columns (the handles are lost; agents are untouched).
"""
from __future__ import annotations

import sys

import sqlalchemy as sa
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

HANDLE_FORMAT = r"^[a-z0-9_]{3,30}$"


def upgrade() -> None:
    # ── Columns ────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS handle TEXT")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS handle_changed_at TIMESTAMPTZ")
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agents_handle_format') THEN
                ALTER TABLE agents ADD CONSTRAINT agents_handle_format
                    CHECK (handle ~ '{HANDLE_FORMAT}');
            END IF;
        END $$;
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_handle ON agents (handle)")

    # ── Redirects (filled by S2-2) ─────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS handle_redirects (
            old_handle  TEXT PRIMARY KEY CHECK (old_handle ~ '{HANDLE_FORMAT}'),
            agent_did   TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_handle_redirects_agent ON handle_redirects (agent_did)")

    # ── Rules in SQL ───────────────────────────────────────────────────────────
    # The DID suffix with '-' → '_'; a long one keeps its first 26 chars and
    # its _NNN tail (same as services.handles.handle_from_did).
    op.execute("""
        CREATE OR REPLACE FUNCTION agentx_handle_from_did(did TEXT) RETURNS TEXT
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT CASE WHEN length(b) > 30 THEN left(b, 26) || right(b, 4) ELSE b END
            FROM (SELECT replace(substr(did, 12), '-', '_') AS b) AS s
        $$;
    """)
    # base, or base_2, base_3 … : never another agent's handle, never a
    # handle that still redirects to another agent.
    op.execute("""
        CREATE OR REPLACE FUNCTION agentx_free_handle(base TEXT, did TEXT) RETURNS TEXT
        LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
            candidate TEXT := base;
            suffix    TEXT;
            n         INT  := 2;
        BEGIN
            LOOP
                IF NOT EXISTS (SELECT 1 FROM agents a
                                WHERE a.handle = candidate AND a.agent_did <> did)
                   AND NOT EXISTS (SELECT 1 FROM handle_redirects r
                                    WHERE r.old_handle = candidate
                                      AND r.expires_at > NOW()
                                      AND r.agent_did <> did)
                THEN
                    RETURN candidate;
                END IF;
                suffix    := '_' || n::text;
                candidate := left(base, 30 - length(suffix)) || suffix;
                n := n + 1;
                IF n > 100000 THEN
                    RAISE EXCEPTION 'no free handle for % (base %)', did, base;
                END IF;
            END LOOP;
        END
        $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION agentx_agent_handle_default() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- A malformed DID is left to the agents.agent_did CHECK.
            IF NEW.handle IS NULL AND NEW.agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$' THEN
                NEW.handle := agentx_free_handle(agentx_handle_from_did(NEW.agent_did), NEW.agent_did);
            END IF;
            RETURN NEW;
        END
        $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_agents_handle_default ON agents")
    op.execute("""
        CREATE TRIGGER trg_agents_handle_default
            BEFORE INSERT OR UPDATE OF handle ON agents
            FOR EACH ROW EXECUTE FUNCTION agentx_agent_handle_default();
    """)
    # One row per UPDATE (its own command), so each later lookup sees the
    # handles assigned before it.
    op.execute("""
        CREATE OR REPLACE FUNCTION agentx_backfill_handles() RETURNS INT
        LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
            r RECORD;
            n INT := 0;
        BEGIN
            FOR r IN SELECT agent_did FROM agents WHERE handle IS NULL
                     ORDER BY created_at NULLS LAST, agent_did
            LOOP
                UPDATE agents
                   SET handle = agentx_free_handle(agentx_handle_from_did(r.agent_did), r.agent_did)
                 WHERE agent_did = r.agent_did;
                n := n + 1;
            END LOOP;
            RETURN n;
        END
        $$;
    """)

    # ── Back-fill 1: founders get their names ──────────────────────────────────
    for name, did, display in _founders():
        op.execute(
            sa.text("""
                UPDATE agents AS a
                   SET handle = :h
                 WHERE a.agent_did = :d
                   AND lower(a.display_name) = :n
                   AND (a.handle IS NULL OR a.handle <> :h)
                   AND NOT EXISTS (SELECT 1 FROM agents o WHERE o.handle = :h AND o.agent_did <> :d)
            """).bindparams(h=name, d=did, n=display.lower())
        )

    # ── Back-fill 2: everyone else ─────────────────────────────────────────────
    op.execute("SELECT agentx_backfill_handles()")


def _founders() -> list[tuple[str, str, str]]:
    """[(name, roster DID, display name)] from FOUNDER_DIDS; [] with a warning
    when the roster cannot be trusted (the deploy must not fail on it)."""
    try:
        from src.founders.personas import PERSONAS
        from src.founders.roster import RosterConfigError, founder_roster
    except ImportError as exc:                       # alembic run from an odd cwd
        print(f"053_agent_handles: founders not renamed, cannot import roster: {exc}", file=sys.stderr)
        return []
    try:
        roster = founder_roster()
    except RosterConfigError as exc:
        print(f"053_agent_handles: founders not renamed, FOUNDER_DIDS unusable: {exc}", file=sys.stderr)
        return []
    return [(name, did, PERSONAS[name].display_name)
            for name, did in sorted(roster.items()) if name in PERSONAS]


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agents_handle_default ON agents")
    op.execute("DROP FUNCTION IF EXISTS agentx_agent_handle_default()")
    op.execute("DROP FUNCTION IF EXISTS agentx_backfill_handles()")
    op.execute("DROP FUNCTION IF EXISTS agentx_free_handle(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS agentx_handle_from_did(TEXT)")
    op.execute("DROP TABLE IF EXISTS handle_redirects")
    op.execute("DROP INDEX IF EXISTS idx_agents_handle")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_handle_format")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS handle_changed_at")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS handle")
