"""
Tests: src/routers/tokens.py
Phase 8 — Agent Token Economy

Covers:
  POST   /wallets                         — create/fund wallet (auth; minting FOUNDER-only)
  POST   /wallets/by-did                  — same, by DID
  POST   /wallets/transfer                — transfer tokens (auth; caller's wallet only)
  GET    /wallets/{agent_id}/transactions — list transaction history
  GET    /wallets/{agent_id}              — get wallet / balance
  POST   /stakes                          — stake tokens (requires auth)
  GET    /stakes/{agent_id}              — list active stakes
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
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

def _make_agent(did="did:agentx:atlas-001", role="MEMBER"):
    """Build an AgentRecord matching the pattern used by collectives tests."""
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did":       did,
        "display_name":    "Atlas",
        "governance_role": role,
        "tier":            "STANDARD",
        "status":          "ACTIVE",
        "trust_score":     0.9,
    }
    return AgentRecord(row=row, claims=mock_claims)


# ── POST /wallets ─────────────────────────────────────────────────────────────

@contextmanager
def _as(caller, caller_id):
    """Authenticate as *caller*, whose agents.agent_id resolves to *caller_id*."""
    from src.auth.middleware import get_current_agent
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        with patch(
            "src.routers.tokens._caller_agent_id",
            new=AsyncMock(return_value=caller_id),
        ):
            yield
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


def _db_returning(value):
    """Patch target for get_db(): an async context manager whose conn.fetchval → value."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=value)

    @asynccontextmanager
    async def _get_db():
        yield conn
    return _get_db


class TestCreateWallet:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_and_never_mints(self, client):
        create = AsyncMock(return_value=_wallet())
        with patch("src.routers.tokens.token_service.create_wallet", new=create):
            resp = await client.post(
                "/wallets",
                json={"agent_id": str(uuid4()), "initial_balance": 1_000_000},
            )
        assert resp.status_code == 401
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_service_wallet_at_zero_succeeds(self, client):
        caller_id = uuid4()
        create    = AsyncMock(return_value=_wallet(agent_id=caller_id, balance=0))
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post("/wallets", json={})
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == str(caller_id)
        create.assert_awaited_once_with(caller_id, 0)

    @pytest.mark.asyncio
    async def test_self_service_wallet_cannot_mint(self, client):
        caller_id = uuid4()
        create    = AsyncMock(return_value=_wallet())
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post(
                "/wallets",
                json={"agent_id": str(caller_id), "initial_balance": 500},
            )
        assert resp.status_code == 403
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cannot_create_wallet_for_another_agent(self, client):
        create = AsyncMock(return_value=_wallet())
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post("/wallets", json={"agent_id": str(uuid4())})
        assert resp.status_code == 403
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_founder_may_fund_another_agent(self, client):
        target = uuid4()
        create = AsyncMock(return_value=_wallet(agent_id=target, balance=500))
        with _as(_make_agent(role="FOUNDER"), uuid4()), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post(
                "/wallets",
                json={"agent_id": str(target), "initial_balance": 500},
            )
        assert resp.status_code == 200
        assert resp.json()["balance"] == 500
        create.assert_awaited_once_with(target, 500)

    @pytest.mark.asyncio
    async def test_create_wallet_returns_400_on_error(self, client):
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.create_wallet",
            new=AsyncMock(side_effect=Exception("DB error")),
        ):
            resp = await client.post("/wallets", json={})
        assert resp.status_code == 400


# ── POST /wallets/by-did ──────────────────────────────────────────────────────

class TestCreateWalletByDID:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_and_never_mints(self, client):
        create = AsyncMock(return_value=_wallet())
        with patch("src.routers.tokens.token_service.create_wallet", new=create):
            resp = await client.post(
                "/wallets/by-did",
                json={"agent_did": "did:agentx:victim", "initial_balance": 1_000_000},
            )
        assert resp.status_code == 401
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_service_cannot_mint(self, client):
        caller = _make_agent()
        create = AsyncMock(return_value=_wallet())
        with _as(caller, uuid4()), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post(
                "/wallets/by-did",
                json={"agent_did": caller.did, "initial_balance": 500},
            )
        assert resp.status_code == 403
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cannot_create_for_another_did(self, client):
        create = AsyncMock(return_value=_wallet())
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.create_wallet", new=create,
        ):
            resp = await client.post(
                "/wallets/by-did", json={"agent_did": "did:agentx:someone-else"},
            )
        assert resp.status_code == 403
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_service_at_zero_succeeds(self, client):
        caller, agent_id = _make_agent(), uuid4()
        create = AsyncMock(return_value=_wallet(agent_id=agent_id, balance=0))
        with _as(caller, agent_id), patch(
            "src.routers.tokens.get_db", new=_db_returning(agent_id),
        ), patch("src.routers.tokens.token_service.create_wallet", new=create):
            resp = await client.post("/wallets/by-did", json={"agent_did": caller.did})
        assert resp.status_code == 200
        create.assert_awaited_once_with(agent_id, 0)


