"""
Integration tests: the founder actor guard against REAL local Postgres.
Sprint 10, S10-1 (`src/founders/roster.resolve_founder`).

What is proven:
  • each of the eight seeded founders resolves to its own `-001` row
  • a DID that is not in the roster, a DID that belongs to another founder,
    a DID with no row, a row that is SUSPENDED / DEACTIVATED /
    PENDING_REVIEW, and a row displayed under another name are all refused —
    with the reason named, and without the guard returning anything
  • a `-seed-NNN` address is accepted when the roster names it and the row is
    the founder's
  • the production roster rule: with nothing listed, no founder resolves

Rows are changed only inside transactions that are rolled back, so the
seeded founders are exactly as before once a test ends.

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import FounderRefused, founder_roster, resolve_founder

pytestmark = pytest.mark.integration   # skipped unless --db is given

DEV = founder_roster("", "development")


@asynccontextmanager
async def rolled_back(pool):
    """A connection inside a transaction that is always rolled back."""
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
        finally:
            await tr.rollback()


async def _refused(conn, name, roster) -> str:
    with pytest.raises(FounderRefused) as exc:
        await resolve_founder(conn, name, roster)
    assert exc.value.name == name
    return exc.value.reason


async def test_every_seeded_founder_resolves_to_its_own_row(pool):
    async with pool.acquire() as conn:
        for name in FOUNDER_NAMES:
            founder = await resolve_founder(conn, name, DEV)
            assert founder.did == f"did:agentx:{name}-001"
            assert founder.display_name == name.upper()
            assert founder.persona is PERSONAS[name]
            assert founder.agent_id == await conn.fetchval(
                "SELECT agent_id FROM agents WHERE agent_did = $1", founder.did
            )


async def test_with_nothing_listed_nobody_resolves_outside_development(pool):
    async with pool.acquire() as conn:
        for name in FOUNDER_NAMES:
            assert await _refused(conn, name, founder_roster("", "production")) == "not_in_roster"
            assert await _refused(conn, name, founder_roster("", "staging")) == "not_in_roster"
        # Listing one founder clears only that founder.
        roster = founder_roster("gia=did:agentx:gia-001", "production")
        assert (await resolve_founder(conn, "gia", roster)).did == "did:agentx:gia-001"
        assert await _refused(conn, "atlas", roster) == "not_in_roster"


async def test_a_did_of_another_founder_or_no_row_is_refused(pool):
    async with pool.acquire() as conn:
        # Nova's real row, offered under Atlas's name: the pattern check wins.
        assert await _refused(conn, "atlas", {"atlas": "did:agentx:nova-001"}) == "did_mismatch"
        # Right shape, but no such agent.
        assert await _refused(conn, "atlas", {"atlas": "did:agentx:atlas-seed-777"}) == "not_found"
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM agents WHERE agent_did = 'did:agentx:atlas-seed-777'"
        ) == 0


@pytest.mark.parametrize("status", ["SUSPENDED", "DEACTIVATED", "PENDING_REVIEW"])
async def test_a_row_that_is_not_active_is_refused(pool, status):
    async with rolled_back(pool) as conn:
        await conn.execute(
            "UPDATE agents SET status = $1::agent_status WHERE agent_did = 'did:agentx:quinn-001'",
            status,
        )
        assert await _refused(conn, "quinn", DEV) == "not_active"
        # The others are untouched by one founder's suspension.
        assert (await resolve_founder(conn, "gia", DEV)).did == "did:agentx:gia-001"
    async with pool.acquire() as conn:
        assert (await resolve_founder(conn, "quinn", DEV)).did == "did:agentx:quinn-001"


async def test_a_row_displayed_under_another_name_is_refused(pool):
    async with rolled_back(pool) as conn:
        await conn.execute(
            "UPDATE agents SET display_name = 'Quinn_-002' WHERE agent_did = 'did:agentx:quinn-001'"
        )
        assert await _refused(conn, "quinn", DEV) == "name_mismatch"
        # Case does not matter; the surrounding whitespace does not either.
        await conn.execute(
            "UPDATE agents SET display_name = ' quinn ' WHERE agent_did = 'did:agentx:quinn-001'"
        )
        assert (await resolve_founder(conn, "quinn", DEV)).did == "did:agentx:quinn-001"


async def test_a_seed_address_is_accepted_only_when_the_roster_names_it(pool):
    async with rolled_back(pool) as conn:
        # Make room for the display name (unique among ACTIVE agents), then add
        # the kind of row production has: did:agentx:<name>-seed-NNN.
        await conn.execute(
            "UPDATE agents SET display_name = 'THEA (old)' WHERE agent_did = 'did:agentx:thea-001'"
        )
        await conn.execute(
            """
            INSERT INTO agents (agent_did, display_name, governance_role)
            VALUES ('did:agentx:thea-seed-002', 'Thea', 'MEMBER'::governance_role)
            """
        )
        seed = {**DEV, "thea": "did:agentx:thea-seed-002"}
        founder = await resolve_founder(conn, "thea", seed)
        assert founder.did == "did:agentx:thea-seed-002" and founder.display_name == "Thea"
        # The default roster still points at thea-001, now displayed otherwise.
        assert await _refused(conn, "thea", DEV) == "name_mismatch"
        # The seed row is nobody else's.
        assert await _refused(conn, "nova", {"nova": "did:agentx:thea-seed-002"}) == "did_mismatch"
    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM agents WHERE agent_did = 'did:agentx:thea-seed-002'"
        ) == 0
