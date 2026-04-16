"""
agentx_sdk — contracts namespace unit tests (no live server required).

Uses respx to mock httpx requests, same pattern as test_sdk.py / test_wallet.py.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import (
    AgentXClient,
    AgentIdentity,
    ContractResponse,
    ContractBidResponse,
    ContractResultResponse,
    ContractDisputeResponse,
    ContractsNamespace,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
CONTRACT_ID = str(uuid4())
BID_ID = str(uuid4())


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def contract_payload(**overrides) -> dict:
    return {
        "contract_id": CONTRACT_ID,
        "creator_did": AGENT_DID,
        "creator_id": str(uuid4()),
        "contractor_did": None,
        "contractor_id": None,
        "title": "Build API",
        "description": "Build a REST API",
        "contract_type": "general",
        "status": "open",
        "budget": 500,
        "escrowed_budget": 500,
        "deadline": None,
        "payload": None,
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


def bid_payload(**overrides) -> dict:
    return {
        "bid_id": BID_ID,
        "contract_id": CONTRACT_ID,
        "bidder_did": "did:agentx:bidder-001",
        "bid_amount": 400,
        "proposal": "I can do it in 2 days",
        "status": "pending",
        "created_at": "2024-06-01T13:00:00",
        **overrides,
    }


def result_payload(**overrides) -> dict:
    return {
        "result_id": str(uuid4()),
        "contract_id": CONTRACT_ID,
        "contractor_did": AGENT_DID,
        "result_payload": {"output": "done"},
        "submitted_at": "2024-06-02T12:00:00",
        **overrides,
    }


def dispute_payload(**overrides) -> dict:
    return {
        "dispute_id": str(uuid4()),
        "contract_id": CONTRACT_ID,
        "initiator_did": AGENT_DID,
        "reason": "Work not delivered",
        "status": "open",
        "created_at": "2024-06-03T12:00:00",
        **overrides,
    }


# ── Create contract ─────────────────────────────────────────────────────────

class TestCreateContract:
    @respx.mock
    def test_create_basic(self):
        payload = contract_payload()
        route = respx.post(f"{BASE}/contracts").mock(
            return_value=httpx.Response(201, json=payload)
        )
        contract = make_client().contracts.create(
            title="Build API",
            description="Build a REST API",
            budget=500,
        )
        assert isinstance(contract, ContractResponse)
        assert contract.title == "Build API"
        assert contract.budget == 500
        assert route.called
        body = json.loads(route.calls[0].request.content)
        assert body["title"] == "Build API"
        assert body["budget"] == 500
        assert "deadline" not in body
        assert "payload" not in body

    @respx.mock
    def test_create_with_capability_and_deadline(self):
        from datetime import datetime, timezone
        deadline = datetime(2024, 12, 31, tzinfo=timezone.utc)
        payload = contract_payload(
            deadline="2024-12-31T00:00:00+00:00",
            payload={"required_capability": "python"},
        )
        route = respx.post(f"{BASE}/contracts").mock(
            return_value=httpx.Response(201, json=payload)
        )
        contract = make_client().contracts.create(
            title="Build API",
            description="Build a REST API",
            budget=500,
            required_capability="python",
            deadline=deadline,
        )
        assert isinstance(contract, ContractResponse)
        body = json.loads(route.calls[0].request.content)
        assert body["deadline"] == deadline.isoformat()
        assert body["payload"]["required_capability"] == "python"


# ── List contracts ───────────────────────────────────────────────────────────

class TestListContracts:
    @respx.mock
    def test_list_array_response(self):
        items = [contract_payload(), contract_payload(title="Second")]
        respx.get(f"{BASE}/contracts").mock(
            return_value=httpx.Response(200, json=items)
        )
        contracts = make_client().contracts.list()
        assert len(contracts) == 2
        assert all(isinstance(c, ContractResponse) for c in contracts)

    @respx.mock
    def test_list_envelope_response(self):
        items = [contract_payload()]
        respx.get(f"{BASE}/contracts").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        contracts = make_client().contracts.list()
        assert len(contracts) == 1

    @respx.mock
    def test_list_with_status_filter(self):
        route = respx.get(f"{BASE}/contracts").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().contracts.list(status="assigned")
        assert "status=assigned" in str(route.calls[0].request.url)

    @respx.mock
    def test_list_no_status(self):
        route = respx.get(f"{BASE}/contracts").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().contracts.list(status=None)
        # status=None should not appear in query params (filtered by _get)
        assert "status=" not in str(route.calls[0].request.url)


# ── Bid ──────────────────────────────────────────────────────────────────────

class TestBid:
    @respx.mock
    def test_bid_with_proposal(self):
        payload = bid_payload()
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/bid").mock(
            return_value=httpx.Response(201, json=payload)
        )
        bid = make_client().contracts.bid(
            contract_id=CONTRACT_ID, amount=400, proposal="I can do it"
        )
        assert isinstance(bid, ContractBidResponse)
        assert bid.bid_amount == 400
        body = json.loads(route.calls[0].request.content)
        assert body["bid_amount"] == 400
        assert body["proposal"] == "I can do it"

    @respx.mock
    def test_bid_without_proposal(self):
        payload = bid_payload(proposal=None)
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/bid").mock(
            return_value=httpx.Response(201, json=payload)
        )
        bid = make_client().contracts.bid(contract_id=CONTRACT_ID, amount=300)
        assert bid.proposal is None
        body = json.loads(route.calls[0].request.content)
        assert "proposal" not in body


# ── Assign ───────────────────────────────────────────────────────────────────

class TestAssign:
    @respx.mock
    def test_assign(self):
        payload = contract_payload(status="assigned", contractor_did="did:agentx:bidder-001")
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/assign").mock(
            return_value=httpx.Response(200, json=payload)
        )
        contract = make_client().contracts.assign(
            contract_id=CONTRACT_ID, bid_id=BID_ID
        )
        assert isinstance(contract, ContractResponse)
        assert contract.status == "assigned"
        body = json.loads(route.calls[0].request.content)
        assert body["bid_id"] == BID_ID


# ── Submit result ────────────────────────────────────────────────────────────

class TestSubmitResult:
    @respx.mock
    def test_submit_result_with_content(self):
        payload = result_payload()
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/result").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().contracts.submit_result(
            contract_id=CONTRACT_ID,
            content={"output": "done"},
        )
        assert isinstance(result, ContractResultResponse)
        assert result.result_payload == {"output": "done"}
        body = json.loads(route.calls[0].request.content)
        assert body["result_payload"]["output"] == "done"

    @respx.mock
    def test_submit_result_with_metadata(self):
        payload = result_payload(result_payload={"output": "done", "score": 95})
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/result").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().contracts.submit_result(
            contract_id=CONTRACT_ID,
            content={"output": "done"},
            metadata={"score": 95},
        )
        body = json.loads(route.calls[0].request.content)
        assert body["result_payload"]["output"] == "done"
        assert body["result_payload"]["score"] == 95

    @respx.mock
    def test_submit_result_no_payload(self):
        payload = result_payload(result_payload=None)
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/result").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().contracts.submit_result(contract_id=CONTRACT_ID)
        body = json.loads(route.calls[0].request.content)
        assert body["result_payload"] is None


# ── Dispute ──────────────────────────────────────────────────────────────────

class TestDispute:
    @respx.mock
    def test_dispute(self):
        payload = dispute_payload()
        route = respx.post(f"{BASE}/contracts/{CONTRACT_ID}/dispute").mock(
            return_value=httpx.Response(201, json=payload)
        )
        dispute = make_client().contracts.dispute(
            contract_id=CONTRACT_ID, reason="Work not delivered"
        )
        assert isinstance(dispute, ContractDisputeResponse)
        assert dispute.reason == "Work not delivered"
        assert dispute.status == "open"
        body = json.loads(route.calls[0].request.content)
        assert body["reason"] == "Work not delivered"


# ── Namespace wiring ─────────────────────────────────────────────────────────

class TestContractsWiring:
    def test_contracts_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "contracts")
        assert isinstance(client.contracts, ContractsNamespace)
