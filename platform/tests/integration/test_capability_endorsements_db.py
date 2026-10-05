"""
Integration tests: capability endorsements and the trust trigger (Sprint 9,
S9-9d), against REAL local Postgres.

POST /agents/{did}/capabilities/{id}/verify used to add one to a counter on
every call, so one other account calling it twice made a capability
"verified". And any write to agent_trust_breakdown reset agents.trust_score to
the flat factor composite (0.44), wiping what the scheduled job had worked out.

What is proven (HTTP → router → Postgres, migration 045 applied):
  • one endorsement per endorser: a second call is a 409 and counts nothing,
    also when many arrive at the same moment
  • the owner cannot endorse their own capability; the database refuses the
    row as well
  • the endorser is the login: a body naming another agent is a 403, no
    login a 401
  • a new (under 24 h) or suspended account cannot endorse
  • two different established accounts make a capability verified
  • a count from before the table existed does not decide "verified"; a
    flag already set stays set
  • removing a capability removes its endorsements
  • updating a breakdown row leaves agents.trust_score alone; inserting one
    still sets the starting value

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncio

import asyncpg
import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

CAP = "data.sql.advanced"   # seeded by init-db.sql


async def _holder(agents, pool, name: str = "holder", **columns):
    """An agent that holds CAP (as POST /agents/{did}/capabilities leaves it)."""
    agent = await agents(name)
    await pool.execute(
        "INSERT INTO agent_capabilities (agent_did, capability_id) VALUES ($1, $2)",
        agent.did, CAP,
    )
    for column, value in columns.items():
        await pool.execute(
            f"UPDATE agent_capabilities SET {column} = $1 WHERE agent_did = $2 AND capability_id = $3",
            value, agent.did, CAP,
        )
    return agent


async def _endorse(client, endorser, holder, **body):
    return await client.post(
        f"/agents/{holder.did}/capabilities/{CAP}/verify",
        json=body, headers=endorser.headers,
    )


async def _state(pool, holder) -> tuple[bool, int, int]:
    """(verified, verified_by_count, recorded endorsers)."""
    row = await pool.fetchrow(
        "SELECT verified, verified_by_count FROM agent_capabilities "
        "WHERE agent_did = $1 AND capability_id = $2",
        holder.did, CAP,
    )
    endorsers = await pool.fetchval(
        "SELECT COUNT(*) FROM capability_endorsements WHERE agent_did = $1 AND capability_id = $2",
        holder.did, CAP,
    )
    return row["verified"], row["verified_by_count"], endorsers


# ── One endorsement per endorser ──────────────────────────────────────────────

async def test_a_second_endorsement_by_the_same_account_changes_nothing(client, pool, agents):
    holder = await _holder(agents, pool)
    friend = await agents("friend", age_days=30)

    first = await _endorse(client, friend, holder)
    assert first.status_code == 200, first.text
    assert first.json()["verified"] is False
    assert first.json()["verified_by_count"] == 1
    assert first.json()["endorsed_by"] == friend.did

    for _ in range(3):
        again = await _endorse(client, friend, holder)
        assert again.status_code == 409, again.text

    assert await _state(pool, holder) == (False, 1, 1)


async def test_endorsements_at_the_same_moment_count_once(client, pool, agents):
    holder = await _holder(agents, pool)
    friend = await agents("friend", age_days=30)

    answers = await asyncio.gather(*(_endorse(client, friend, holder) for _ in range(8)))

    assert sorted(a.status_code for a in answers) == [200] + [409] * 7
    assert await _state(pool, holder) == (False, 1, 1)


async def test_two_different_established_accounts_verify_a_capability(client, pool, agents):
    holder = await _holder(agents, pool)
    first, second = await agents("first", age_days=2), await agents("second", age_days=2)

    assert (await _endorse(client, first, holder)).json()["verified"] is False
    answer = await _endorse(client, second, holder, notes="worked with them on a pipeline")

    assert answer.status_code == 200, answer.text
    assert answer.json()["verified"] is True
    assert answer.json()["endorsers"] == 2
    assert await _state(pool, holder) == (True, 2, 2)

    listed = await client.get(f"/agents/{holder.did}/capabilities")
    assert [(c["verified"], c["verified_by_count"]) for c in listed.json()] == [(True, 2)]


async def test_different_endorsers_at_the_same_moment_are_all_counted(client, pool, agents):
    holder = await _holder(agents, pool)
    endorsers = [await agents(f"e{i}", age_days=5) for i in range(5)]

    answers = await asyncio.gather(*(_endorse(client, e, holder) for e in endorsers))

    assert [a.status_code for a in answers] == [200] * 5
    assert await _state(pool, holder) == (True, 5, 5)


async def test_two_endorsers_at_the_same_moment_still_verify(client, pool, agents):
    """Each of the two must see the other's endorsement when it decides
    "verified" (the capability row is locked first), on every pair."""
    holders = [await _holder(agents, pool, f"holder{i}") for i in range(12)]
    first, second = await agents("first", age_days=5), await agents("second", age_days=5)

    await asyncio.gather(*(
        _endorse(client, endorser, holder)
        for holder in holders for endorser in (first, second)
    ))

    assert [await _state(pool, h) for h in holders] == [(True, 2, 2)] * 12


# ── Who may endorse ───────────────────────────────────────────────────────────

async def test_the_owner_cannot_endorse_their_own_capability(client, pool, agents):
    holder = await _holder(agents, pool)
    await pool.execute(
        "UPDATE agents SET created_at = NOW() - INTERVAL '30 days' WHERE agent_did = $1",
        holder.did,
    )

    answer = await _endorse(client, holder, holder)

    assert answer.status_code == 422, answer.text
    assert await _state(pool, holder) == (False, 0, 0)
    # The table refuses it too, whatever the code above it does.
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            "INSERT INTO capability_endorsements (agent_did, capability_id, endorser_did) "
            "VALUES ($1, $2, $1)",
            holder.did, CAP,
        )


async def test_the_endorser_is_the_login_not_the_body(client, pool, agents):
    holder = await _holder(agents, pool)
    friend, other = await agents("friend", age_days=30), await agents("other", age_days=30)

    as_other = await _endorse(client, friend, holder, endorser_did=other.did)
    assert as_other.status_code == 403, as_other.text
    assert await _state(pool, holder) == (False, 0, 0)

    as_self = await _endorse(client, friend, holder, endorser_did=friend.did)
    assert as_self.status_code == 200, as_self.text
    assert await pool.fetchval(
        "SELECT endorser_did FROM capability_endorsements WHERE agent_did = $1", holder.did,
    ) == friend.did


async def test_no_login_no_endorsement(client, pool, agents):
    holder = await _holder(agents, pool)

    answer = await client.post(f"/agents/{holder.did}/capabilities/{CAP}/verify", json={})

    assert answer.status_code == 401
    assert await _state(pool, holder) == (False, 0, 0)


async def test_a_new_account_cannot_endorse(client, pool, agents):
    holder = await _holder(agents, pool)
    made_today = [await agents(f"new{i}") for i in range(3)]

    for account in made_today:
        answer = await _endorse(client, account, holder)
        assert answer.status_code == 403, answer.text

    assert await _state(pool, holder) == (False, 0, 0)


async def test_a_suspended_account_cannot_endorse(client, pool, agents):
    holder = await _holder(agents, pool)
    suspended = await agents("suspended", age_days=30)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", suspended.did)

    assert (await _endorse(client, suspended, holder)).status_code == 403
    assert await _state(pool, holder) == (False, 0, 0)


async def test_a_capability_the_agent_does_not_hold_is_a_404(client, pool, agents):
    holder = await agents("holder")
    friend = await agents("friend", age_days=30)

    assert (await _endorse(client, friend, holder)).status_code == 404
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM capability_endorsements WHERE agent_did = $1", holder.did,
    ) == 0


# ── Counts from before the table existed ──────────────────────────────────────

async def test_an_old_count_does_not_make_a_capability_verified(client, pool, agents):
    """verified_by_count = 1 with no recorded endorser: one more endorser shows
    a count of 2, but "verified" needs two endorsers the table knows."""
    holder = await _holder(agents, pool, verified_by_count=1)
    first, second = await agents("first", age_days=30), await agents("second", age_days=30)

    answer = await _endorse(client, first, holder)
    assert (answer.json()["verified"], answer.json()["verified_by_count"]) == (False, 2)
    assert await _state(pool, holder) == (False, 2, 1)

    assert (await _endorse(client, second, holder)).json()["verified"] is True
    assert await _state(pool, holder) == (True, 3, 2)


async def test_a_flag_already_set_stays_set(client, pool, agents):
    """The founders' capabilities are seeded verified, with no recorded endorser."""
    holder = await _holder(agents, pool, verified=True, verified_by_count=3)
    friend = await agents("friend", age_days=30)

    answer = await _endorse(client, friend, holder)

    assert answer.status_code == 200, answer.text
    assert await _state(pool, holder) == (True, 4, 1)


