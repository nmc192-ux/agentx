"""
Tests: the token faucet (Phase C, Sprint 20, FC-1) — route and helpers.

`POST /wallets/faucet` mints a fixed amount into the CALLER's wallet, once
per UTC day, while the faucet is on and the daily budget lasts. These tests
cover the parts that need no database: the on/off switch, the UTC day
arithmetic, the refusal → HTTP mapping, that the route is 404 while off,
401 without a login, and that nothing in the request body can choose who
is paid. The money itself (one credit, concurrent claims, the budget, the
ledger and supply rows) is proven against real Postgres in
tests/integration/test_faucet_db.py (--db).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import app
from src.models.token import FaucetClaimResponse
from src.services import faucet_service
from src.services.faucet_service import FaucetRefused, faucet_enabled, next_utc_day

CALLER_DID = "did:agentx:newcomer-001"
CALLER_ID = uuid4()
VICTIM_ID = uuid4()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def authed():
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord, get_current_agent
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = CALLER_DID
    caller = AgentRecord(
        row={
            "agent_did": CALLER_DID, "display_name": "Newcomer", "governance_role": "MEMBER",
            "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5,
        },
        claims=claims,
    )
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        yield caller
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


@pytest.fixture
def faucet_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "faucet_enabled", "true")
    monkeypatch.setattr(settings, "faucet_amount", 25)
    monkeypatch.setattr(settings, "faucet_daily_budget", 2000)
    return settings


@pytest.fixture
def faucet_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "faucet_enabled", "false")


@pytest.fixture
def caller_resolves(monkeypatch):
    """The DID → UUID lookup, without a database."""
    monkeypatch.setattr(
        "src.routers.tokens._caller_agent_id", AsyncMock(return_value=CALLER_ID),
    )


def _response(agent_id=CALLER_ID, amount=25, balance=25) -> FaucetClaimResponse:
    now = datetime.now(timezone.utc)
    return FaucetClaimResponse(
        claim_id=uuid4(), agent_id=agent_id, wallet_id=uuid4(), amount=amount,
        balance=balance, claim_day=now.date(), next_claim_at=next_utc_day(now),
        transaction_id=uuid4(),
    )


# ── The switch ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["1", "true", "yes", "TRUE", " True "])
def test_faucet_is_on_for_the_accepted_spellings(flag):
    assert faucet_enabled(SimpleNamespace(faucet_enabled=flag, faucet_amount=25, faucet_daily_budget=2000))


@pytest.mark.parametrize("flag", ["", "false", "0", "no", "yse", "on", None, "enabled"])
def test_faucet_is_off_for_anything_else(flag):
    assert not faucet_enabled(SimpleNamespace(faucet_enabled=flag, faucet_amount=25, faucet_daily_budget=2000))


def test_faucet_is_off_by_default():
    assert get_settings().faucet_enabled == "false"
    assert not faucet_enabled(get_settings())


@pytest.mark.parametrize("amount,budget", [(0, 2000), (-5, 2000), (25, 0), (25, -1), ("x", 2000)])
def test_zero_amount_or_budget_means_off(amount, budget):
    assert not faucet_enabled(SimpleNamespace(faucet_enabled="true", faucet_amount=amount, faucet_daily_budget=budget))


def test_defaults_match_the_sprint_spec():
    s = get_settings()
    assert (s.faucet_amount, s.faucet_balance_ceiling, s.faucet_min_age_minutes, s.faucet_daily_budget) == (25, 100, 60, 2000)


# ── UTC day arithmetic ────────────────────────────────────────────────────────

def test_next_claim_day_starts_at_utc_midnight():
    now = datetime(2026, 11, 2, 23, 59, 59, tzinfo=timezone.utc)
    assert next_utc_day(now) == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert faucet_service.claim_day(now) == date(2026, 11, 2)


def test_day_is_counted_in_utc_not_local_time():
    # 03:30 in Karachi (UTC+5) is still the previous day in UTC.
    karachi = timezone(timedelta(hours=5))
    now = datetime(2026, 11, 3, 3, 30, tzinfo=karachi)
    assert faucet_service.claim_day(now) == date(2026, 11, 2)
    assert next_utc_day(now) == datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_a_naive_time_is_read_as_utc():
    now = datetime(2026, 11, 2, 23, 30)
    assert faucet_service.utc_now(now) == datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)
    assert faucet_service.claim_day(now) == date(2026, 11, 2)


# ── Refusals → HTTP ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("reason,code", [
    ("disabled", 404), ("not_active", 403), ("too_young", 429),
    ("already_claimed", 429), ("balance_ceiling", 409), ("dry", 429),
])
def test_each_refusal_has_its_status(reason, code):
    assert FaucetRefused(reason, "x").http_status == code


def test_retry_after_counts_whole_seconds_up_to_the_next_day():
    now = datetime(2026, 11, 2, 23, 59, 30, tzinfo=timezone.utc)
    refused = FaucetRefused("already_claimed", "x", next_claim_at=next_utc_day(now))
    assert refused.headers(now) == {"Retry-After": "31"}
    assert FaucetRefused("balance_ceiling", "x").headers(now) == {}
    assert refused.detail() == {
        "reason": "already_claimed", "message": "x", "next_claim_at": "2026-11-03T00:00:00+00:00",
    }


def test_retry_after_is_never_below_one_second():
    now = datetime(2026, 11, 3, 0, 0, 5, tzinfo=timezone.utc)
    late = FaucetRefused("dry", "x", next_claim_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert late.headers(now) == {"Retry-After": "1"}


# ── The route ─────────────────────────────────────────────────────────────────

async def test_off_means_404_even_when_logged_in(client, authed, faucet_off):
    with patch.object(faucet_service, "claim", new=AsyncMock()) as claim:
        r = await client.post("/wallets/faucet")
    assert r.status_code == 404
    claim.assert_not_called()


async def test_no_login_means_401_before_anything_else(client, faucet_on):
    with patch.object(faucet_service, "claim", new=AsyncMock()) as claim:
        r = await client.post("/wallets/faucet")
        bad = await client.post("/wallets/faucet", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401
    assert bad.status_code == 401
    claim.assert_not_called()


async def test_a_claim_pays_the_caller(client, authed, faucet_on, caller_resolves):
    paid = _response()
    with patch.object(faucet_service, "claim", new=AsyncMock(return_value=paid)) as claim:
        r = await client.post("/wallets/faucet")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == str(CALLER_ID)
    assert body["amount"] == 25 and body["balance"] == 25
    assert body["next_claim_at"].endswith("+00:00") or body["next_claim_at"].endswith("Z")
    claim.assert_awaited_once()
    assert claim.await_args.args == (CALLER_ID,)
    assert claim.await_args.kwargs["settings"] is faucet_on


async def test_nothing_in_the_body_can_choose_who_is_paid(client, authed, faucet_on, caller_resolves):
    with patch.object(faucet_service, "claim", new=AsyncMock(return_value=_response())) as claim:
        r = await client.post(
            "/wallets/faucet",
            json={
                "agent_id": str(VICTIM_ID), "agent_did": "did:agentx:victim-001",
                "to_id": str(VICTIM_ID), "amount": 1_000_000,
            },
        )
    assert r.status_code == 200, r.text
    assert claim.await_args.args == (CALLER_ID,)
    assert r.json()["amount"] == 25


@pytest.mark.parametrize("reason,code,retry", [
    ("already_claimed", 429, True), ("dry", 429, True), ("too_young", 429, True),
    ("balance_ceiling", 409, False), ("not_active", 403, False), ("disabled", 404, False),
])
async def test_a_refusal_is_reported_with_its_reason(client, authed, faucet_on, caller_resolves, reason, code, retry):
    nxt = next_utc_day(datetime.now(timezone.utc)) if retry else None
    with patch.object(
        faucet_service, "claim", new=AsyncMock(side_effect=FaucetRefused(reason, "why", next_claim_at=nxt)),
    ):
        r = await client.post("/wallets/faucet")
    assert r.status_code == code
    detail = r.json()["detail"]
    assert detail["reason"] == reason and detail["message"] == "why"
    if retry:
        assert detail["next_claim_at"] == nxt.isoformat()
        assert int(r.headers["Retry-After"]) >= 1
    else:
        assert detail["next_claim_at"] is None
        assert "Retry-After" not in r.headers


async def test_the_faucet_route_needs_a_login_by_declaration():
    """The write-route guard sees it: the dependency is in the route itself."""
    from fastapi.routing import APIRoute
    from src.auth.middleware import get_current_agent
    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/wallets/faucet")
    assert route.methods == {"POST"}
    assert any(d.call is get_current_agent for d in route.dependant.dependencies)
    assert route.body_field is None   # no request body at all


async def test_service_refuses_while_off_without_touching_the_database(monkeypatch):
    """Belt and braces: a caller that bypasses the router gets the same answer."""
    monkeypatch.setattr(get_settings(), "faucet_enabled", "false")
    with patch.object(faucet_service, "transaction") as txn:
        with pytest.raises(FaucetRefused) as exc:
            await faucet_service.claim(CALLER_ID)
    assert exc.value.reason == "disabled"
    txn.assert_not_called()


# ── FC-5a review: the per-DID rate limit and other ways to pick the payee ────

def _bearer(did: str) -> dict:
    from src.auth.jwt import create_access_token
    return {"Authorization": f"Bearer {create_access_token(agent_did=did, trust_score=0.0)}"}


def test_the_faucet_limits_are_a_few_calls_a_minute():
    """Static strings (no trust scaling): the faucet is for agents with no
    trust yet, and an honest one claims once a day."""
    from src.middleware.rate_limits import LIMIT_FAUCET, LIMIT_FAUCET_HR
    assert LIMIT_FAUCET == "6/minute" and LIMIT_FAUCET_HR == "30/hour"


async def test_the_seventh_call_in_a_minute_never_reaches_the_service(client, authed, faucet_on, caller_resolves):
    """Every claim, paid or refused, takes the faucet's platform-wide lock, so
    the route is capped per DID: the limiter answers the seventh call itself."""
    with patch.object(faucet_service, "claim", new=AsyncMock(return_value=_response())) as claim:
        codes = [
            (await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))).status_code
            for _ in range(6)
        ]
        seventh = await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))
    assert codes == [200] * 6
    assert seventh.status_code == 429, seventh.text
    assert seventh.json()["detail"] == "Rate limit exceeded"
    assert seventh.json()["limit"] == "6 per 1 minute"
    assert int(seventh.headers["Retry-After"]) >= 1
    assert claim.await_count == 6


async def test_refused_claims_count_against_the_same_cap(client, authed, faucet_on, caller_resolves):
    """Looping on a refusal is exactly the case the cap is for."""
    refusal = FaucetRefused(
        "already_claimed", "later", next_claim_at=next_utc_day(datetime.now(timezone.utc)),
    )
    with patch.object(faucet_service, "claim", new=AsyncMock(side_effect=refusal)) as claim:
        for _ in range(6):
            r = await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))
            assert r.status_code == 429 and r.json()["detail"]["reason"] == "already_claimed"
        seventh = await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))
    assert seventh.status_code == 429
    assert seventh.json()["detail"] == "Rate limit exceeded"
    assert claim.await_count == 6


async def test_the_cap_is_per_agent_not_per_address(client, authed, faucet_on, caller_resolves):
    """One agent at its cap does not stop another agent from the same IP."""
    with patch.object(faucet_service, "claim", new=AsyncMock(return_value=_response())) as claim:
        for _ in range(6):
            await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))
        blocked = await client.post("/wallets/faucet", headers=_bearer(CALLER_DID))
        other = await client.post("/wallets/faucet", headers=_bearer("did:agentx:neighbour-002"))
    assert blocked.status_code == 429 and other.status_code == 200
    assert claim.await_count == 7


async def test_the_route_declares_both_faucet_limits():
    """The limits live on the route itself, so a refactor that drops the
    decorators fails here rather than in production."""
    from src.middleware.rate_limits import limiter_did
    key = next(k for k in limiter_did._route_limits if k.endswith("claim_faucet"))
    assert sorted(str(limit.limit) for limit in limiter_did._route_limits[key]) == [
        "30 per 1 hour", "6 per 1 minute",
    ]


async def test_nothing_in_the_headers_or_query_can_choose_who_is_paid(client, authed, faucet_on, caller_resolves):
    """The route reads no agent identity from anywhere but the bearer token."""
    with patch.object(faucet_service, "claim", new=AsyncMock(return_value=_response())) as claim:
        r = await client.post(
            "/wallets/faucet",
            params={"agent_id": str(VICTIM_ID), "agent_did": "did:agentx:victim-001", "amount": 10_000},
            headers={
                "X-Agent-DID": "did:agentx:victim-001", "X-Agent-Id": str(VICTIM_ID),
                "X-On-Behalf-Of": "did:agentx:victim-001", "X-Forwarded-User": "did:agentx:victim-001",
            },
        )
    assert r.status_code == 200, r.text
    assert claim.await_args.args == (CALLER_ID,)
    assert claim.await_args.kwargs.get("now") is None      # the clock is the server's
    assert r.json()["amount"] == 25