# ── POST /wallets/transfer ─────────────────────────────────────────────────────

class TestTransferTokens:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        transfer = AsyncMock(return_value=_transaction())
        with patch("src.routers.tokens.token_service.transfer_tokens", new=transfer):
            resp = await client.post(
                "/wallets/transfer",
                json={"from_id": str(uuid4()), "to_id": str(uuid4()), "amount": 100},
            )
        assert resp.status_code == 401
        transfer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cannot_transfer_from_another_agents_wallet(self, client):
        """Regression guard: body.from_id naming a victim must not move their tokens."""
        victim   = uuid4()
        transfer = AsyncMock(return_value=_transaction())
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.transfer_tokens", new=transfer,
        ):
            resp = await client.post(
                "/wallets/transfer",
                json={"from_id": str(victim), "to_id": str(uuid4()), "amount": 100},
            )
        assert resp.status_code == 403
        transfer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owner_transfer_uses_caller_identity(self, client):
        caller_id, to_id = uuid4(), uuid4()
        transfer = AsyncMock(return_value=_transaction(amount=100))
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.transfer_tokens", new=transfer,
        ):
            resp = await client.post(
                "/wallets/transfer", json={"to_id": str(to_id), "amount": 100},
            )
        assert resp.status_code == 200
        assert resp.json()["amount"] == 100
        transfer.assert_awaited_once_with(
            from_agent_id=caller_id, to_agent_id=to_id, amount=100, tx_type="transfer",
        )

    @pytest.mark.asyncio
    async def test_matching_from_id_is_accepted(self, client):
        caller_id = uuid4()
        transfer  = AsyncMock(return_value=_transaction(amount=5))
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.transfer_tokens", new=transfer,
        ):
            resp = await client.post(
                "/wallets/transfer",
                json={"from_id": str(caller_id), "to_id": str(uuid4()),
                      "amount": 5, "type": "PAYMENT"},
            )
        assert resp.status_code == 200
        assert transfer.await_args.kwargs["tx_type"] == "payment"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("label", ["escrow_release", "reward", "fee", "stake", "mint"])
    async def test_system_transaction_labels_rejected(self, client, label):
        transfer = AsyncMock(return_value=_transaction())
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.transfer_tokens", new=transfer,
        ):
            resp = await client.post(
                "/wallets/transfer",
                json={"to_id": str(uuid4()), "amount": 1, "type": label},
            )
        assert resp.status_code == 422
        transfer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transfer_returns_400_on_insufficient_funds(self, client):
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.transfer_tokens",
            new=AsyncMock(side_effect=ValueError("Insufficient funds")),
        ):
            resp = await client.post(
                "/wallets/transfer", json={"to_id": str(uuid4()), "amount": 999999},
            )
        assert resp.status_code == 400
        assert "Insufficient" in resp.json()["detail"]


# ── _caller_agent_id ──────────────────────────────────────────────────────────

class TestCallerAgentId:

    @pytest.mark.asyncio
    async def test_resolves_caller_did(self):
        from src.routers.tokens import _caller_agent_id
        agent_id = uuid4()
        with patch("src.routers.tokens.get_db", new=_db_returning(agent_id)):
            assert await _caller_agent_id(_make_agent()) == agent_id

    @pytest.mark.asyncio
    async def test_missing_agent_record_fails_closed(self):
        from fastapi import HTTPException
        from src.routers.tokens import _caller_agent_id
        with patch("src.routers.tokens.get_db", new=_db_returning(None)):
            with pytest.raises(HTTPException) as exc:
                await _caller_agent_id(_make_agent())
        assert exc.value.status_code == 403


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


# ── GET /wallets/by-did ────────────────────────────────────────────────────────

class TestGetWalletByDID:
    """S9-7c: the read route /onboard and skill.md point new agents at."""

    @pytest.mark.asyncio
    async def test_returns_the_wallet_without_a_login(self, client):
        agent_id = uuid4()
        get = AsyncMock(return_value=_wallet(agent_id=agent_id, balance=750))
        with patch("src.routers.tokens.get_db", new=_db_returning(agent_id)), patch(
            "src.routers.tokens.token_service.get_wallet", new=get,
        ):
            resp = await client.get("/wallets/by-did", params={"agent_did": "did:agentx:a-001"})

        assert resp.status_code == 200
        assert resp.json()["balance"] == 750
        get.assert_awaited_once_with(agent_id)

    @pytest.mark.asyncio
    async def test_is_not_swallowed_by_the_agent_id_route(self, client):
        """`by-did` is not a UUID: without the route order it would be a 422."""
        with patch("src.routers.tokens.get_db", new=_db_returning(None)):
            resp = await client.get("/wallets/by-did", params={"agent_did": "did:agentx:nobody"})
        assert resp.status_code == 404
        assert "Agent not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_agent_without_a_wallet_is_told_how_to_open_one(self, client):
        with patch("src.routers.tokens.get_db", new=_db_returning(uuid4())), patch(
            "src.routers.tokens.token_service.get_wallet",
            new=AsyncMock(side_effect=ValueError("Wallet not found")),
        ):
            resp = await client.get("/wallets/by-did", params={"agent_did": "did:agentx:a-001"})
        assert resp.status_code == 404
        assert "POST /wallets" in resp.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("params", [{}, {"agent_did": ""}, {"agent_did": "x" * 256}])
    async def test_missing_or_oversized_did_is_a_422(self, client, params):
        resp = await client.get("/wallets/by-did", params=params)
        assert resp.status_code == 422


