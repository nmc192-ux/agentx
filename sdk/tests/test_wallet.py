"""
agentx_sdk — wallet namespace unit tests (no live server required).

Uses respx to mock httpx requests, same pattern as test_sdk.py.
"""
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import (
    AgentXClient,
    AgentIdentity,
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
        assert route.called
        sent = route.calls[0].request.content
        import json
        body = json.loads(sent)
        assert body["agent_id"] == AGENT_DID
        assert body["initial_balance"] == 0

    @respx.mock
    def test_create_wallet_with_balance(self):
        payload = wallet_payload(balance=500)
        respx.post(f"{BASE}/wallets").mock(
            return_value=httpx.Response(200, json=payload)
        )
        wallet = make_client().wallet.create_wallet(initial_balance=500)
        assert wallet.balance == 500


# ── Get wallet ───────────────────────────────────────────────────────────────

class TestGetWallet:
    @respx.mock
    def test_get_wallet(self):
        payload = wallet_payload()
        respx.get(f"{BASE}/wallets/{AGENT_DID}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        wallet = make_client().wallet.get_wallet()
        assert isinstance(wallet, WalletResponse)
        assert wallet.balance == 1000
        assert wallet.wallet_type == "agent"


# ── Transfer ─────────────────────────────────────────────────────────────────

class TestTransfer:
    @respx.mock
    def test_transfer_default_type(self):
        payload = transaction_payload()
        route = respx.post(f"{BASE}/wallets/transfer").mock(
            return_value=httpx.Response(200, json=payload)
        )
        tx = make_client().wallet.transfer(to_did="did:agentx:other-001", amount=50)

        assert isinstance(tx, TransactionResponse)
        assert tx.amount == 50
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["from_id"] == AGENT_DID
        assert body["to_id"] == "did:agentx:other-001"
        assert body["type"] == "PAYMENT"

    @respx.mock
    def test_transfer_custom_type(self):
        payload = transaction_payload(type="REWARD")
        respx.post(f"{BASE}/wallets/transfer").mock(
            return_value=httpx.Response(200, json=payload)
        )
        tx = make_client().wallet.transfer(
            to_did="did:agentx:other-001", amount=100, tx_type="REWARD"
        )
        assert tx.type == "REWARD"


# ── List transactions ────────────────────────────────────────────────────────

class TestListTransactions:
    @respx.mock
    def test_list_transactions_array(self):
        items = [transaction_payload(), transaction_payload()]
        respx.get(f"{BASE}/wallets/{AGENT_DID}/transactions").mock(
            return_value=httpx.Response(200, json=items)
        )
        txs = make_client().wallet.list_transactions()
        assert len(txs) == 2
        assert all(isinstance(t, TransactionResponse) for t in txs)

    @respx.mock
    def test_list_transactions_envelope(self):
        items = [transaction_payload()]
        respx.get(f"{BASE}/wallets/{AGENT_DID}/transactions").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        txs = make_client().wallet.list_transactions()
        assert len(txs) == 1

    @respx.mock
    def test_list_transactions_with_limit(self):
        route = respx.get(f"{BASE}/wallets/{AGENT_DID}/transactions").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().wallet.list_transactions(limit=10)
        assert "limit=10" in str(route.calls[0].request.url)


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
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["agent_id"] == AGENT_DID
        assert "locked_until" not in body

    @respx.mock
    def test_stake_with_lock(self):
        lock_dt = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        payload = stake_payload()
        route = respx.post(f"{BASE}/stakes").mock(
            return_value=httpx.Response(201, json=payload)
        )
        stake = make_client().wallet.stake(amount=200, locked_until=lock_dt)

        assert isinstance(stake, StakeResponse)
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["locked_until"] == lock_dt.isoformat()


# ── List stakes ──────────────────────────────────────────────────────────────

class TestListStakes:
    @respx.mock
    def test_list_stakes_array(self):
        items = [stake_payload(), stake_payload()]
        respx.get(f"{BASE}/stakes/{AGENT_DID}").mock(
            return_value=httpx.Response(200, json=items)
        )
        stakes = make_client().wallet.list_stakes()
        assert len(stakes) == 2
        assert all(isinstance(s, StakeResponse) for s in stakes)

    @respx.mock
    def test_list_stakes_envelope(self):
        items = [stake_payload()]
        respx.get(f"{BASE}/stakes/{AGENT_DID}").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        stakes = make_client().wallet.list_stakes()
        assert len(stakes) == 1


# ── get_balance convenience ──────────────────────────────────────────────────

class TestGetBalance:
    @respx.mock
    def test_get_balance(self):
        payload = wallet_payload(balance=42)
        respx.get(f"{BASE}/wallets/{AGENT_DID}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        balance = make_client().wallet.get_balance()
        assert balance == 42


# ── WalletNamespace is wired into client ─────────────────────────────────────

class TestNamespaceWiring:
    def test_wallet_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "wallet")
        from agentx_sdk.wallet import WalletNamespace
        assert isinstance(client.wallet, WalletNamespace)
