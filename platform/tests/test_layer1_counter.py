"""
Tests: Layer 1 real-use counter (S7-1)
══════════════════════════════════════
``GET /stats/layer1``: always on, public, cached; ``NOT_COUNTED_AGENT_DIDS``
parsed strictly and a bad value (or a bad founder roster) answers 503,
never a count. Database behaviour is in
``tests/integration/test_layer1_counter_db.py --db``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.founders.roster import RosterConfigError
from src.main import app
from src.middleware import public_list_limit, response_cache
from src.services import layer1_counter
from src.services.layer1_counter import Layer1Stats, NotCountedConfigError, parse_not_counted

client = TestClient(app, raise_server_exceptions=False)
URL = "/stats/layer1"
NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _stats(n: int = 3) -> Layer1Stats:
    return Layer1Stats(outside_posters_7d=n, target=25, window_days=7, as_of=NOW)


@pytest.fixture(autouse=True)
def fresh_cache():
    response_cache.invalidate("")
    yield
    response_cache.invalidate("")


# ── The setting ───────────────────────────────────────────────────────────────

def test_setting_ships_empty():
    from src.config import Settings
    assert Settings.model_fields["not_counted_agent_dids"].default == ""


@pytest.mark.parametrize("raw, want", [
    ("", []),
    (None, []),
    ("did:agentx:scoop-001", ["did:agentx:scoop-001"]),
    (" did:agentx:b-002 ,\ndid:agentx:a-001,, did:agentx:b-002 ",
     ["did:agentx:a-001", "did:agentx:b-002"]),
])
def test_parse_good_values(raw, want):
    assert parse_not_counted(raw) == want


@pytest.mark.parametrize("raw", [
    "scoop-001",
    "did:agentx:Scoop-001",
    "did:agentx:scoop",
    "did:agentx:scoop-001 did:agentx:other-002",      # space is not a separator
    "did:agentx:scoop-001;did:agentx:other-002",
    "did:agentx:scoop-001,did:web:example.com",
    "did:agentx:scoop-001'--",
])
def test_one_bad_entry_rejects_the_whole_value(raw):
    with pytest.raises(NotCountedConfigError):
        parse_not_counted(raw)


def test_too_many_entries_rejected():
    raw = ",".join(f"did:agentx:a{i}-001" for i in range(layer1_counter.MAX_NOT_COUNTED + 1))
    with pytest.raises(NotCountedConfigError):
        parse_not_counted(raw)


def test_not_text_rejected():
    with pytest.raises(NotCountedConfigError):
        layer1_counter.not_counted_dids(SimpleNamespace(not_counted_agent_dids=["did:agentx:a-001"]))


# ── The route ────────────────────────────────────────────────────────────────

def test_always_on_and_counts_only():
    with patch.object(layer1_counter, "build_stats", new=AsyncMock(return_value=_stats(4))), \
         patch.object(layer1_counter.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(layer1_counter.cache, "cache_set", new=AsyncMock()):
        resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"outside_posters_7d", "target", "window_days", "as_of"}
    assert body["outside_posters_7d"] == 4 and body["target"] == 25 and body["window_days"] == 7


def test_bad_not_counted_setting_is_503_and_reads_nothing(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "not_counted_agent_dids", "not-a-did")
    with patch.object(layer1_counter, "build_stats", new=AsyncMock()) as built, \
         patch.object(layer1_counter.cache, "cache_get",
                      new=AsyncMock(return_value=_stats(9).model_dump(mode="json"))) as got:
        resp = client.get(URL)
    assert resp.status_code == 503
    assert "NOT_COUNTED_AGENT_DIDS" in resp.json()["detail"]
    built.assert_not_awaited()
    got.assert_not_awaited()          # not even a cached count from before


def test_bad_founder_roster_is_503():
    with patch.object(layer1_counter, "house_dids", side_effect=RosterConfigError("bad")), \
         patch.object(layer1_counter, "build_stats", new=AsyncMock()) as built:
        resp = client.get(URL)
    assert resp.status_code == 503
    built.assert_not_awaited()


def test_503_is_not_cached_by_the_response_cache(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "not_counted_agent_dids", "bad")
    assert client.get(URL).status_code == 503
    monkeypatch.setattr(get_settings(), "not_counted_agent_dids", "")
    with patch.object(layer1_counter, "build_stats", new=AsyncMock(return_value=_stats(1))), \
         patch.object(layer1_counter.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(layer1_counter.cache, "cache_set", new=AsyncMock()):
        assert client.get(URL).status_code == 200


async def test_get_stats_uses_the_cache():
    with patch.object(layer1_counter.cache, "cache_get",
                      new=AsyncMock(return_value=_stats(7).model_dump(mode="json"))), \
         patch.object(layer1_counter, "build_stats", new=AsyncMock()) as built:
        got = await layer1_counter.get_stats()
    assert got.outside_posters_7d == 7
    built.assert_not_awaited()


async def test_get_stats_rebuilds_and_stores_on_miss():
    with patch.object(layer1_counter.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(layer1_counter.cache, "cache_set", new=AsyncMock()) as stored, \
         patch.object(layer1_counter, "build_stats", new=AsyncMock(return_value=_stats(2))):
        got = await layer1_counter.get_stats()
    assert got.outside_posters_7d == 2
    key, value, ttl = stored.await_args.args
    assert key == layer1_counter.CACHE_KEY and ttl == layer1_counter.CACHE_TTL
    assert value["outside_posters_7d"] == 2


def test_public_rate_limit_and_cache_cover_the_route():
    assert public_list_limit.is_list_path(URL)
    assert response_cache.CACHED_PATHS[URL] == 300


def test_sql_uses_the_shared_outside_rule():
    sql = layer1_counter._COUNT_SQL
    assert "governance_role <> 'FOUNDER'" in sql and "status = 'ACTIVE'" in sql
    assert "reposts" not in sql
