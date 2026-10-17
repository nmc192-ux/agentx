"""
Integration tests: Sprint 22 security review (CL-8a), against REAL local Postgres.

What is proven (HTTP → router → Postgres, schema from init-db.sql + alembic head):
  • a private collective's profile and member list are 404 to an anonymous
    caller, an outsider and a PENDING asker; its OWNER and an ACTIVE member
    see them; a public one is open to all
  • an ADMIN cannot remove another ADMIN (the row stays); the OWNER can; an
    ADMIN can still remove a MEMBER and reject a PENDING request
  • an agent BANNED by hand cannot delete its own row, is refused when it
    asks again, and stays BANNED; approving it is 404
  • a task handed to one collective cannot be handed to a second; the second
    collective's work done stays empty

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_collective_security_review_db.py -v --db
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from .support import START_BALANCE
from .test_collective_membership_db import join, make_admin, make_collective
from .test_task_escrow_db import assigned_task

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture(autouse=True)
def no_task_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


@pytest.fixture(autouse=True)
def fresh_reads(monkeypatch):
    from src.services import collective_work

    async def miss(key):
        return None

    monkeypatch.setattr(collective_work.cache, "cache_get", miss)


@pytest_asyncio.fixture(autouse=True)
async def optional_caller(agents):
    """The conftest stands in for get_current_agent only; the profile and
    member reads use the optional login, so map it onto the same stand-in."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    from src.main import app

    async def _optional(request: Request):
        try:
            return await app.dependency_overrides[get_current_agent](request)
        except HTTPException:
            return None

    app.dependency_overrides[get_current_agent_optional] = _optional
    yield
    app.dependency_overrides.pop(get_current_agent_optional, None)


async def membership(pool, col, agent):
    return await pool.fetchrow(
        "SELECT role::text AS role, status::text AS status FROM collective_members"
        " WHERE collective_id = $1 AND agent_did = $2", col, agent.did,
    )


# ── Private collective reads ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_private_profile_and_members_hidden_from_non_members(client, pool, agents):
    owner, member, outsider, asker = [await agents(n) for n in ("own", "mem", "out", "ask")]
    col = await make_collective(pool, owner, is_public=False)
    await join(client, col, member)
    r = await client.post(f"/collectives/{col}/members/{member.did}/approve", headers=owner.headers)
    assert r.status_code == 200
    await join(client, col, asker, "please")

    for path in ("", "/members"):
        r = await client.get(f"/collectives/{col}{path}")                         # anonymous
        assert r.status_code == 404, (path, r.text)
        for who in (outsider, asker):
            r = await client.get(f"/collectives/{col}{path}", headers=who.headers)
            assert r.status_code == 404, (who.did, path, r.text)
        for who in (owner, member):
            r = await client.get(f"/collectives/{col}{path}", headers=who.headers)
            assert r.status_code == 200, (who.did, path, r.text)

    r = await client.get(f"/collectives/{col}", headers=member.headers)
    assert r.json()["is_public"] is False
    assert {m["agent_did"] for m in r.json()["members"]} == {owner.did, member.did}
    # the private collective is not in the public list either
    r = await client.get("/collectives?limit=100")
    assert str(col) not in {c["collective_id"] for c in r.json()["collectives"]}


@pytest.mark.asyncio
async def test_public_profile_open_to_all(client, pool, agents):
    owner, outsider = await agents("own"), await agents("out")
    col = await make_collective(pool, owner, is_public=True)
    for headers in ({}, outsider.headers):
        for path in ("", "/members"):
            r = await client.get(f"/collectives/{col}{path}", headers=headers)
            assert r.status_code == 200, (path, r.text)


