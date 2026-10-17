"""
Integration tests: migration 048, the agent_spotlights table (Sprint 17,
S17-1), against REAL local Postgres.

What is proven (migration 048 applied by the fixture's alembic chain):
  • one row per week: a second INSERT ... ON CONFLICT DO NOTHING is a no-op
  • week_start must be a Monday
  • chosen_by is 'auto' or a DID, nothing else
  • agent_did must name a real agent; deleting the agent keeps the week's
    row with agent_did NULL

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from datetime import date

import asyncpg
import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

# Far from any week the job or later tests would touch.
MONDAY = date(1999, 1, 4)
TUESDAY = date(1999, 1, 5)


@pytest.fixture
async def clean(pool):
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")
    yield pool
    await pool.execute("DELETE FROM agent_spotlights WHERE week_start < '2000-01-01'")


async def test_one_pick_per_week(clean, agents):
    a, b = await agents("spot-a"), await agents("spot-b")
    insert = """
        INSERT INTO agent_spotlights (week_start, agent_did, chosen_by)
        VALUES ($1, $2, 'auto') ON CONFLICT (week_start) DO NOTHING
    """
    assert await clean.execute(insert, MONDAY, a.did) == "INSERT 0 1"
    assert await clean.execute(insert, MONDAY, b.did) == "INSERT 0 0"
    row = await clean.fetchrow("SELECT * FROM agent_spotlights WHERE week_start = $1", MONDAY)
    assert row["agent_did"] == a.did
    assert row["withdrawn_at"] is None and row["breakdown"] == "{}"


async def test_week_must_start_on_monday(clean):
    with pytest.raises(asyncpg.CheckViolationError):
        await clean.execute(
            "INSERT INTO agent_spotlights (week_start, chosen_by) VALUES ($1, 'auto')", TUESDAY,
        )


@pytest.mark.parametrize("chosen_by", ["", "founder", "AUTO", "mallory did:agentx:x"])
async def test_chosen_by_is_auto_or_a_did(clean, chosen_by):
    with pytest.raises(asyncpg.CheckViolationError):
        await clean.execute(
            "INSERT INTO agent_spotlights (week_start, chosen_by) VALUES ($1, $2)",
            MONDAY, chosen_by,
        )


async def test_agent_must_exist(clean):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await clean.execute(
            "INSERT INTO agent_spotlights (week_start, agent_did, chosen_by) "
            "VALUES ($1, 'did:agentx:nobody', 'auto')",
            MONDAY,
        )


async def test_deleting_the_agent_keeps_the_week(clean, agents):
    a = await agents("spot-gone")
    await clean.execute(
        "INSERT INTO agent_spotlights (week_start, agent_did, chosen_by) VALUES ($1, $2, 'auto')",
        MONDAY, a.did,
    )
    await clean.execute("DELETE FROM agents WHERE agent_did = $1", a.did)
    assert await clean.fetchval(
        "SELECT agent_did FROM agent_spotlights WHERE week_start = $1", MONDAY,
    ) is None
