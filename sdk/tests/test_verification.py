"""
agentx_sdk — verification namespace unit tests.

Uses respx to mock httpx requests, same pattern as other test modules.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, VerificationNamespace


# -- Helpers ------------------------------------------------------------------

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
CONTRACT_ID = str(uuid4())
RESULT_ID = str(uuid4())
VERIFICATION_ID = str(uuid4())


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def verification_payload(**overrides) -> dict:
    return {
        "verification_id": VERIFICATION_ID,
        "contract_id": CONTRACT_ID,
        "result_id": RESULT_ID,
        "requester_did": AGENT_DID,
        "requester_id": None,
        "status": "pending",
        "required_votes": 3,
        "consensus_threshold": 0.67,
        "yes_power": 0.0,
        "no_power": 0.0,
        "vote_count": 0,
        "reward_pool": 100,
        "created_at": "2024-06-01T12:00:00",
        "finalized_at": None,
        **overrides,
    }


def vote_payload(**overrides) -> dict:
    return {
        "vote_id": str(uuid4()),
        "verification_id": VERIFICATION_ID,
        "verifier_did": AGENT_DID,
        "vote": "approve",
        "vote_power": 42.5,
        "comment": None,
        "created_at": "2024-06-02T08:00:00",
        **overrides,
    }


# -- Request verification ----------------------------------------------------

class TestRequestVerification:
    @respx.mock
    def test_request_basic(self):
        payload = verification_payload()
        route = respx.post(f"{BASE}/verifications").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().verification.request_verification(
            contract_id=CONTRACT_ID,
            result_id=RESULT_ID,
        )
        assert result["verification_id"] == VERIFICATION_ID
        assert result["status"] == "pending"
        body = json.loads(route.calls[0].request.content)
        assert body["contract_id"] == CONTRACT_ID
        assert body["result_id"] == RESULT_ID


# -- Submit vote --------------------------------------------------------------

class TestSubmitVote:
    @respx.mock
    def test_vote_approve(self):
        payload = vote_payload(vote="approve")
        route = respx.post(f"{BASE}/verifications/{VERIFICATION_ID}/vote").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().verification.submit_vote(
            verification_id=VERIFICATION_ID,
            vote="approve",
        )
        assert result["vote"] == "approve"
        body = json.loads(route.calls[0].request.content)
        assert body["vote"] == "approve"
        assert "comment" not in body

    @respx.mock
    def test_vote_reject_with_rationale(self):
        payload = vote_payload(vote="reject", comment="Quality too low")
        route = respx.post(f"{BASE}/verifications/{VERIFICATION_ID}/vote").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().verification.submit_vote(
            verification_id=VERIFICATION_ID,
            vote="reject",
            rationale="Quality too low",
        )
        assert result["vote"] == "reject"
        body = json.loads(route.calls[0].request.content)
        assert body["comment"] == "Quality too low"


# -- List pending -------------------------------------------------------------

class TestListPending:
    @respx.mock
    def test_list_array(self):
        items = [verification_payload(), verification_payload(status="active")]
        respx.get(f"{BASE}/verifications/pending").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().verification.list_pending()
        assert len(result) == 2

    @respx.mock
    def test_list_envelope(self):
        items = [verification_payload()]
        respx.get(f"{BASE}/verifications/pending").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        result = make_client().verification.list_pending()
        assert len(result) == 1

    @respx.mock
    def test_list_empty(self):
        respx.get(f"{BASE}/verifications/pending").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = make_client().verification.list_pending()
        assert result == []


# -- Get ----------------------------------------------------------------------

class TestGetVerification:
    @respx.mock
    def test_get(self):
        payload = verification_payload()
        respx.get(f"{BASE}/verifications/{VERIFICATION_ID}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = make_client().verification.get(VERIFICATION_ID)
        assert result["verification_id"] == VERIFICATION_ID
        assert result["contract_id"] == CONTRACT_ID


# -- Namespace wiring ---------------------------------------------------------

class TestVerificationWiring:
    def test_verification_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "verification")
        assert isinstance(client.verification, VerificationNamespace)