# ── Removing members ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cannot_remove_admin_but_owner_can(client, pool, agents):
    owner, admin1, admin2, member, asker = [await agents(n) for n in
                                            ("own", "a1", "a2", "mem", "ask")]
    col = await make_collective(pool, owner)
    await make_admin(pool, col, admin1)
    await make_admin(pool, col, admin2)
    await join(client, col, member)
    await client.post(f"/collectives/{col}/members/{member.did}/approve", headers=owner.headers)
    await join(client, col, asker)

    r = await client.delete(f"/collectives/{col}/members/{admin2.did}", headers=admin1.headers)
    assert r.status_code == 403, r.text
    assert (await membership(pool, col, admin2))["status"] == "ACTIVE"

    r = await client.delete(f"/collectives/{col}/members/{owner.did}", headers=admin1.headers)
    assert r.status_code == 422
    assert (await membership(pool, col, owner))["role"] == "OWNER"

    # an ADMIN still manages members: removes an ACTIVE one, rejects a PENDING one
    r = await client.delete(f"/collectives/{col}/members/{member.did}", headers=admin1.headers)
    assert r.status_code == 204, r.text
    r = await client.delete(f"/collectives/{col}/members/{asker.did}", headers=admin1.headers)
    assert r.status_code == 204, r.text
    assert await membership(pool, col, member) is None
    assert await membership(pool, col, asker) is None

    # a MEMBER cannot remove an ADMIN, and an outsider cannot remove anyone
    await join(client, col, member)
    await client.post(f"/collectives/{col}/members/{member.did}/approve", headers=owner.headers)
    r = await client.delete(f"/collectives/{col}/members/{admin2.did}", headers=member.headers)
    assert r.status_code == 403
    r = await client.delete(f"/collectives/{col}/members/{member.did}", headers=asker.headers)
    assert r.status_code == 403
    assert (await membership(pool, col, admin2))["status"] == "ACTIVE"

    r = await client.delete(f"/collectives/{col}/members/{admin2.did}", headers=owner.headers)
    assert r.status_code == 204, r.text
    assert await membership(pool, col, admin2) is None
    # … and an ADMIN may leave on their own
    r = await client.delete(f"/collectives/{col}/members/{admin1.did}", headers=admin1.headers)
    assert r.status_code == 204, r.text
    assert await membership(pool, col, admin1) is None


@pytest.mark.asyncio
async def test_banned_agent_stays_banned(client, pool, agents):
    owner, banned = await agents("own"), await agents("ban")
    col = await make_collective(pool, owner)
    await join(client, col, banned)
    await pool.execute(
        "UPDATE collective_members SET status = 'BANNED' WHERE collective_id = $1 AND agent_did = $2",
        col, banned.did,
    )

    r = await client.delete(f"/collectives/{col}/members/{banned.did}", headers=banned.headers)
    assert r.status_code == 403, r.text
    r = await client.post(f"/collectives/{col}/join", json={"message": "again"},
                          headers=banned.headers)
    assert r.status_code == 403, r.text
    r = await client.post(f"/collectives/{col}/members/{banned.did}/approve", headers=owner.headers)
    assert r.status_code == 404
    row = await membership(pool, col, banned)
    assert row["status"] == "BANNED" and row["role"] == "MEMBER"
    r = await client.get(f"/collectives/{col}/membership", headers=banned.headers)
    assert r.json()["status"] == "BANNED"
    # the OWNER may lift the ban by removing the row; the agent can then ask again
    r = await client.delete(f"/collectives/{col}/members/{banned.did}", headers=owner.headers)
    assert r.status_code == 204
    r = await client.post(f"/collectives/{col}/join", json={}, headers=banned.headers)
    assert r.status_code == 202


# ── One collective per task ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_cannot_be_handed_to_two_collectives(client, pool, agents):
    creator = await agents("creator", START_BALANCE)
    doer = await agents("doer", 0)
    first = await make_collective(pool, doer)
    second = await make_collective(pool, doer)
    task_id = await assigned_task(client, creator, doer)

    r = await client.post(f"/collectives/{first}/tasks", json={"task_id": task_id},
                          headers=doer.headers)
    assert r.status_code == 201, r.text
    r = await client.post(f"/collectives/{second}/tasks", json={"task_id": task_id},
                          headers=doer.headers)
    assert r.status_code == 422, r.text
    assert "another collective" in r.json()["detail"]
    # handing it to the first collective again is harmless
    r = await client.post(f"/collectives/{first}/tasks", json={"task_id": task_id},
                          headers=doer.headers)
    assert r.status_code == 201, r.text

    assert await pool.fetchval(
        "SELECT executor_collective_id FROM tasks WHERE task_id = $1", uuid.UUID(task_id),
    ) == first
    r = await client.get(f"/collectives/{second}/work")
    assert r.status_code == 200 and r.json()["total_tasks"] == 0
    r = await client.get(f"/collectives/{first}/work")
    assert r.json()["total_tasks"] == 1
