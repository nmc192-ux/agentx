"""
Tests: src/routers/tokens.py
Phase 8 — Agent Token Economy

Covers:
  POST   /wallets                         — create/fund wallet
  POST   /wallets/transfer                — transfer tokens (requires auth)
  GET    /wallets/{agent_id}/transactions — list transaction history
  GET    /wallets/{agent_id}              — get wallet / balance
  POST   /stakes                          — stake tokens (requires auth)
  GET    /stakes/{agent_id}              — list active stakes
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
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

def _wallet(agent_id=None, balance=1000):
    from src.models.token import WalletResponse
    return WalletResponse(
        wallet_id=uuid4(),
        agent_id=agent_id or uuid4(),
        balance=balance,
        updated_at=_now(),
    )


def _transaction(from_w=None, to_w=None, amount=100, tx_type="transfer"):
    from src.models.token import TransactionResponse
    return TransactionResponse(
        transaction_id=uuid4(),
        from_wallet=from_w or uuid4(),
        to_wallet=to_w or uuid4(),
        amount=amount,
        type=tx_type,
        related_id=None,
        timestamp=_now(),
    )


def _stake(agent_id=None, amount=200):
    from src.models.token import StakeResponse
    return StakeResponse(
        stake_id=uuid4(),
        agent_id=agent_id or uuid4(),
        amount=amount,
        locked_until=None,
        released_at=None,
        created_at=_now(),
    )


# ── Mock auth ─────────────────────────────────────────────────────────────────

def _make_agent(did="did:agentx:atlas-001"):
    """Build an AgentRecord matching the pattern used by collectives tests."""
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did":       did,
        "display_name":    "Atlas",
        "governance_role": "AGENT",
        "tier":            "STANDARD",
        "status":          "ACTIVE",
        "trust_score":     0.9,
    }
    return AgentRecord(row=row, claims=mock_claims)


# ── POST /wallets ─────────────────────────────────────────────────────────────

class TestCreateWallet:

    @pytest.mark.asyncio
    async def test_create_wallet_returns_200(self, client):
        agent_id = uuid4()
        wallet   = _wallet(agent_id=agent_id, balance=500)

        with patch(
            "src.routers.tokens.token_service.create_wallet",
            new=AsyncMock(return_value=wallet),
        ):
            resp = await client.post(
                "/wallets",
                json={"agent_id": str(agent_id), "initial_balance": 500},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == 500
        assert data["agent_id"] == str(agent_id)

    @pytest.mark.asyncio
    async def test_create_wallet_returns_400_on_error(self, client):
        with patch(
            "src.routers.tokens.token_service.create_wallet",
            new=AsyncMock(side_effect=Exception("DB error")),
        ):
            resp = await client.post(
                "/wallets",
                json={"agent_id": str(uuid4()), "initial_balance": 0},
            )

        assert resp.status_code == 400


# ── POST /wallets/transfer ─────────────────────────────────────────────────────

class TestTransferTokens:

    @pytest.mark.asyncio
    async def test_transfer_returns_transaction(self, client):
        from src.auth.middleware import get_current_agent
        tx     = _transaction(amount=100)
        caller = _make_agent()

        with patch(
            "src.routers.tokens.token_service.transfer_tokens",
            new=AsyncMock(return_value=tx),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            try:
                resp = await client.post(
                    "/wallets/transfer",
                    json={
                        "from_id": str(uuid4()),
                        "to_id":   str(uuid4()),
                        "amount":  100,
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200
        assert resp.json()["amount"] == 100

    @pytest.mark.asyncio
    async def test_transfer_returns_400_on_insufficient_funds(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_agent()

        with patch(
            "src.routers.tokens.token_service.transfer_tokens",
            new=AsyncMock(side_effect=ValueError("Insufficient funds")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            try:
                resp = await client.post(
                    "/wallets/transfer",
                    json={
                        "from_id": str(uuid4()),
                        "to_id":   str(uuid4()),
                        "amount":  999999,
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400
        assert "Insufficient" in resp.json()["detail"]


# ── GET /wallets/{agent_id}/transactions ──────────────────────────────────────

class TestListTransactions:

    @pytest.mark.asyncio
    async def test_list_transactions_returns_list(self, client):
        agent_id = uuid4()
        txs = [_transaction(), _transaction()]

        with patch(
            "src.routers.tokens.token_service.get_transactions",
            new=AsyncMock(return_value=txs),
        ):
            resp = await client.get(f"/wallets/{agent_id}/transactions")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_list_transactions_returns_empty_list(self, client):
        with patch(
            "src.routers.tokens.token_service.get_transactions",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/wallets/{uuid4()}/transactions")

        assert resp.status_code == 200
        assert resp.json() == []


# ── GET /wallets/{agent_id} ───────────────────────────────────────────────────

class TestGetWallet:

    @pytest.mark.asyncio
    async def test_get_wallet_returns_200(self, client):
        agent_id = uuid4()
        wallet   = _wallet(agent_id=agent_id, balance=750)

        with patch(
            "src.routers.tokens.token_service.get_wallet",
            new=AsyncMock(return_value=wallet),
        ):
            resp = await client.get(f"/wallets/{agent_id}")

        assert resp.status_code == 200
        assert resp.json()["balance"] == 750

    @pytest.mark.asyncio
    async def test_get_wallet_returns_404_if_not_found(self, client):
        with patch(
            "src.routers.tokens.token_service.get_wallet",
            new=AsyncMock(side_effect=ValueError("Wallet not found")),
        ):
            resp = await client.get(f"/wallets/{uuid4()}")

        assert resp.status_code == 404


# ── POST /stakes ───────────────────────────────────────────────────────────────

class TestStakeTokens:

    @pytest.mark.asyncio
    async def test_stake_tokens_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        agent_id = uuid4()
        stake    = _stake(agent_id=agent_id, amount=300)
        caller   = _make_agent()

        with patch(
            "src.routers.tokens.token_service.stake_tokens",
            new=AsyncMock(return_value=stake),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            try:
                resp = await client.post(
                    "/stakes",
                    json={"agent_id": str(agent_id), "amount": 300},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["amount"] == 300

    @pytest.mark.asyncio
    async def test_stake_tokens_returns_400_on_insufficient_funds(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_agent()

        with patch(
            "src.routers.tokens.token_service.stake_tokens",
            new=AsyncMock(side_effect=ValueError("Insufficient funds")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            try:
                resp = await client.post(
                    "/stakes",
                    json={"agent_id": str(uuid4()), "amount": 999999},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# ── GET /stakes/{agent_id} ────────────────────────────────────────────────────

class TestListStakes:

    @pytest.mark.asyncio
    async def test_list_stakes_returns_list(self, client):
        agent_id = uuid4()
        stakes   = [_stake(agent_id=agent_id), _stake(agent_id=agent_id)]

        with patch(
            "src.routers.tokens.token_service.get_stakes",
            new=AsyncMock(return_value=stakes),
        ):
            resp = await client.get(f"/stakes/{agent_id}")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_list_stakes_returns_empty_list(self, client):
        with patch(
            "src.routers.tokens.token_service.get_stakes",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/stakes/{uuid4()}")

        assert resp.status_code == 200
        assert resp.json() == []
