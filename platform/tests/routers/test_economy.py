"""
Tests: src/routers/economy.py
Phase 8.5 — Economic Engine

Covers:
  GET  /economy/metrics  — latest economic snapshot
  GET  /economy/treasury — treasury wallet balance
  POST /economy/mint     — mint tokens (requires auth)
  POST /economy/slash    — slash a stake (requires auth)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


def _now():
    return datetime.now(timezone.utc)


# ── Model builders ─────────────────────────────────────────────────────────────

def _metrics():
    from src.models.economy import EconomicMetricsResponse
    return EconomicMetricsResponse(
        metric_id=uuid4(),
        total_supply=10000,
        treasury_balance=2500,
        total_staked=1000,
        active_tasks=5,
        fees_collected=200,
        recorded_at=_now(),
    )


def _supply():
    from src.models.economy import TokenSupplyResponse
    return TokenSupplyResponse(
        supply_id=uuid4(),
        total_minted=10000,
        total_burned=0,
        circulating=10000,
        updated_at=_now(),
    )


def _treasury():
    from src.models.token import WalletResponse
    return WalletResponse(
        wallet_id=uuid4(),
        agent_id=None,
        balance=2500,
        updated_at=_now(),
        wallet_type="treasury",
    )


def _slash(stake_id=None):
    from src.models.economy import StakeSlashResponse
    return StakeSlashResponse(
        slash_id=uuid4(),
        stake_id=stake_id or uuid4(),
        agent_id=uuid4(),
        amount=500,
        reason="bad actor",
        created_at=_now(),
    )


# ── Mock auth ─────────────────────────────────────────────────────────────────

def _make_agent():
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = "did:agentx:admin-001"
    row = {
        "agent_did":       "did:agentx:admin-001",
        "display_name":    "Admin",
        "governance_role": "ADMIN",
        "tier":            "ELITE",
        "status":          "ACTIVE",
        "trust_score":     1.0,
    }
    return AgentRecord(row=row, claims=mock_claims)


# ── GET /economy/metrics ──────────────────────────────────────────────────────

class TestGetMetrics:

    @pytest.mark.asyncio
    async def test_returns_latest_metrics(self, client):
        m = _metrics()
        from unittest.mock import patch
        with patch(
            "src.routers.economy.economy_service.get_latest_metrics",
            new=AsyncMock(return_value=m),
        ):
            resp = await client.get("/economy/metrics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_supply"] == 10000
        assert data["treasury_balance"] == 2500

    @pytest.mark.asyncio
    async def test_returns_null_when_no_snapshots(self, client):
        from unittest.mock import patch
        with patch(
            "src.routers.economy.economy_service.get_latest_metrics",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get("/economy/metrics")

        assert resp.status_code == 200
        assert resp.json() is None


# ── GET /economy/treasury ─────────────────────────────────────────────────────

class TestGetTreasury:

    @pytest.mark.asyncio
    async def test_returns_treasury_wallet(self, client):
        t = _treasury()
        from unittest.mock import patch
        with patch(
            "src.routers.economy.economy_service.get_treasury_balance",
            new=AsyncMock(return_value=t),
        ):
            resp = await client.get("/economy/treasury")

        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == 2500
        assert data["wallet_type"] == "treasury"
        assert data["agent_id"] is None

    @pytest.mark.asyncio
    async def test_returns_404_if_not_initialised(self, client):
        from unittest.mock import patch
        with patch(
            "src.routers.economy.economy_service.get_treasury_balance",
            new=AsyncMock(side_effect=ValueError("Treasury not initialised")),
        ):
            resp = await client.get("/economy/treasury")

        assert resp.status_code == 404


# ── POST /economy/mint ────────────────────────────────────────────────────────

class TestMintTokens:

    @pytest.mark.asyncio
    async def test_mint_returns_200(self, client):
        from unittest.mock import patch
        from src.auth.middleware import get_current_agent
        s = _supply()

        with patch(
            "src.routers.economy.economy_service.mint_tokens",
            new=AsyncMock(return_value=s),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/economy/mint",
                    json={"amount": 1000, "reason": "genesis"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json()["total_minted"] == 10000

    @pytest.mark.asyncio
    async def test_mint_returns_400_if_treasury_not_initialised(self, client):
        from unittest.mock import patch
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.economy.economy_service.mint_tokens",
            new=AsyncMock(side_effect=ValueError("Treasury not initialised")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/economy/mint",
                    json={"amount": 100},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_mint_requires_auth(self, client):
        """Without auth override, endpoint returns 401/403 from real auth."""
        resp = await client.post(
            "/economy/mint",
            json={"amount": 100},
        )
        # No auth token → 401 or 403
        assert resp.status_code in (401, 403)


# ── POST /economy/slash ───────────────────────────────────────────────────────

class TestSlashStake:

    @pytest.mark.asyncio
    async def test_slash_returns_200(self, client):
        from unittest.mock import patch
        from src.auth.middleware import get_current_agent
        stake_id = uuid4()
        sl = _slash(stake_id=stake_id)

        with patch(
            "src.routers.economy.economy_service.slash_stake",
            new=AsyncMock(return_value=sl),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/economy/slash",
                    json={"stake_id": str(stake_id), "reason": "bad actor"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json()["amount"] == 500

    @pytest.mark.asyncio
    async def test_slash_returns_404_for_unknown_stake(self, client):
        from unittest.mock import patch
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.economy.economy_service.slash_stake",
            new=AsyncMock(side_effect=ValueError("Stake not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/economy/slash",
                    json={"stake_id": str(uuid4()), "reason": ""},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_slash_returns_400_for_already_released(self, client):
        from unittest.mock import patch
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.economy.economy_service.slash_stake",
            new=AsyncMock(side_effect=ValueError("Stake already released or slashed")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_agent()
            try:
                resp = await client.post(
                    "/economy/slash",
                    json={"stake_id": str(uuid4()), "reason": "double slash"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_slash_requires_auth(self, client):
        resp = await client.post(
            "/economy/slash",
            json={"stake_id": str(uuid4()), "reason": ""},
        )
        assert resp.status_code in (401, 403)
