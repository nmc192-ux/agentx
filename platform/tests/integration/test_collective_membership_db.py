"""
Integration tests: collective membership reads, against REAL local Postgres.
Phase C, Sprint 22, CL-2.

What is proven (HTTP → router → Postgres, schema from init-db.sql + alembic head):
  • a join request keeps its message; a repeat request does not overwrite it
  • the OWNER and an ACTIVE ADMIN see pending requests (oldest first, with the
    message); a MEMBER, an outsider and the requester themselves get 403
  • after approval the request is gone from the list and the member's own
    membership reads ACTIVE; after leaving it reads "none"
  • a private collective is 404 to outsiders on both reads
  • approving a DID with no PENDING row is still 404

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_collective_membership_db.py -v --db
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given


async def make_collective(pool, owner, is_public=True) -> uuid.UUID:
    col = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO collectives (collective_id, name, description, is_public, owner_did)"
            " VALUES ($1, $2, 'a group', $3, $4)",
            col, f"G-{col.hex[:8]}", is_public, owner.did,
        )
        await conn.execute(
            "INSERT INTO collective_members (collective_id, agent_did, role, status)"
            " VALUES ($1, $2, 'OWNER', 'ACTIVE')",
            col, owner.did,
        )
    return col


async def join(client, col, agent, message=None):
    body = {} if message is None else {"message": message}
    resp = await client.post(f"/collectives/{col}/join", json=body, headers=agent.headers)
    assert resp.status_code == 202, resp.text


async def make_admin(pool, col, agent):
    await pool.execute(
        "INSERT INTO collective_members (collective_id, agent_did, role, status)"
        " VALUES ($1, $2, 'ADMIN', 'ACTIVE')", col, agent.did,
    )


@pytest.mark.asyncio
async def test_requests_and_membership_lifecycle(client, pool, agents):
    owner, admin, member, c, d, outsider = [await agents(n) for n in
                                            ("own", "adm", "mem", "c", "d", "out")]
    col = await make_collective(pool, owner)
    await make_admin(pool, col, admin)

    # member joins and is approved first, so it is an ACTIVE MEMBER
    await join(client, col, member)
    resp = await client.post(f"/collectives/{col}/members/{member.did}/approve",
                             headers=owner.headers)
    assert resp.status_code == 200

    await join(client, col, c, "  I review Python code ")
    await join(client, col, d)
    await join(client, col, c, "second message must not overwrite")   # repeat: no change

    # own membership
    r = await client.get(f"/collectives/{col}/membership", headers=c.headers)
    assert r.status_code == 200
    assert (r.json()["role"], r.json()["status"]) == ("MEMBER", "PENDING")
    r = await client.get(f"/collectives/{col}/membership", headers=outsider.headers)
    assert r.json()["status"] == "none" and r.json()["role"] is None
    r = await client.get(f"/collectives/{col}/membership", headers=owner.headers)
    assert (r.json()["role"], r.json()["status"]) == ("OWNER", "ACTIVE")
    assert (await client.get(f"/collectives/{col}/membership")).status_code == 401

    # who may read requests
    for who in (owner, admin):
        r = await client.get(f"/collectives/{col}/requests", headers=who.headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [x["agent_did"] for x in body] == [c.did, d.did]
        assert body[0]["message"] == "I review Python code"
        assert body[1]["message"] is None
        assert body[0]["requested_at"] and body[0]["trust_score"] == 0.5
    for who in (member, outsider, c):
        r = await client.get(f"/collectives/{col}/requests", headers=who.headers)
        assert r.status_code == 403, (who.did, r.text)
    assert (await client.get(f"/collectives/{col}/requests")).status_code == 401

    # ADMIN approves C → gone from requests, C is ACTIVE
    r = await client.post(f"/collectives/{col}/members/{c.did}/approve", headers=admin.headers)
    assert r.status_code == 200
    r = await client.get(f"/collectives/{col}/requests", headers=owner.headers)
    assert [x["agent_did"] for x in r.json()] == [d.did]
    r = await client.get(f"/collectives/{col}/membership", headers=c.headers)
    assert r.json()["status"] == "ACTIVE"

    # approving someone with no PENDING row stays 404 (already ACTIVE, never asked)
    for did in (c.did, outsider.did):
        r = await client.post(f"/collectives/{col}/members/{did}/approve", headers=owner.headers)
        assert r.status_code == 404

    # C leaves → none
    r = await client.delete(f"/collectives/{col}/members/{c.did}", headers=c.headers)
    assert r.status_code == 204
    r = await client.get(f"/collectives/{col}/membership", headers=c.headers)
    assert r.json()["status"] == "none"


@pytest.mark.asyncio
async def test_private_collective_hidden_from_outsiders(client, pool, agents):
    owner, outsider, asker = [await agents(n) for n in ("own", "out", "ask")]
    col = await make_collective(pool, owner, is_public=False)
    await join(client, col, asker, "let me in")

    for who in (outsider, asker):
        for path in ("requests", "membership"):
            r = await client.get(f"/collectives/{col}/{path}", headers=who.headers)
            assert r.status_code == 404, (who.did, path, r.text)

    r = await client.get(f"/collectives/{col}/requests", headers=owner.headers)
    assert r.status_code == 200
    assert [(x["agent_did"], x["message"]) for x in r.json()] == [(asker.did, "let me in")]


@pytest.mark.asyncio
async def test_missing_collective_404(client, agents):
    a = await agents("a")
    for path in ("requests", "membership"):
        r = await client.get(f"/collectives/{uuid.uuid4()}/{path}", headers=a.headers)
        assert r.status_code == 404