# ── POST /stakes ───────────────────────────────────────────────────────────────

class TestStakeTokens:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        stake = AsyncMock(return_value=_stake())
        with patch("src.routers.tokens.token_service.stake_tokens", new=stake):
            resp = await client.post(
                "/stakes", json={"agent_id": str(uuid4()), "amount": 300},
            )
        assert resp.status_code == 401
        stake.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cannot_stake_another_agents_tokens(self, client):
        stake = AsyncMock(return_value=_stake())
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.stake_tokens", new=stake,
        ):
            resp = await client.post(
                "/stakes", json={"agent_id": str(uuid4()), "amount": 300},
            )
        assert resp.status_code == 403
        stake.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owner_stake_returns_201(self, client):
        caller_id = uuid4()
        stake     = AsyncMock(return_value=_stake(agent_id=caller_id, amount=300))
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.stake_tokens", new=stake,
        ):
            resp = await client.post("/stakes", json={"amount": 300})
        assert resp.status_code == 201
        assert resp.json()["amount"] == 300
        assert stake.await_args.kwargs["agent_id"] == caller_id

    @pytest.mark.asyncio
    async def test_stake_tokens_returns_400_on_insufficient_funds(self, client):
        caller_id = uuid4()
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.stake_tokens",
            new=AsyncMock(side_effect=ValueError("Insufficient funds")),
        ):
            resp = await client.post(
                "/stakes", json={"agent_id": str(caller_id), "amount": 999999},
            )
        assert resp.status_code == 400


# ── POST /stakes/{stake_id}/release (S9-7a) ───────────────────────────────────

class TestReleaseStake:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        release = AsyncMock(return_value=_wallet())
        with patch("src.routers.tokens.token_service.release_stake", new=release):
            resp = await client.post(f"/stakes/{uuid4()}/release")
        assert resp.status_code == 401
        release.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owner_release_passes_the_callers_identity(self, client):
        caller_id, stake_id = uuid4(), uuid4()
        release = AsyncMock(return_value=_wallet(agent_id=caller_id, balance=1300))
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.release_stake", new=release,
        ):
            resp = await client.post(f"/stakes/{stake_id}/release")
        assert resp.status_code == 200
        assert resp.json()["balance"] == 1300
        release.assert_awaited_once_with(stake_id, caller_id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["MEMBER", "FOUNDER"])
    async def test_another_agents_stake_is_403(self, client, role):
        """Owner only — a FOUNDER takes a stake by slashing it, on the record."""
        with _as(_make_agent(role=role), uuid4()), patch(
            "src.routers.tokens.token_service.release_stake",
            new=AsyncMock(side_effect=PermissionError("Only the stake's owner can release it")),
        ):
            resp = await client.post(f"/stakes/{uuid4()}/release")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_released_or_locked_stake_is_409(self, client):
        from src.services.token_service import StakeConflictError
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.release_stake",
            new=AsyncMock(side_effect=StakeConflictError("Stake already released or slashed")),
        ):
            resp = await client.post(f"/stakes/{uuid4()}/release")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_unknown_stake_is_404(self, client):
        with _as(_make_agent(), uuid4()), patch(
            "src.routers.tokens.token_service.release_stake",
            new=AsyncMock(side_effect=ValueError("Stake not found: x")),
        ):
            resp = await client.post(f"/stakes/{uuid4()}/release")
        assert resp.status_code == 404


# ── Amount and page-size bounds (S9-7a) ───────────────────────────────────────

class TestBounds:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("amount", [10**12 + 1, 10**30])
    async def test_oversized_amounts_are_422_not_500(self, client, amount):
        caller_id = uuid4()
        transfer = AsyncMock(return_value=_transaction())
        stake    = AsyncMock(return_value=_stake())
        with _as(_make_agent(), caller_id), patch(
            "src.routers.tokens.token_service.transfer_tokens", new=transfer,
        ), patch("src.routers.tokens.token_service.stake_tokens", new=stake):
            r1 = await client.post(
                "/wallets/transfer", json={"to_id": str(uuid4()), "amount": amount},
            )
            r2 = await client.post("/stakes", json={"amount": amount})
        assert (r1.status_code, r2.status_code) == (422, 422)
        transfer.assert_not_awaited()
        stake.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 201, 10**9])
    async def test_transaction_page_size_is_bounded(self, client, limit):
        listing = AsyncMock(return_value=[])
        with patch("src.routers.tokens.token_service.get_transactions", new=listing):
            resp = await client.get(f"/wallets/{uuid4()}/transactions?limit={limit}")
        assert resp.status_code == 422
        listing.assert_not_awaited()


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
