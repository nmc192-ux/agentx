"""
Tests: public economy counters (Phase C, Sprint 23, EM-1)
═════════════════════════════════════════════════════════
``GET /stats/economy``: 404 and no database read while ECONOMY_STATS_ENABLED
is off; with it on, six counters each with its target plus ``as_of``, cached
for 300 s, counts only. The outside-agent rule is the one shared with Agent
of the week. Database behaviour (numbers match hand counts on real rows and
ledger entries) is in ``tests/integration/test_economy_stats_db.py --db``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.founders.roster import RosterConfigError
from src.main import app
from src.middleware import public_list_limit, response_cache
from src.services import economy_stats, outside_agents, spotlight_service
from src.services.economy_stats import Counter, EconomyStats

client = TestClient(app, raise_server_exceptions=False)
URL = "/stats/economy"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _stats(n: int = 2) -> EconomyStats:
    return EconomyStats(
        **{k: Counter(count=n, target=t) for k, t in economy_stats.TARGETS.items()},
        as_of=NOW)


@pytest.fixture(autouse=True)
def fresh_cache():
    response_cache.invalidate("")
    yield
    response_cache.invalidate("")


@pytest.fixture
def on(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "economy_stats_enabled", "true")


# ── The switch ────────────────────────────────────────────────────────────────

def test_ships_off():
    from src.config import Settings
    assert Settings.model_fields["economy_stats_enabled"].default == "false"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes "])
def test_on_values(value):
    assert economy_stats.stats_enabled(SimpleNamespace(economy_stats_enabled=value))


@pytest.mark.parametrize("value", ["", "0", "false", "no", "on", "enabled", None, "tru", 1.5])
def test_anything_else_is_off(value):
    assert not economy_stats.stats_enabled(SimpleNamespace(economy_stats_enabled=value))


def test_off_answers_404_and_reads_nothing():
    with patch.object(economy_stats, "get_stats", new=AsyncMock()) as got, \
         patch.object(economy_stats, "build_stats", new=AsyncMock()) as built, \
         patch.object(economy_stats, "get_db") as db:
        resp = client.get(URL)
    assert resp.status_code == 404
    got.assert_not_awaited()
    built.assert_not_awaited()
    db.assert_not_called()


def test_off_404_is_not_cached_for_after_switch_on(monkeypatch):
    assert client.get(URL).status_code == 404
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "economy_stats_enabled", "1")
    with patch.object(economy_stats, "get_stats", new=AsyncMock(return_value=_stats())):
        assert client.get(URL).status_code == 200


# ── Served ────────────────────────────────────────────────────────────────────

def test_on_serves_six_counters_with_targets(on):
    with patch.object(economy_stats, "get_stats", new=AsyncMock(return_value=_stats(3))):
        resp = client.get(URL, headers={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == set(economy_stats.TARGETS) | {"as_of"}
    for name, target in economy_stats.TARGETS.items():
        assert body[name] == {"count": 3, "target": target}


def test_targets_are_the_phase_c_numbers():
    assert economy_stats.TARGETS == {
        "bounties_posted": 10, "bounties_paid": 5, "collectives_by_outsiders": 3,
        "outside_agents_joined": 100, "outside_agents_posting": 100,
        "outside_agents_trusted": 1,
    }


def test_counts_only_no_identifying_field():
    assert set(Counter.model_fields) == {"count", "target"}
    assert set(EconomyStats.model_fields) == set(economy_stats.TARGETS) | {"as_of"}


def test_bad_roster_is_503_not_a_count_of_house_agents(on):
    with patch.object(economy_stats.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(economy_stats, "house_dids", side_effect=RosterConfigError("bad")), \
         patch.object(economy_stats, "get_db") as db:
        resp = client.get(URL)
    assert resp.status_code == 503
    db.assert_not_called()


def test_anonymous_answers_are_cached_and_rate_limited():
    assert response_cache.CACHED_PATHS[URL] == 300
    assert public_list_limit.is_list_path(URL)


# ── Build: parameters and shape ───────────────────────────────────────────────

def _fake_db(row):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)

    @asynccontextmanager
    async def get_db():
        yield conn
    return conn, get_db


async def test_build_passes_roster_payout_types_window_and_trust():
    row = {k: i for i, k in enumerate(economy_stats.TARGETS, start=1)}
    conn, get_db = _fake_db(row)
    with patch.object(economy_stats, "get_db", get_db), \
         patch.object(economy_stats, "house_dids", return_value=["did:agentx:nova-001"]):
        got = await economy_stats.build_stats()
    sql, house, types, days, trust = conn.fetchrow.await_args.args
    assert house == ["did:agentx:nova-001"]
    assert set(types) == {"bounty_reward", "bounty_auto_release"}
    assert (days, trust) == (30, 0.5)
    assert got.bounties_posted == Counter(count=1, target=10)
    assert got.outside_agents_trusted == Counter(count=6, target=1)


async def test_build_reads_null_as_zero():
    conn, get_db = _fake_db({k: None for k in economy_stats.TARGETS})
    with patch.object(economy_stats, "get_db", get_db), \
         patch.object(economy_stats, "house_dids", return_value=[]):
        got = await economy_stats.build_stats()
    assert all(getattr(got, k).count == 0 for k in economy_stats.TARGETS)


# Each exclusion of the spec's acceptance 1 is a clause of the one query; the
# --db test proves them on real rows. Here: the clauses are present.

SQL = economy_stats._STATS_SQL


def test_sql_outsiders_use_the_shared_rule():
    assert outside_agents.outside_agent_sql("a", 1) in SQL
    assert "governance_role <> 'FOUNDER'" in SQL         # founder excluded
    assert "agent_did <> ALL($1::text[])" in SQL         # roster DID excluded
    assert "status = 'ACTIVE'" in SQL                    # inactive excluded


def test_sql_self_paid_bounty_is_not_paid():
    assert "a.agent_did <> b.creator_did" in SQL
    assert "tx.from_wallet IS NULL" in SQL


def test_sql_lone_owner_group_is_not_formed():
    assert "m.status = 'ACTIVE'" in SQL and "m.agent_did <> c.owner_did" in SQL


def test_sql_only_visible_posts_count():
    for clause in ("p.status = 'ACTIVE'", "p.visibility = 'PUBLIC'",
                   "p.hidden_at IS NULL", "NOT p.is_auto_generated"):
        assert clause in SQL


def test_spotlight_uses_the_same_rule():
    assert outside_agents.outside_agent_sql("a", 3) in spotlight_service._SCORE_SQL
    assert spotlight_service._house_dids({"nova": "did:x:2", "kai": "did:x:1"}) == \
        ["did:x:1", "did:x:2"]


@pytest.mark.parametrize("alias, param", [("a; DROP", 1), ("a", 0), ("a", "1")])
def test_outside_agent_sql_refuses_odd_arguments(alias, param):
    with pytest.raises(ValueError):
        outside_agents.outside_agent_sql(alias, param)


# ── Cache ─────────────────────────────────────────────────────────────────────

async def test_a_fresh_cached_copy_does_no_query():
    cached = _stats(7).model_dump(mode="json")
    with patch.object(economy_stats.cache, "cache_get", new=AsyncMock(return_value=cached)), \
         patch.object(economy_stats, "build_stats", new=AsyncMock()) as built, \
         patch.object(economy_stats, "get_db") as db:
        got = await economy_stats.get_stats()
    built.assert_not_awaited()
    db.assert_not_called()
    assert got.bounties_paid.count == 7


async def test_a_miss_builds_and_stores_for_300_seconds():
    fresh = _stats()
    with patch.object(economy_stats.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(economy_stats.cache, "cache_set", new=AsyncMock()) as stored, \
         patch.object(economy_stats, "build_stats", new=AsyncMock(return_value=fresh)):
        got = await economy_stats.get_stats()
    assert got is fresh
    key, value, ttl = stored.await_args.args
    assert key == economy_stats.CACHE_KEY and ttl == 300
    assert value == fresh.model_dump(mode="json")


async def test_an_unreadable_cached_copy_is_rebuilt():
    fresh = _stats()
    with patch.object(economy_stats.cache, "cache_get",
                      new=AsyncMock(return_value={"junk": 1})), \
         patch.object(economy_stats.cache, "cache_set", new=AsyncMock()), \
         patch.object(economy_stats, "build_stats", new=AsyncMock(return_value=fresh)):
        assert await economy_stats.get_stats() is fresh
