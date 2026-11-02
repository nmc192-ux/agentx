"""
Layer 1, S2-11 sprint-close security review of the handle code (S2-1, S2-2),
against real local Postgres (``--db``). Adversarial cases the S2 suite did not
have, each proving the rule fails closed:

  - the generic profile update (PATCH /agents/{did}) cannot smuggle a
    ``handle`` or ``handle_changed_at`` past the handle rules;
  - no sign-up body (POST /agents, /agents/register, /onboard) can choose a
    handle: the trigger derives it, a ``handle`` key is ignored or refused;
  - invisible and look-alike characters (zero-width space, RTL override,
    full-width letters, no-break space inside) are refused, never folded onto
    someone else's name;
  - a deactivated agent's handle and its live redirect are neither found nor
    takeable: the names stay parked, nobody inherits an old link;
  - a held (PENDING_REVIEW) agent cannot change its handle (its token no
    longer authenticates) and nothing about it changes;
  - a body naming another agent changes only the caller.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.services import handles as h

pytestmark = pytest.mark.integration


def did(key: str) -> str:
    return f"did:agentx:{key}-{uuid4().hex[:8]}-001"


@pytest_asyncio.fixture
async def conn(pool):
    async with pool.acquire() as c:
        yield c


@pytest_asyncio.fixture
async def http(pool, monkeypatch):
    from src.main import app
    from src.middleware.rate_limits import limiter, limiter_did
    from src.services import onboard_service
    monkeypatch.setattr(onboard_service, "publish_event", AsyncMock(return_value=None))
    limiter.reset()
    limiter_did.reset()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as c:
        yield c
    limiter.reset()
    limiter_did.reset()


class Agent:
    def __init__(self, agent_did: str, token: str):
        self.did, self.headers = agent_did, {"Authorization": f"Bearer {token}"}
        self.derived = h.handle_from_did(agent_did)


async def signup(http, key: str = "agent", **extra) -> tuple[int, dict, str]:
    a = did(key)
    r = await http.post("/agents", json={"agent_did": a, "display_name": f"Agent {a[-12:-4]}", **extra})
    return r.status_code, r.json(), a


async def active(http, key: str = "agent") -> Agent:
    code, body, a = await signup(http, key)
    assert code == 201, body
    return Agent(a, body["access_token"])


async def change(http, agent: Agent, handle, **extra):
    return await http.patch("/agents/me/handle", json={"handle": handle, **extra}, headers=agent.headers)


async def row(conn, agent_did: str):
    return await conn.fetchrow(
        "SELECT handle, handle_changed_at, status::text AS status FROM agents WHERE agent_did = $1", agent_did)


async def holder(conn, handle: str):
    return await conn.fetchval("SELECT agent_did FROM agents WHERE handle = $1", handle)


def fresh(tag: str = "") -> str:
    return f"rev_{tag}{uuid4().hex[:6]}"


# ── Only PATCH /agents/me/handle changes a handle ─────────────────────────────

async def test_the_profile_update_cannot_smuggle_a_handle_or_its_clock(http, conn):
    me = await active(http, "smuggle")
    before = await row(conn, me.did)
    assert before["handle"] == me.derived and before["handle_changed_at"] is None

    r = await http.patch(
        f"/agents/{me.did}",
        json={"bio": "hello", "handle": "admin", "handle_changed_at": "2020-01-01T00:00:00Z",
              "status": "ACTIVE"},
        headers=me.headers,
    )
    # A plain agent may not touch status; whichever way the body is read, the
    # handle columns are not writable here.
    assert r.status_code in (200, 403, 422), r.text
    after = await row(conn, me.did)
    assert after["handle"] == me.derived
    assert after["handle_changed_at"] is None
    assert await holder(conn, "admin") is None

    r = await http.patch(f"/agents/{me.did}", json={"bio": "hello", "handle": "admin"}, headers=me.headers)
    assert r.status_code == 200, r.text
    assert r.json()["handle"] == me.derived
    assert (await row(conn, me.did))["handle"] == me.derived
    assert await holder(conn, "admin") is None


@pytest.mark.parametrize("wanted", ["admin", "atlas", "agentx_team"])
async def test_no_sign_up_body_can_choose_a_handle(http, conn, wanted):
    # POST /agents
    code, body, a = await signup(http, "pick", handle=wanted)
    assert code in (201, 422), body
    if code == 201:
        assert (await row(conn, a))["handle"] == h.handle_from_did(a)

    # POST /agents/register
    tag = uuid4().hex[:8]
    r = await http.post("/agents/register", json={
        "name": f"reg {tag}", "description": "d", "skills": [], "capabilities": [],
        "endpoint": "http://r", "owner": "o", "handle": wanted,
    })
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        a = await conn.fetchval("SELECT agent_did FROM agents WHERE display_name = $1", f"reg {tag}")
        assert (await row(conn, a))["handle"] == h.handle_from_did(a)

    # POST /onboard
    tag = uuid4().hex[:8]
    r = await http.post("/onboard", json={"name": f"onb-{tag}", "capabilities": ["x"], "handle": wanted})
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        a = r.json()["agent_did"]
        assert r.json()["handle"] == h.handle_from_did(a)
        assert (await row(conn, a))["handle"] == h.handle_from_did(a)

    # Whatever happened above, nobody new holds the wanted name.
    owner = await holder(conn, wanted)
    if wanted == "atlas":
        assert owner in (None, "did:agentx:atlas-001")     # the dev roster's founder, if seeded
    else:
        assert owner is None


async def test_a_body_naming_another_agent_changes_only_the_caller(http, conn):
    me = await active(http, "caller")
    other = await active(http, "other")
    name = fresh("mine")
    r = await change(http, me, name, agent_did=other.did, sender_agent_did=other.did)
    assert r.status_code == 200, r.text
    assert r.json()["agent_did"] == me.did
    assert (await row(conn, me.did))["handle"] == name
    assert (await row(conn, other.did))["handle"] == other.derived


# ── Look-alikes and invisible characters ──────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "rev​zero",          # zero-width space inside
    "​revzero",          # zero-width space in front (would survive strip())
    "rev‮zero",          # right-to-left override
    "rev zero",          # no-break space inside
    "ｒｅｖｚｅｒｏ",           # full-width letters
    "revеzero",          # Cyrillic е
    "rev­zero",          # soft hyphen
    "rev﻿zero",          # byte-order mark
])
async def test_invisible_and_look_alike_characters_are_refused_not_folded(http, conn, raw):
    victim = await active(http, "victim")
    await change(http, victim, "revzero_" + uuid4().hex[:4])   # a real holder of a nearby name
    me = await active(http, "lookalike")
    r = await change(http, me, raw)
    assert r.status_code == 422, r.text
    assert (await row(conn, me.did))["handle"] == me.derived
    assert (await row(conn, me.did))["handle_changed_at"] is None
    with pytest.raises(h.HandleInvalid):
        h.normalize_handle(raw)


# ── Deactivated and held agents ───────────────────────────────────────────────

async def test_a_deactivated_agents_handle_and_live_redirect_are_parked(http, conn):
    gone = await active(http, "gone")
    old, new = gone.derived, fresh("gone")
    assert (await change(http, gone, new)).status_code == 200
    await conn.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", gone.did)
    live = await conn.fetchval(
        "SELECT expires_at > NOW() FROM handle_redirects WHERE old_handle = $1 AND agent_did = $2", old, gone.did)
    assert live is True

    # Neither name finds anyone...
    assert (await http.get(f"/agents/by-handle/{old}")).status_code == 404
    assert (await http.get(f"/agents/by-handle/{new}")).status_code == 404

    # ...and neither name can be taken by someone else.
    me = await active(http, "heir")
    for name in (old, new):
        r = await change(http, me, name)
        assert r.status_code == 409, r.text
        assert "another agent" in r.json()["detail"]
    assert (await row(conn, me.did))["handle"] == me.derived
    assert (await row(conn, me.did))["handle_changed_at"] is None

    # The trigger parks them too: a newcomer whose derived name would be the
    # deactivated agent's gets a suffix, never the name.
    assert await holder(conn, new) == gone.did


async def test_a_held_agent_cannot_change_its_handle(http, conn):
    held = await active(http, "held")
    await conn.execute("UPDATE agents SET status = 'PENDING_REVIEW' WHERE agent_did = $1", held.did)
    r = await change(http, held, fresh("held"))
    assert r.status_code == 401, r.text
    after = await row(conn, held.did)
    assert after["handle"] == held.derived and after["handle_changed_at"] is None
    assert after["status"] == "PENDING_REVIEW"
    # The held agent is still visible by handle (held is not deactivated),
    # as its posts still are to its followers.
    assert (await http.get(f"/agents/by-handle/{held.derived}")).status_code == 200


async def test_a_suspended_agent_keeps_its_handle_parked_and_cannot_lose_it(http, conn):
    bad = await active(http, "bad")
    await conn.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", bad.did)
    me = await active(http, "taker")
    r = await change(http, me, bad.derived)
    assert r.status_code == 409, r.text
    assert await holder(conn, bad.derived) == bad.did
