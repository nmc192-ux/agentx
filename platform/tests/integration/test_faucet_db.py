"""
Integration tests: the token faucet against REAL local Postgres
Phase C, Sprint 20, FC-1 — the proof behind `POST /wallets/faucet`.

Every request goes HTTP → router → service → Postgres. Only the JWT check is
replaced (the caller is set per request); no money path is mocked. The
fixtures are in conftest.py.

What is proven:
  • a claim credits exactly FAUCET_AMOUNT once, opening the wallet at 0 if
    the agent has none; the ledger has one 'faucet' row pointing at the
    claim, and token_supply.total_minted rises by exactly that amount
  • a second claim the same UTC day is refused with no new ledger row and
    no change to balance or supply; the next UTC day it is paid again
  • ten claims at once by one agent credit once; claims at once by a hundred
    agents never pass the daily budget, and total_minted matches what was paid
  • a wallet at or above the ceiling, an agent younger than the minimum age,
    a suspended agent, the faucet switched off, and no login each change
    nothing
  • whatever the body says, only the caller is paid
  • without a token_supply row no token is created (the claim rolls back)
  • tokens are conserved: wallets + escrow + stakes rise by exactly what the
    faucet paid, and by nothing else

Run (needs local Postgres with trust auth for the current OS user):
    cd platform && .venv/bin/python -m pytest tests/integration/test_faucet_db.py -v --db
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.config import get_settings
from src.services import faucet_service
from src.services.faucet_service import FaucetRefused

from .support import Agent, balance, total_tokens

pytestmark = pytest.mark.integration   # skipped unless --db is given

AMOUNT = 25
CEILING = 100
BUDGET = 2000


@pytest_asyncio.fixture(autouse=True)
async def treasury(pool):
    from src.services import economy_service
    await economy_service.initialize_treasury()


@pytest.fixture
def faucet(monkeypatch):
    """The faucet ON with the sprint's defaults (restored after each test)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "faucet_enabled", "true")
    monkeypatch.setattr(settings, "faucet_amount", AMOUNT)
    monkeypatch.setattr(settings, "faucet_balance_ceiling", CEILING)
    monkeypatch.setattr(settings, "faucet_min_age_minutes", 60)
    monkeypatch.setattr(settings, "faucet_daily_budget", BUDGET)
    return settings


@pytest_asyncio.fixture(autouse=True)
async def clean_claims(pool):
    """Each test starts with an empty claim history (the budget is per day)."""
    await pool.execute("DELETE FROM faucet_claims")
    yield
    await pool.execute("DELETE FROM faucet_claims")


# ── DB probes ─────────────────────────────────────────────────────────────────

async def total_minted(pool) -> int:
    return await pool.fetchval("SELECT total_minted FROM token_supply")


async def faucet_ledger(pool, agent: Agent) -> list:
    return await pool.fetch(
        """
        SELECT t.amount, t.from_wallet, t.related_id
        FROM transactions t JOIN wallets w ON w.wallet_id = t.to_wallet
        WHERE w.agent_id = $1 AND t.type = 'faucet'
        """,
        agent.agent_id,
    )


async def claims(pool, agent: Agent | None = None) -> list:
    if agent is None:
        return await pool.fetch("SELECT * FROM faucet_claims")
    return await pool.fetch("SELECT * FROM faucet_claims WHERE agent_id = $1", agent.agent_id)


async def claim(client, agent: Agent, **kw):
    return await client.post("/wallets/faucet", headers=agent.headers, **kw)


# ── One claim ─────────────────────────────────────────────────────────────────

