"""
agentx_sdk — wallet namespace unit tests (no live server required).

Uses respx to mock httpx requests, same pattern as test_sdk.py.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import (
    AgentXClient,
    AgentXError,
    AgentIdentity,
    NotFoundError,
    WalletResponse,
    TransactionResponse,
    StakeResponse,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
AGENT_UUID = str(uuid4())
WALLET_UUID = str(uuid4())


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def wallet_payload(**overrides) -> dict:
    return {
        "wallet_id": WALLET_UUID,
        "agent_id": AGENT_UUID,
        "balance": 1000,
        "updated_at": "2024-06-01T12:00:00",
        "wallet_type": "agent",
        **overrides,
    }


def transaction_payload(**overrides) -> dict:
    return {
        "transaction_id": str(uuid4()),
        "from_wallet": str(uuid4()),
        "to_wallet": str(uuid4()),
        "amount": 50,
        "type": "PAYMENT",
        "related_id": None,
        "timestamp": "2024-06-01T12:00:00",
        **overrides,
    }


def stake_payload(**overrides) -> dict:
    return {
        "stake_id": str(uuid4()),
        "agent_id": AGENT_UUID,
        "amount": 200,
        "locked_until": "2024-12-31T23:59:59",
        "released_at": None,
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


OTHER_UUID = str(uuid4())


def mock_my_wallet(**overrides):
    """GET /wallets/by-did for this agent → its wallet (with agent UUID)."""
    return respx.get(f"{BASE}/wallets/by-did", params={"agent_did": AGENT_DID}).mock(
        return_value=httpx.Response(200, json=wallet_payload(**overrides))
    )


# ── Create wallet ────────────────────────────────────────────────────────────

class TestCreateWallet:
    @respx.mock
    def test_create_wallet_default_balance(self):
        payload = wallet_payload(balance=0)
        route = respx.post(f"{BASE}/wallets").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = make_client()
        wallet = client.wallet.create_wallet()

        assert isinstance(wallet, WalletResponse)
        assert wallet.balance == 0
        # The API takes the owner from the token; no DID in a UUID field.
        assert json.loads(route.calls[0].request.content) == {"initial_balance": 0}

    @respx.mock
    def test_create_wallet_with_balance(self):
        payload = wallet_payload(balance=500)
        respx.post(f"{BASE}/wallets").mock(
            return_value=httpx.Response(200, json=payload)
        )
        wallet = make_client().wallet.create_wallet(initial_balance=500)
        assert wallet.balance == 500

    @respx.mock
    def test_funding_without_founder_role_surfaces_403(self):
        respx.post(f"{BASE}/wallets").mock(
            return_value=httpx.Response(403, json={"detail": "FOUNDER only"})
        )
        with pytest.raises(AgentXError, match="403"):
            make_client().wallet.create_wallet(initial_balance=500)


# ── Get wallet ───────────────────────────────────────────────────────────────

class TestGetWallet:
    @respx.mock
    def test_get_wallet_by_did(self):
        route = mock_my_wallet()
        wallet = make_client().wallet.get_wallet()
        assert isinstance(wallet, WalletResponse)
        assert wallet.balance == 1000
        assert wallet.wallet_type == "agent"
        assert route.called

    @respx.mock
    def test_no_wallet_raises_not_found(self):
        respx.get(f"{BASE}/wallets/by-did").mock(
            return_value=httpx.Response(404, json={"detail": "No wallet yet"})
        )
        with pytest.raises(NotFoundError):
            make_client().wallet.get_wallet()

    def test_without_identity_raises_before_any_request(self):
        client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
        client.identity = None
        with pytest.raises(AgentXError, match="identity"):
            client.wallet.get_wallet()


# ── Transfer ─────────────────────────────────────────────────────────────────

class TestTransfer:
    @respx.mock
    def test_transfer_resolves_recipient_did_to_uuid(self):
        lookup = respx.get(
            f"{BASE}/wallets/by-did", params={"agent_did": "did:agentx:other-001"},
        ).mock(return_value=httpx.Response(200, json=wallet_payload(agent_id=OTHER_UUID)))
        route = respx.post(f"{BASE}/wallets/transfer").mock(
            return_value=httpx.Response(200, json=transaction_payload(type="payment"))
        )
        tx = make_client().wallet.transfer(to_did="did:agentx:other-001", amount=50)

        assert isinstance(tx, TransactionResponse)
        assert tx.amount == 50
        assert lookup.called
        body = json.loads(route.calls[0].request.content)
        # Sender comes from the token; recipient is a UUID; type is allowlisted.
        assert body == {"to_id": OTHER_UUID, "amount": 50, "type": "payment"}

    @respx.mock
    def test_transfer_to_uuid_skips_lookup(self):
        route = respx.post(f"{BASE}/wallets/transfer").mock(
            return_value=httpx.Response(200, json=transaction_payload(type="tip"))
        )
        tx = make_client().wallet.transfer(to_did=OTHER_UUID, amount=100, tx_type="tip")
        assert tx.type == "tip"
        assert json.loads(route.calls[0].request.content)["to_id"] == OTHER_UUID

    @respx.mock
    def test_recipient_without_wallet_raises_not_found(self):
        respx.get(f"{BASE}/wallets/by-did").mock(
            return_value=httpx.Response(404, json={"detail": "No wallet yet"})
        )
        transfer = respx.post(f"{BASE}/wallets/transfer")
        with pytest.raises(NotFoundError):
            make_client().wallet.transfer(to_did="did:agentx:nobody-001", amount=1)
        assert not transfer.called

    @respx.mock
    def test_insufficient_funds_surfaces_400(self):
        respx.post(f"{BASE}/wallets/transfer").mock(
            return_value=httpx.Response(400, json={"detail": "Insufficient funds"})
        )
        with pytest.raises(AgentXError, match="Insufficient"):
            make_client().wallet.transfer(to_did=OTHER_UUID, amount=10**6)


# ── List transactions ────────────────────────────────────────────────────────

class TestListTransactions:
    @respx.mock
    def test_list_transactions_array(self):
        mock_my_wallet()
        items = [transaction_payload(), transaction_payload()]
        respx.get(f"{BASE}/wallets/{AGENT_UUID}/transactions").mock(
            return_value=httpx.Response(200, json=items)
        )
        txs = make_client().wallet.list_transactions()
        assert len(txs) == 2
        assert all(isinstance(t, TransactionResponse) for t in txs)

    @respx.mock
    def test_list_transactions_envelope(self):
        mock_my_wallet()
        items = [transaction_payload()]
        respx.get(f"{BASE}/wallets/{AGENT_UUID}/transactions").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        txs = make_client().wallet.list_transactions()
        assert len(txs) == 1

    @respx.mock
    def test_list_transactions_with_limit(self):
        mock_my_wallet()
        route = respx.get(f"{BASE}/wallets/{AGENT_UUID}/transactions").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().wallet.list_transactions(limit=10)
        assert "limit=10" in str(route.calls[0].request.url)

    @respx.mock
    def test_uuid_is_looked_up_once_per_client(self):
        lookup = mock_my_wallet()
        respx.get(f"{BASE}/wallets/{AGENT_UUID}/transactions").mock(
            return_value=httpx.Response(200, json=[])
        )
        client = make_client()
        client.wallet.list_transactions()
        client.wallet.list_transactions()
        assert lookup.call_count == 1

    @respx.mock
    def test_opens_empty_wallet_when_agent_has_none(self):
        respx.get(f"{BASE}/wallets/by-did").mock(
            return_value=httpx.Response(404, json={"detail": "No wallet yet"})
        )
        opened = respx.post(f"{BASE}/wallets").mock(
            return_value=httpx.Response(200, json=wallet_payload(balance=0))
        )
        respx.get(f"{BASE}/wallets/{AGENT_UUID}/transactions").mock(
            return_value=httpx.Response(200, json=[])
        )
        assert make_client().wallet.list_transactions() == []
        assert json.loads(opened.calls[0].request.content) == {"initial_balance": 0}


# ── Stake ────────────────────────────────────────────────────────────────────

class TestStake:
    @respx.mock
    def test_stake_without_lock(self):
        payload = stake_payload(locked_until=None)
        route = respx.post(f"{BASE}/stakes").mock(
            return_value=httpx.Response(201, json=payload)
        )
        stake = make_client().wallet.stake(amount=200)

        assert isinstance(stake, StakeResponse)
        assert stake.amount == 200
        assert json.loads(route.calls[0].request.content) == {"amount": 200}

    @respx.mock
    def test_stake_with_lock(self):
        lock_dt = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        payload = stake_payload()
        route = respx.post(f"{BASE}/stakes").mock(
            return_value=httpx.Response(201, json=payload)
        )
        stake = make_client().wallet.stake(amount=200, locked_until=lock_dt)

        assert isinstance(stake, StakeResponse)
        body = json.loads(route.calls[0].request.content)
        assert body["locked_until"] == lock_dt.isoformat()
        assert "agent_id" not in body


class TestReleaseStake:
    @respx.mock
    def test_release_returns_wallet(self):
        stake_id = str(uuid4())
        route = respx.post(f"{BASE}/stakes/{stake_id}/release").mock(
            return_value=httpx.Response(200, json=wallet_payload(balance=1200))
        )
        wallet = make_client().wallet.release_stake(stake_id)
        assert isinstance(wallet, WalletResponse)
        assert wallet.balance == 1200
        assert route.called

    @respx.mock
    def test_locked_stake_surfaces_409(self):
        stake_id = str(uuid4())
        respx.post(f"{BASE}/stakes/{stake_id}/release").mock(
            return_value=httpx.Response(409, json={"detail": "Stake is still locked"})
        )
        with pytest.raises(AgentXError, match="409"):
            make_client().wallet.release_stake(stake_id)


# ── List stakes ──────────────────────────────────────────────────────────────

class TestListStakes:
    @respx.mock
    def test_list_stakes_array(self):
        mock_my_wallet()
        items = [stake_payload(), stake_payload()]
        respx.get(f"{BASE}/stakes/{AGENT_UUID}").mock(
            return_value=httpx.Response(200, json=items)
        )
        stakes = make_client().wallet.list_stakes()
        assert len(stakes) == 2
        assert all(isinstance(s, StakeResponse) for s in stakes)

    @respx.mock
    def test_list_stakes_envelope(self):
        mock_my_wallet()
        items = [stake_payload()]
        respx.get(f"{BASE}/stakes/{AGENT_UUID}").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        stakes = make_client().wallet.list_stakes()
        assert len(stakes) == 1


# ── get_balance convenience ──────────────────────────────────────────────────

class TestGetBalance:
    @respx.mock
    def test_get_balance(self):
        mock_my_wallet(balance=42)
        balance = make_client().wallet.get_balance()
        assert balance == 42


# ── WalletNamespace is wired into client ─────────────────────────────────────

class TestNamespaceWiring:
    def test_wallet_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "wallet")
        from agentx_sdk.wallet import WalletNamespace
        assert isinstance(client.wallet, WalletNamespace)
