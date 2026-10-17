"""
Integration tests: GET /agents/follow-status against REAL local Postgres.
EG-6 (Neon egress).

The website used to learn "do I follow X?" by downloading X's first 50
followers (full agent rows with bios) and searching them, which also gave the
wrong answer once X had more than 50 followers. The new call ships one DID per
followed agent and nothing else.

What is proven:
  • the answer is the subset of the asked DIDs the caller follows, in the
    order asked, duplicates collapsed
  • it is right when the caller is follower number 51+ (the old way was not)
  • it only answers for the caller: someone else's follows do not count
  • the DB returns one short column per match, no agent rows
  • no login → 401; more than 100 DIDs → 422; no DIDs → 422

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.integration   # skipped unless --db is given

URL = "/agents/follow-status"


async def _follow(pool, follower, following, minutes_ago=0):
    await pool.execute(
        "INSERT INTO follows (follower_did, following_did, created_at) "
        "VALUES ($1, $2, now() - make_interval(mins => $3))",
        follower.did, following.did, minutes_ago,
    )


async def test_returns_followed_subset_in_order(client, pool, agents):
    me, a, b, c = [await agents(n) for n in ("me", "a", "b", "c")]
    await _follow(pool, me, a)
    await _follow(pool, me, c)
    await _follow(pool, b, me)          # b follows me; I do not follow b

    r = await client.get(URL, params={"did": [c.did, b.did, a.did, c.did]}, headers=me.headers)
    assert r.status_code == 200
    assert r.json() == {"following": [c.did, a.did]}


async def test_right_past_the_first_page_of_followers(client, pool, agents):
    star, me = await agents("star"), await agents("me")
    # I followed first, so 55 newer followers push me off the 50-row page
    # the website used to search.
    await _follow(pool, me, star, minutes_ago=100)
    for i in range(55):
        await _follow(pool, await agents(f"fan{i}"), star)

    page = (await client.get(f"/agents/{star.did}/followers", params={"limit": 50})).json()
    assert me.did not in [x["agent_did"] for x in page["agents"]]

    r = await client.get(URL, params={"did": star.did}, headers=me.headers)
    assert r.json() == {"following": [star.did]}


async def test_answers_only_for_the_caller(client, pool, agents):
    me, other, target = [await agents(n) for n in ("me", "other", "target")]
    await _follow(pool, other, target)
    r = await client.get(URL, params={"did": target.did}, headers=me.headers)
    assert r.json() == {"following": []}


async def test_db_ships_only_the_matching_dids(client, pool, agents, monkeypatch):
    me = await agents("me")
    others = [await agents(f"o{i}") for i in range(5)]
    for o in others[:3]:
        await _follow(pool, me, o)

    seen: list[asyncpg.Record] = []
    real_fetch = asyncpg.Connection.fetch

    async def fetch(self, *a, **kw):
        rows = await real_fetch(self, *a, **kw)
        seen.extend(rows)
        return rows

    monkeypatch.setattr(asyncpg.Connection, "fetch", fetch)
    r = await client.get(URL, params={"did": [o.did for o in others]}, headers=me.headers)
    assert len(r.json()["following"]) == 3
    assert len(seen) == 3
    assert all(list(row.keys()) == ["following_did"] for row in seen)


async def test_needs_login(client, pool, agents):
    target = await agents("target")
    r = await client.get(URL, params={"did": target.did})
    assert r.status_code == 401


async def test_bounded_and_required(client, pool, agents):
    me = await agents("me")
    too_many = [f"did:agentx:x{i}" for i in range(101)]
    r = await client.get(URL, params={"did": too_many}, headers=me.headers)
    assert r.status_code == 422
    r = await client.get(URL, headers=me.headers)
    assert r.status_code == 422
    # 100 is fine (duplicates collapse first)
    r = await client.get(URL, params={"did": too_many[:100] + too_many[:5]}, headers=me.headers)
    assert r.status_code == 200
