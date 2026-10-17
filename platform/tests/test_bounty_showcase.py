"""
Tests: bounty showcase (Phase C, Sprint 21, BT-4)
═════════════════════════════════════════════════
``GET /markets/bounties/showcase``: 404 and no database read while
ECONOMY_SHOWCASE_ENABLED is off; with it on, the three lists in a fixed shape,
cached, with no private field in the model. Database behaviour (numbers match
the ledger) is in ``tests/integration/test_bounty_showcase_db.py --db``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.middleware import public_list_limit, response_cache
from src.models.markets import (
    BountyShowcase,
    ShowcaseEarner,
    ShowcaseOpenBounty,
    ShowcasePayout,
)
from src.services.markets import showcase_service

client = TestClient(app, raise_server_exceptions=False)
URL = "/markets/bounties/showcase"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _showcase() -> BountyShowcase:
    return BountyShowcase(
        window_days=30,
        open_count=1,
        open_pool_total=100,
        open_bounties=[ShowcaseOpenBounty(
            bounty_id=uuid4(), title="t", capability_required="c", reward_pool=100,
            deadline=NOW, submission_count=2, created_at=NOW)],
        recently_paid=[ShowcasePayout(
            bounty_id=uuid4(), title="t", amount=50, winner_did="did:agentx:w",
            winner_name="W", paid_at=NOW, how="automatic")],
        top_earners=[ShowcaseEarner(
            agent_did="did:agentx:w", display_name="W", earned=50,
            bounty_payouts=1, contract_payouts=0)],
        generated_at=NOW,
    )


@pytest.fixture(autouse=True)
def fresh_cache():
    response_cache.invalidate("")
    yield
    response_cache.invalidate("")


@pytest.fixture
def on(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "economy_showcase_enabled", "true")


# ── The switch ────────────────────────────────────────────────────────────────

def test_ships_off():
    from src.config import Settings
    assert Settings.model_fields["economy_showcase_enabled"].default == "false"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes "])
def test_on_values(value):
    assert showcase_service.showcase_enabled(SimpleNamespace(economy_showcase_enabled=value))


@pytest.mark.parametrize("value", ["", "0", "false", "no", "on", "enabled", None, "tru"])
def test_anything_else_is_off(value):
    assert not showcase_service.showcase_enabled(SimpleNamespace(economy_showcase_enabled=value))


def test_off_answers_404_and_reads_nothing():
    with patch.object(showcase_service, "get_showcase", new=AsyncMock()) as got, \
         patch.object(showcase_service, "build_showcase", new=AsyncMock()) as built:
        resp = client.get(URL)
    assert resp.status_code == 404
    got.assert_not_awaited()
    built.assert_not_awaited()


# ── Served ────────────────────────────────────────────────────────────────────

def test_on_serves_the_three_lists(on):
    with patch.object(showcase_service, "get_showcase",
                      new=AsyncMock(return_value=_showcase())):
        resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"window_days", "open_count", "open_pool_total", "open_bounties",
                         "recently_paid", "top_earners", "generated_at"}
    assert body["recently_paid"][0]["how"] == "automatic"
    assert body["top_earners"][0]["earned"] == 50


def test_showcase_is_not_read_as_a_bounty_id(on):
    """The route sits before /bounties/{bounty_id}: no 422 for 'showcase'."""
    with patch.object(showcase_service, "get_showcase",
                      new=AsyncMock(return_value=_showcase())), \
         patch("src.services.markets.bounty_service.get_bounty", new=AsyncMock()) as get:
        assert client.get(URL).status_code == 200
    get.assert_not_awaited()


def test_no_login_needed(on):
    with patch.object(showcase_service, "get_showcase",
                      new=AsyncMock(return_value=_showcase())):
        assert client.get(URL, headers={}).status_code == 200


def test_anonymous_answers_are_cached_and_rate_limited():
    assert response_cache.CACHED_PATHS[URL] == 60
    assert public_list_limit.is_list_path(URL)


# ── No private fields ─────────────────────────────────────────────────────────

_PRIVATE = {"description", "solution_data", "summary", "wallet_id", "to_wallet",
            "from_wallet", "creator_id", "recipient_id", "submitter_id", "agent_id",
            "transaction_id", "submission_id"}


@pytest.mark.parametrize("model", [BountyShowcase, ShowcaseOpenBounty, ShowcasePayout,
                                   ShowcaseEarner])
def test_models_carry_no_private_field(model):
    assert not set(model.model_fields) & _PRIVATE


# ── Cache ─────────────────────────────────────────────────────────────────────

async def test_a_fresh_cached_copy_skips_the_database():
    cached = _showcase().model_dump(mode="json")
    with patch.object(showcase_service.cache, "cache_get", new=AsyncMock(return_value=cached)), \
         patch.object(showcase_service, "build_showcase", new=AsyncMock()) as built:
        got = await showcase_service.get_showcase()
    built.assert_not_awaited()
    assert got.top_earners[0].agent_did == "did:agentx:w"


async def test_a_miss_builds_and_stores_for_60_seconds():
    fresh = _showcase()
    with patch.object(showcase_service.cache, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(showcase_service.cache, "cache_set", new=AsyncMock()) as stored, \
         patch.object(showcase_service, "build_showcase", new=AsyncMock(return_value=fresh)):
        got = await showcase_service.get_showcase()
    assert got is fresh
    key, value, ttl = stored.await_args.args
    assert key == showcase_service.CACHE_KEY and ttl == 60
    assert value == fresh.model_dump(mode="json")


async def test_an_unreadable_cached_copy_is_rebuilt():
    fresh = _showcase()
    with patch.object(showcase_service.cache, "cache_get",
                      new=AsyncMock(return_value={"junk": 1})), \
         patch.object(showcase_service.cache, "cache_set", new=AsyncMock()), \
         patch.object(showcase_service, "build_showcase", new=AsyncMock(return_value=fresh)):
        assert await showcase_service.get_showcase() is fresh


def test_payout_types_match_the_ledger_writers():
    from src.services import reputation
    assert set(showcase_service.BOUNTY_PAYOUT_TYPES) == set(reputation._BOUNTY_PAYOUT_TYPES)
    assert set(reputation._CONTRACT_PAYOUT_TYPES) <= set(showcase_service.CONTRACT_PAYOUT_TYPES)
