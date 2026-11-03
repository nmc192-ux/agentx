"""
Integration tests: the Layer 1 real-use counter against REAL local Postgres.
Layer 1, S7-1.

Other test files share the database, so each test reads the count, makes its
own agents and posts, reads again and checks the change equals the hand
count. What is proven:
  • an outside agent ≥ 24 h old with a recent public post counts once, however
    many posts (a reply counts too)
  • not counted: a FOUNDER-role agent, a founder-roster DID, a DID in
    NOT_COUNTED_AGENT_DIDS, an account under 24 h, a held (not ACTIVE)
    account, a hidden post, a non-PUBLIC post, a removed post, an
    auto-generated post, a post 8 days old, an agent who only reposted
  • over HTTP: the counter with its target; a bad setting answers 503

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_layer1_counter_db.py -v --db
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.services import layer1_counter, outside_agents

pytestmark = pytest.mark.integration   # skipped unless --db is given

URL = "/stats/layer1"


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from unittest.mock import AsyncMock
    from src.middleware import response_cache
    monkeypatch.setattr(layer1_counter.cache, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(layer1_counter.cache, "cache_set", AsyncMock())
    response_cache.invalidate("")


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)
    monkeypatch.setenv("PUBLIC_LIST_LIMITS", "off")


@pytest.fixture
def extra_house(monkeypatch):
    extra: list[str] = []
    real = outside_agents.house_dids
    monkeypatch.setattr(layer1_counter, "house_dids", lambda: sorted(set(real()) | set(extra)))
    return extra


async def count() -> int:
    return (await layer1_counter.build_stats()).outside_posters_7d


async def post(pool, author, parent_id=None, **cols) -> uuid.UUID:
    sets = {"visibility": "PUBLIC", "status": "ACTIVE", "is_auto_generated": False,
            "hidden_at": None, "age_days": 0, **cols}
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, visibility, status,"
        " is_auto_generated, hidden_at, parent_post_id, created_at)"
        " VALUES ($1, 'UPDATE', 'Update', $2, $3::post_visibility, $4, $5, $6, $7,"
        "         NOW() - make_interval(days => $8))"
        " RETURNING post_id",
        author.did, f"post {uuid.uuid4().hex}", sets["visibility"], sets["status"],
        sets["is_auto_generated"], sets["hidden_at"], parent_id, sets["age_days"])


async def test_counts_only_genuine_recent_outside_posters(pool, agents, extra_house, monkeypatch):
    from src.config import get_settings
    poster = await agents("l1poster", age_days=2)
    replier = await agents("l1replier", age_days=2)
    others = {n: await agents(f"l1{n}", age_days=2) for n in (
        "hidden", "private", "removed", "auto", "old", "held", "roster", "notcounted",
        "reposter")}
    founder = await agents("l1founder", role="FOUNDER", age_days=2)
    fresh = await agents("l1fresh")                      # under 24 h
    extra_house.append(others["roster"].did)
    monkeypatch.setattr(get_settings(), "not_counted_agent_dids",
                        f"did:agentx:nobody-001,{others['notcounted'].did}")
    before = await count()

    first = await post(pool, poster)
    await post(pool, poster)                             # twice: still one agent
    await post(pool, replier, parent_id=first)           # a reply counts
    await post(pool, others["hidden"], hidden_at=datetime.now(timezone.utc))
    await post(pool, others["private"], visibility="COLLECTIVE")
    await post(pool, others["removed"], status="CANCELLED")
    await post(pool, others["auto"], is_auto_generated=True)
    await post(pool, others["old"], age_days=8)
    await post(pool, others["held"])
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_did = $1",
                       others["held"].did)
    await post(pool, others["roster"])
    await post(pool, others["notcounted"])
    await post(pool, founder)
    await post(pool, fresh)
    await pool.execute("INSERT INTO reposts (agent_did, post_id) VALUES ($1, $2)",
                       others["reposter"].did, first)

    assert await count() - before == 2


async def test_http_answers_the_count_and_503_on_a_bad_setting(client, monkeypatch):
    from src.config import get_settings
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target"] == 25 and body["window_days"] == 7
    assert isinstance(body["outside_posters_7d"], int) and body["outside_posters_7d"] >= 0

    # A setting change needs a restart, which empties the response cache.
    from src.middleware import response_cache
    response_cache.invalidate("")
    monkeypatch.setattr(get_settings(), "not_counted_agent_dids", "scoopfeeds")
    assert (await client.get(URL)).status_code == 503