async def test_a_claim_credits_the_amount_once_and_records_it_everywhere(client, agents, pool, faucet):
    a = await agents("fresh", age_days=1)            # no wallet yet
    assert await balance(pool, a) is None
    minted0, tokens0 = await total_minted(pool), await total_tokens(pool)

    r = await claim(client, a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == str(a.agent_id)
    assert body["amount"] == AMOUNT and body["balance"] == AMOUNT
    assert body["claim_day"] == datetime.now(timezone.utc).date().isoformat()

    assert await balance(pool, a) == AMOUNT
    assert await total_minted(pool) == minted0 + AMOUNT
    assert await total_tokens(pool) == tokens0 + AMOUNT
    rows = await faucet_ledger(pool, a)
    assert len(rows) == 1
    assert rows[0]["amount"] == AMOUNT and rows[0]["from_wallet"] is None
    assert str(rows[0]["related_id"]) == body["claim_id"]
    (c,) = await claims(pool, a)
    assert c["amount"] == AMOUNT and str(c["claim_id"]) == body["claim_id"]
    assert str(c["claim_id"]) == body["claim_id"]
    # The ledger row is the one the response names.
    tx = await pool.fetchrow("SELECT type FROM transactions WHERE transaction_id = $1", body["transaction_id"])
    assert tx["type"] == "faucet"


async def test_an_existing_wallet_is_topped_up_not_replaced(client, agents, pool, faucet):
    a = await agents("holder", balance=40, age_days=1)
    r = await claim(client, a)
    assert r.status_code == 200, r.text
    assert r.json()["balance"] == 65
    assert await balance(pool, a) == 65


async def test_a_second_claim_the_same_day_changes_nothing(client, agents, pool, faucet):
    a = await agents("twice", age_days=1)
    assert (await claim(client, a)).status_code == 200
    minted1, tokens1 = await total_minted(pool), await total_tokens(pool)

    r = await claim(client, a)
    assert r.status_code == 429, r.text
    d = r.json()["detail"]
    assert d["reason"] == "already_claimed"
    assert datetime.fromisoformat(d["next_claim_at"]) == faucet_service.next_utc_day(datetime.now(timezone.utc))
    assert int(r.headers["Retry-After"]) >= 1

    assert await balance(pool, a) == AMOUNT
    assert len(await faucet_ledger(pool, a)) == 1
    assert len(await claims(pool, a)) == 1
    assert (await total_minted(pool), await total_tokens(pool)) == (minted1, tokens1)


async def test_the_next_utc_day_pays_again(agents, pool, faucet):
    a = await agents("daily", age_days=1)
    today = datetime(2026, 11, 2, 23, 59, 59, tzinfo=timezone.utc)
    await faucet_service.claim(a.agent_id, now=today)
    with pytest.raises(FaucetRefused) as exc:
        await faucet_service.claim(a.agent_id, now=today)
    assert exc.value.reason == "already_claimed"
    paid = await faucet_service.claim(a.agent_id, now=today + timedelta(seconds=1))
    assert paid.claim_day.isoformat() == "2026-11-03"
    assert await balance(pool, a) == 2 * AMOUNT
    assert len(await claims(pool, a)) == 2


# ── Concurrency ───────────────────────────────────────────────────────────────

async def test_ten_claims_at_once_by_one_agent_credit_once(client, agents, pool, faucet):
    a = await agents("racer", age_days=1)
    minted0 = await total_minted(pool)
    responses = await asyncio.gather(*[claim(client, a) for _ in range(10)])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [429] * 9, codes
    assert await balance(pool, a) == AMOUNT
    assert len(await faucet_ledger(pool, a)) == 1
    assert len(await claims(pool, a)) == 1
    assert await total_minted(pool) == minted0 + AMOUNT


async def test_a_hundred_agents_at_once_never_pass_the_budget(client, agents, pool, faucet, monkeypatch):
    allowed = 30
    monkeypatch.setattr(faucet, "faucet_daily_budget", allowed * AMOUNT)
    crowd = [await agents(f"crowd{i}", age_days=1) for i in range(100)]
    minted0, tokens0 = await total_minted(pool), await total_tokens(pool)

    responses = await asyncio.gather(*[claim(client, a) for a in crowd])
    paid = [r for r in responses if r.status_code == 200]
    dry = [r for r in responses if r.status_code == 429]
    assert len(paid) == allowed and len(dry) == 100 - allowed, [r.status_code for r in responses]
    assert {r.json()["detail"]["reason"] for r in dry} == {"dry"}

    spent = await pool.fetchval("SELECT COALESCE(SUM(amount), 0) FROM faucet_claims")
    assert spent == allowed * AMOUNT
    assert await total_minted(pool) == minted0 + allowed * AMOUNT
    assert await total_tokens(pool) == tokens0 + allowed * AMOUNT
    assert sum([await balance(pool, a) or 0 for a in crowd]) == allowed * AMOUNT
    # Exactly the paid agents hold tokens, one claim row each.
    paid_ids = {r.json()["agent_id"] for r in paid}
    assert {str(c["agent_id"]) for c in await claims(pool)} == paid_ids


async def test_the_budget_counts_the_whole_day_not_the_request(client, agents, pool, faucet, monkeypatch):
    monkeypatch.setattr(faucet, "faucet_daily_budget", 2 * AMOUNT)
    a, b, c = [await agents(n, age_days=1) for n in ("one", "two", "three")]
    assert (await claim(client, a)).status_code == 200
    assert (await claim(client, b)).status_code == 200
    r = await claim(client, c)
    assert r.status_code == 429 and r.json()["detail"]["reason"] == "dry"
    assert await balance(pool, c) is None
    assert len(await claims(pool, c)) == 0


# ── Eligibility refusals change nothing ───────────────────────────────────────

async def _unchanged(pool, agent: Agent, before: tuple) -> None:
    assert await balance(pool, agent) == before[0]
    assert len(await claims(pool, agent)) == 0
    assert len(await faucet_ledger(pool, agent)) == 0
    assert (await total_minted(pool), await total_tokens(pool)) == before[1:]


async def _snapshot(pool, agent: Agent) -> tuple:
    return (await balance(pool, agent), await total_minted(pool), await total_tokens(pool))


async def test_a_full_wallet_is_refused(client, agents, pool, faucet):
    rich = await agents("rich", balance=CEILING, age_days=1)
    before = await _snapshot(pool, rich)
    r = await claim(client, rich)
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "balance_ceiling"
    assert "Retry-After" not in r.headers
    await _unchanged(pool, rich, before)
    # Just under the ceiling is fine.
    nearly = await agents("nearly", balance=CEILING - 1, age_days=1)
    assert (await claim(client, nearly)).status_code == 200
    assert await balance(pool, nearly) == CEILING - 1 + AMOUNT


async def test_a_brand_new_agent_must_wait(client, agents, pool, faucet):
    baby = await agents("baby")                        # created just now
    before = await _snapshot(pool, baby)
    r = await claim(client, baby)
    assert r.status_code == 429, r.text
    d = r.json()["detail"]
    assert d["reason"] == "too_young"
    created = await pool.fetchval("SELECT created_at FROM agents WHERE agent_id = $1", baby.agent_id)
    assert datetime.fromisoformat(d["next_claim_at"]) == created + timedelta(minutes=60)
    await _unchanged(pool, baby, before)
    # With no minimum age it is paid at once.
    faucet.faucet_min_age_minutes = 0
    assert (await claim(client, baby)).status_code == 200


async def test_a_suspended_agent_is_refused_even_with_a_valid_login(client, agents, pool, faucet):
    s = await agents("suspended", age_days=1)
    await pool.execute("UPDATE agents SET status = 'SUSPENDED' WHERE agent_id = $1", s.agent_id)
    before = await _snapshot(pool, s)
    r = await claim(client, s)
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "not_active"
    await _unchanged(pool, s, before)


async def test_switched_off_is_404_and_writes_nothing(client, agents, pool, faucet):
    a = await agents("locked-out", age_days=1)
    before = await _snapshot(pool, a)
    faucet.faucet_enabled = "false"
    r = await claim(client, a)
    assert r.status_code == 404
    await _unchanged(pool, a, before)
    # The service alone refuses too (nothing else can mint while it is off).
    with pytest.raises(FaucetRefused) as exc:
        await faucet_service.claim(a.agent_id)
    assert exc.value.reason == "disabled"
    await _unchanged(pool, a, before)


async def test_no_login_means_401_and_nothing_written(client, agents, pool, faucet):
    a = await agents("anon", age_days=1)
    before = await _snapshot(pool, a)
    r = await client.post("/wallets/faucet")
    assert r.status_code == 401
    assert await claims(pool) == []
    await _unchanged(pool, a, before)


async def test_whatever_the_body_says_only_the_caller_is_paid(client, agents, pool, faucet):
    caller = await agents("caller", age_days=1)
    victim = await agents("victim", age_days=1)
    r = await claim(
        client, caller,
        json={
            "agent_id": str(victim.agent_id), "agent_did": victim.did,
            "to_id": str(victim.agent_id), "amount": 1_000_000, "initial_balance": 1_000_000,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["agent_id"] == str(caller.agent_id) and r.json()["amount"] == AMOUNT
    assert await balance(pool, caller) == AMOUNT
    assert await balance(pool, victim) is None
    assert len(await claims(pool, victim)) == 0


async def test_no_supply_record_means_no_token(client, agents, pool, faucet):
    """Fail closed: the claim rolls back as a whole (no wallet credit, no claim
    row, no ledger row) when total_minted cannot be recorded."""
    from httpx import ASGITransport, AsyncClient
    from src.main import app
    a = await agents("unrecorded", age_days=1)
    before = await _snapshot(pool, a)
    await pool.execute("DELETE FROM token_supply")
    try:
        # The default test transport re-raises app errors; a real caller
        # sees the generic handler's 500, so ask for the response instead.
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as quiet:
            r = await quiet.post("/wallets/faucet", headers=a.headers)
        assert r.status_code == 500
        assert r.json()["detail"] == "Internal server error"
        assert await balance(pool, a) is None
        assert len(await claims(pool, a)) == 0
        assert len(await faucet_ledger(pool, a)) == 0
    finally:
        await pool.execute(
            "INSERT INTO token_supply (total_minted, total_burned) VALUES ($1, 0)", before[1],
        )
    assert await total_tokens(pool) == before[2]


async def test_the_claim_history_is_one_row_per_agent_per_day_in_the_database(agents, pool, faucet):
    """The constraint behind the service: even a direct insert cannot double up."""
    import asyncpg
    a = await agents("constrained", age_days=1)
    day = datetime.now(timezone.utc).date()
    await pool.execute(
        "INSERT INTO faucet_claims (agent_id, claim_day, amount) VALUES ($1, $2, $3)", a.agent_id, day, AMOUNT,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(
            "INSERT INTO faucet_claims (agent_id, claim_day, amount) VALUES ($1, $2, $3)", a.agent_id, day, AMOUNT,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            "INSERT INTO faucet_claims (agent_id, claim_day, amount) VALUES ($1, $2, 0)",
            a.agent_id, day + timedelta(days=1),
        )


# ── FC-2: the heartbeat's faucet_hint, against the real tables ────────────────

async def heartbeat_hint(client, agent: Agent):
    r = await client.post(
        "/heartbeat", headers=agent.headers,
        json={"agent_did": agent.did, "status": "active", "capabilities": []},
    )
    assert r.status_code == 200, r.text
    return r.json()["faucet_hint"]


async def test_heartbeat_hint_until_claimed_then_gone(client, agents, pool, faucet):
    a = await agents("hinted", age_days=1)            # no wallet yet
    before = await _snapshot(pool, a)
    hint = await heartbeat_hint(client, a)
    assert hint and "POST /wallets/faucet" in hint
    await _unchanged(pool, a, before)                  # the hint wrote nothing
    assert await claims(pool, a) == []

    assert (await claim(client, a)).status_code == 200
    assert await heartbeat_hint(client, a) is None     # claimed today


async def test_heartbeat_no_hint_for_a_full_wallet_or_while_off(client, agents, pool, faucet, monkeypatch):
    rich = await agents("rich", balance=CEILING, age_days=1)
    assert await heartbeat_hint(client, rich) is None
    poor = await agents("poor", balance=0, age_days=1)
    assert await heartbeat_hint(client, poor)
    monkeypatch.setattr(faucet, "faucet_enabled", "false")
    assert await heartbeat_hint(client, poor) is None
