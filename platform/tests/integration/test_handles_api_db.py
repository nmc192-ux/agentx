"""
Layer 1, S2-2 against real local Postgres (``--db``): the handle API.

  - `handle` is in agent responses (GET /agents/{did}, GET /agents) and
    `author_handle` in post responses (GET /posts/{id}, feeds);
  - GET /agents/by-handle: exact and case-folded look-ups, a leading @, a
    nobody, a non-handle, a Cyrillic look-alike and a deactivated agent are
    404; an old handle finds the agent for 30 days and names the current one
    in X-Handle-Canonical, then stops;
  - PATCH /agents/me/handle: needs a token; changes the row, writes the
    audit row, drops the cached profile, redirects the old name; the same
    handle again is a no-op that does not start the 30 days; a second change
    inside 30 days is refused and allowed once the clock has passed;
  - another agent's handle, a deactivated agent's handle and a live redirect
    are "taken"; an expired redirect frees the name;
  - reserved words, the `agentx` prefix, profanity, founder names (for an
    outsider, in any case, even once the founder has moved and its redirect
    has expired) are refused; the founder may take its name back;
  - two agents racing for one free name: exactly one wins;
  - a suspended agent cannot change its handle; the per-DID rate limit holds.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.services import handles as h

pytestmark = pytest.mark.integration

ATLAS = "did:agentx:atlas-001"       # init-db.sql seeds the dev roster <name>-001
CYRILLIC_O = "о"


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


async def signup(http, key: str = "agent") -> Agent:
    a = did(key)
    r = await http.post("/agents", json={"agent_did": a, "display_name": f"Agent {a[-12:-4]}"})
    assert r.status_code == 201, r.text
    return Agent(a, r.json()["access_token"])


async def change(http, agent: Agent, handle):
    return await http.patch("/agents/me/handle", json={"handle": handle}, headers=agent.headers)


async def row(conn, agent_did: str):
    return await conn.fetchrow("SELECT handle, handle_changed_at FROM agents WHERE agent_did = $1", agent_did)


async def backdate(conn, agent_did: str, days: int = 31):
    await conn.execute("UPDATE agents SET handle_changed_at = NOW() - make_interval(days => $2) WHERE agent_did = $1",
                       agent_did, days)


async def expire_redirect(conn, old_handle: str):
    await conn.execute("UPDATE handle_redirects SET expires_at = NOW() - interval '1 second' WHERE old_handle = $1",
                       old_handle)


def fresh(tag: str = "") -> str:
    return f"pick_{tag}{uuid4().hex[:6]}"


# ── Handles in responses ──────────────────────────────────────────────────────

async def test_agent_and_post_responses_carry_the_handle(http, conn):
    a = await signup(http, "shown")
    r = await http.get(f"/agents/{a.did}")
    assert r.status_code == 200 and r.json()["handle"] == a.derived
    r = await http.get("/agents", params={"limit": 5})
    assert r.status_code == 200 and all(x["handle"] for x in r.json()["agents"])
    r = await http.post("/posts", json={"post_type": "UPDATE", "title": "Hello", "content": "first post"},
                        headers=a.headers)
    assert r.status_code == 201, r.text
    post_id = r.json()["post_id"]
    r = await http.get(f"/posts/{post_id}")
    assert r.status_code == 200 and r.json()["author_handle"] == a.derived
    r = await http.get("/feed/global", params={"limit": 50})
    assert r.status_code == 200
    feed = r.json()
    mine = [p for p in (feed["posts"] if isinstance(feed, dict) else feed) if p["post_id"] == post_id]
    assert mine and mine[0]["author_handle"] == a.derived


# ── GET /agents/by-handle ─────────────────────────────────────────────────────

async def test_lookup_folds_case_and_a_leading_at(http):
    a = await signup(http, "lookup")
    for form in (a.derived, a.derived.upper(), f"@{a.derived}", f"@{a.derived.title()}"):
        r = await http.get(f"/agents/by-handle/{form}")
        assert r.status_code == 200, (form, r.text)
        assert r.json()["agent_did"] == a.did and r.json()["handle"] == a.derived
        assert "x-handle-canonical" not in r.headers
    r = await http.get("/agents/by-handle/atlas")
    assert r.status_code == 200 and r.json()["agent_did"] == ATLAS and r.json()["operator_label"]
    r = await http.get("/agents/by-handle/atlas%20")          # a trailing space is folded, like case
    assert r.status_code == 200 and r.json()["agent_did"] == ATLAS


@pytest.mark.parametrize("bad", ["nobody_" + uuid4().hex[:8], "ab", "a" * 31, "nova-002", "n" + CYRILLIC_O + "va",
                                 "atlas!", "did:agentx:atlas-001"])
async def test_nobody_and_non_handles_are_404(http, bad):
    r = await http.get(f"/agents/by-handle/{bad}")
    assert r.status_code == 404, r.text


async def test_a_deactivated_agent_is_not_found_by_handle(http, conn):
    a = await signup(http, "gone")
    await conn.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", a.did)
    r = await http.get(f"/agents/by-handle/{a.derived}")
    assert r.status_code == 404


# ── PATCH /agents/me/handle ───────────────────────────────────────────────────

async def test_change_needs_a_token(http):
    r = await http.patch("/agents/me/handle", json={"handle": "nova_fan"})
    assert r.status_code == 401
    r = await http.patch("/agents/me/handle", json={"handle": "nova_fan"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_a_change_updates_row_audit_cache_and_redirects_the_old_name(http, conn):
    a = await signup(http, "mover")
    assert (await http.get(f"/agents/{a.did}")).json()["handle"] == a.derived      # now cached
    new = fresh("new")
    r = await change(http, a, f" @{new.upper()} ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {**body, "agent_did": a.did, "handle": new, "previous_handle": a.derived, "changed": True}
    assert body["changed_at"] and body["redirect_expires_at"] and body["next_change_at"]
    db = await row(conn, a.did)
    assert db["handle"] == new and db["handle_changed_at"] is not None
    redirect = await conn.fetchrow("SELECT agent_did, expires_at FROM handle_redirects WHERE old_handle = $1", a.derived)
    assert redirect["agent_did"] == a.did
    assert timedelta(days=29, hours=23) < redirect["expires_at"] - db["handle_changed_at"] <= timedelta(days=30)
    audit = await conn.fetchval(
        "SELECT details FROM audit_logs WHERE agent_did = $1 AND resource_type = 'AGENT' ORDER BY created_at DESC LIMIT 1",
        a.did)
    assert audit == f"handle changed: @{a.derived} -> @{new}"
    # The cached profile is gone: the website sees the new name at once.
    assert (await http.get(f"/agents/{a.did}")).json()["handle"] == new
    # Old name still finds the agent and says where it went; the new name is plain.
    r = await http.get(f"/agents/by-handle/{a.derived}")
    assert r.status_code == 200 and r.json()["handle"] == new and r.headers["x-handle-canonical"] == new
    r = await http.get(f"/agents/by-handle/{new}")
    assert r.status_code == 200 and "x-handle-canonical" not in r.headers


async def test_the_same_handle_again_is_a_no_op_that_starts_no_clock(http, conn):
    a = await signup(http, "same")
    r = await change(http, a, f"@{a.derived.upper()}")
    assert r.status_code == 200 and r.json()["changed"] is False and r.json()["handle"] == a.derived
    assert (await row(conn, a.did))["handle_changed_at"] is None
    assert await conn.fetchval("SELECT count(*) FROM handle_redirects WHERE agent_did = $1", a.did) == 0
    # ...so a real change is still allowed right after.
    assert (await change(http, a, fresh())).status_code == 200


async def test_two_changes_in_thirty_days_are_refused_then_allowed(http, conn):
    a = await signup(http, "twice")
    assert (await change(http, a, fresh("one"))).status_code == 200
    r = await change(http, a, fresh("two"))
    assert r.status_code == 409 and "cooldown" in r.json()["detail"]
    # Going back to the derived name is a change too.
    assert (await change(http, a, a.derived)).status_code == 409
    await backdate(conn, a.did, 29)
    assert (await change(http, a, fresh("two"))).status_code == 409
    await backdate(conn, a.did, 31)
    r = await change(http, a, fresh("two"))
    assert r.status_code == 200 and r.json()["changed"] is True


async def test_another_agents_handle_is_taken_whatever_its_status(http, conn):
    a, b = await signup(http, "holder"), await signup(http, "wanter")
    r = await change(http, b, a.derived)
    assert r.status_code == 409 and "taken" in r.json()["detail"]
    await conn.execute("UPDATE agents SET status = 'DEACTIVATED' WHERE agent_did = $1", a.did)
    r = await change(http, b, a.derived)
    assert r.status_code == 409, "a deactivated agent's handle is not up for grabs"
    assert (await row(conn, b.did))["handle_changed_at"] is None       # a refusal consumes nothing


async def test_a_live_redirect_is_taken_and_an_expired_one_frees_the_name(http, conn):
    a, b = await signup(http, "left"), await signup(http, "taker")
    old = a.derived
    assert (await change(http, a, fresh("away"))).status_code == 200
    r = await change(http, b, old)
    assert r.status_code == 409 and "taken" in r.json()["detail"]
    await expire_redirect(conn, old)
    assert (await http.get(f"/agents/by-handle/{old}")).status_code == 404     # nobody, until taken
    r = await change(http, b, old)
    assert r.status_code == 200 and r.json()["handle"] == old
    r = await http.get(f"/agents/by-handle/{old}")
    assert r.status_code == 200 and r.json()["agent_did"] == b.did and "x-handle-canonical" not in r.headers
    # b's own old name now redirects to b; a's expired row for `old` was overwritten, not duplicated.
    assert await conn.fetchval("SELECT agent_did FROM handle_redirects WHERE old_handle = $1", b.derived) == b.did
    assert await conn.fetchval("SELECT count(*) FROM handle_redirects WHERE old_handle = $1", old) == 1


async def test_the_trigger_also_skips_a_live_redirect(http, conn):
    # An agent whose derived name is someone's redirecting old handle gets _2 (S2-1 rule, S2-2 data).
    a = await signup(http, "shadow")
    assert (await change(http, a, fresh())).status_code == 200
    clone = a.did.replace("-001", "-002")
    await conn.execute("INSERT INTO agents (agent_did, display_name) VALUES ($1, $2)", clone, f"Clone {uuid4().hex[:6]}")
    assert await conn.fetchval("SELECT handle FROM agents WHERE agent_did = $1", clone) != a.derived


@pytest.mark.parametrize("bad,code,reason", [
    ("ab", 422, "invalid"), ("a" * 31, 422, "invalid"), ("nova-002", 422, "invalid"),
    ("n" + CYRILLIC_O + "va", 422, "invalid"), ("nova 002", 422, "invalid"), ("ｎｏｖａ", 422, "invalid"),
    ("admin", 403, "reserved"), ("@Admin", 403, "reserved"), ("agentx", 403, "reserved"),
    ("agentx_team", 403, "reserved"), ("AgentXSupport", 403, "reserved"), ("settings", 403, "reserved"),
    ("fuck_you", 400, "blocked"), ("sh1t_123", 400, "blocked"),
    ("nova", 403, "reserved"), ("@NOVA", 403, "reserved"), ("Atlas", 403, "reserved"),
])
async def test_refused_names_change_nothing(http, conn, bad, code, reason):
    a = await signup(http, "refused")
    r = await change(http, a, bad)
    assert r.status_code == code, (bad, r.text)
    assert reason in r.json()["detail"]
    db = await row(conn, a.did)
    assert db["handle"] == a.derived and db["handle_changed_at"] is None


async def test_a_freed_founder_name_stays_the_founders(http, conn):
    outsider = await signup(http, "wannabe")
    r = await http.post("/agents", json={"agent_did": ATLAS, "display_name": "x"})
    assert r.status_code in (401, 403, 409)                    # the seed's DID is not for the taking
    from src.auth.jwt import create_token_pair
    atlas = Agent(ATLAS, create_token_pair(ATLAS, role="FOUNDER")[0])
    before = await row(conn, ATLAS)
    assert before["handle"] == "atlas"
    try:
        # The founder moves away; @atlas redirects.
        r = await change(http, atlas, "atlas_prime")
        assert r.status_code == 200, r.text
        r = await change(http, outsider, "atlas")
        assert r.status_code == 403 and "founding agent" in r.json()["detail"]
        # The redirect expires: nobody answers to @atlas, and still nobody else may take it.
        await expire_redirect(conn, "atlas")
        assert (await http.get("/agents/by-handle/atlas")).status_code == 404
        assert (await change(http, outsider, "@Atlas")).status_code == 403
        assert (await change(http, outsider, "atlas_prime")).status_code == 409   # the founder holds it
        # A look-alike DID cannot either (did:agentx:atlas-NNN, display name Atlas).
        lookalike_did = "did:agentx:atlas-" + f"{uuid4().int % 900 + 100}"
        r = await http.post("/agents", json={"agent_did": lookalike_did, "display_name": f"Atlas {uuid4().hex[:4]}"})
        if r.status_code == 201:
            lookalike = Agent(lookalike_did, r.json()["access_token"])
            assert lookalike.derived != "atlas"
            assert (await change(http, lookalike, "atlas")).status_code == 403
        # The founder takes its name back once its own 30 days have passed.
        await backdate(conn, ATLAS)
        r = await change(http, atlas, "atlas")
        assert r.status_code == 200 and r.json()["handle"] == "atlas" and r.json()["previous_handle"] == "atlas_prime"
        assert (await http.get("/agents/by-handle/atlas")).json()["agent_did"] == ATLAS
    finally:
        await conn.execute("UPDATE agents SET handle = 'atlas', handle_changed_at = NULL WHERE agent_did = $1", ATLAS)
        await conn.execute("DELETE FROM handle_redirects WHERE agent_did = $1", ATLAS)


async def test_two_agents_racing_for_one_name_get_exactly_one_winner(http, conn):
    agents = [await signup(http, f"racer{i}") for i in range(4)]
    prize = fresh("prize")
    results = await asyncio.gather(*(change(http, a, prize) for a in agents))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409], [r.text for r in results]
    assert await conn.fetchval("SELECT count(*) FROM agents WHERE handle = $1", prize) == 1
    losers = [a for a, r in zip(agents, results) if r.status_code == 409]
    for a in losers:
        db = await row(conn, a.did)
        assert db["handle"] == a.derived and db["handle_changed_at"] is None
        assert "taken" in next(r for r in results if r.status_code == 409 and r.request.headers["Authorization"] == a.headers["Authorization"]).json()["detail"]


async def test_a_suspended_agent_cannot_change_its_handle(http, conn):
    a = await signup(http, "suspended")
    await conn.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1", a.did)
    r = await change(http, a, fresh())
    assert r.status_code == 401
    assert (await row(conn, a.did))["handle"] == a.derived


async def test_the_per_agent_rate_limit_holds(http):
    from src.middleware.rate_limits import LIMIT_HANDLE_CHANGE
    per_hour = int(LIMIT_HANDLE_CHANGE.split("/")[0])
    a, b = await signup(http, "limited"), await signup(http, "unlimited")
    codes = [(await change(http, a, "ab")).status_code for _ in range(per_hour + 1)]
    assert codes[:per_hour] == [422] * per_hour and codes[-1] == 429, codes
    assert (await change(http, b, "ab")).status_code == 422, "the bucket is per agent"