async def test_removing_a_capability_removes_its_endorsements(client, pool, agents):
    holder = await _holder(agents, pool)
    friend = await agents("friend", age_days=30)
    assert (await _endorse(client, friend, holder)).status_code == 200

    removed = await client.delete(
        f"/agents/{holder.did}/capabilities/{CAP}", headers=holder.headers,
    )
    assert removed.status_code == 204, removed.text
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM capability_endorsements WHERE agent_did = $1", holder.did,
    ) == 0

    # Held again: it starts from nothing, and the same friend counts once more.
    added = await client.post(
        f"/agents/{holder.did}/capabilities", json={"capability_id": CAP}, headers=holder.headers,
    )
    assert added.status_code == 201, added.text
    assert (await _endorse(client, friend, holder)).json()["verified_by_count"] == 1
    assert await _state(pool, holder) == (False, 1, 1)


# ── The trust trigger ─────────────────────────────────────────────────────────

async def _trust(pool, agent) -> float:
    return float(await pool.fetchval(
        "SELECT trust_score FROM agents WHERE agent_id = $1", agent.agent_id,
    ))


async def test_updating_a_breakdown_row_leaves_the_trust_score_alone(pool, agents):
    agent = await agents("scored")
    await pool.execute(
        "INSERT INTO agent_trust_breakdown (agent_did) VALUES ($1)", agent.did,
    )
    # Sign-up's insert still sets the starting value (the factor composite).
    assert await _trust(pool, agent) == pytest.approx(0.44)

    # The scheduled job has since worked out a real score.
    await pool.execute("UPDATE agents SET trust_score = 0.81 WHERE agent_id = $1", agent.agent_id)

    await pool.execute(
        "UPDATE agent_trust_breakdown SET peer_endorsements = 0.90, execution_success = 0.10 "
        "WHERE agent_did = $1",
        agent.did,
    )
    assert await _trust(pool, agent) == pytest.approx(0.81)

    # An upsert that lands on the existing row is an update, not an insert.
    await pool.execute(
        """
        INSERT INTO agent_trust_breakdown (agent_did, sla_compliance) VALUES ($1, 0.20)
        ON CONFLICT (agent_did) DO UPDATE SET sla_compliance = EXCLUDED.sla_compliance
        """,
        agent.did,
    )
    assert await _trust(pool, agent) == pytest.approx(0.81)
