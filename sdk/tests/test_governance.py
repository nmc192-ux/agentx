"""
agentx_sdk — governance namespace unit tests (no live server required).

Uses respx to mock httpx requests, same pattern as test_sdk.py.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import (
    AgentXClient,
    AgentIdentity,
    ProposalResponse,
    VoteResponse,
    GovernanceNamespace,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
PROPOSAL_ID = str(uuid4())


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def proposal_payload(**overrides) -> dict:
    return {
        "proposal_id": PROPOSAL_ID,
        "proposer_did": AGENT_DID,
        "proposer_id": str(uuid4()),
        "title": "Increase stake minimum",
        "description": "Raise the minimum stake from 10 to 50 tokens",
        "proposal_type": "parameter_change",
        "status": "active",
        "payload": {"min_stake": 50},
        "yes_power": 120.0,
        "no_power": 30.0,
        "voting_ends_at": "2024-07-01T00:00:00",
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


def vote_payload(**overrides) -> dict:
    return {
        "vote_id": str(uuid4()),
        "proposal_id": PROPOSAL_ID,
        "voter_did": AGENT_DID,
        "vote": "yes",
        "vote_power": 42.5,
        "created_at": "2024-06-02T08:00:00",
        **overrides,
    }


# ── Create proposal ─────────────────────────────────────────────────────────

class TestCreateProposal:
    @respx.mock
    def test_create_basic(self):
        payload = proposal_payload()
        route = respx.post(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(201, json=payload)
        )
        proposal = make_client().governance.create_proposal(
            title="Increase stake minimum",
            description="Raise the minimum stake from 10 to 50 tokens",
            proposal_type="parameter_change",
        )
        assert isinstance(proposal, ProposalResponse)
        assert proposal.title == "Increase stake minimum"
        assert proposal.yes_power == 120.0
        body = json.loads(route.calls[0].request.content)
        assert body["title"] == "Increase stake minimum"
        assert body["proposal_type"] == "parameter_change"
        assert body["voting_days"] == 7
        assert "payload" not in body

    @respx.mock
    def test_create_with_options_and_voting_days(self):
        payload = proposal_payload()
        route = respx.post(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().governance.create_proposal(
            title="Test",
            description="Desc",
            options={"min_stake": 50},
            voting_days=14,
        )
        body = json.loads(route.calls[0].request.content)
        assert body["payload"] == {"min_stake": 50}
        assert body["voting_days"] == 14

    @respx.mock
    def test_create_defaults(self):
        payload = proposal_payload(proposal_type="general")
        route = respx.post(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().governance.create_proposal(
            title="General idea",
            description="Let's do something",
        )
        body = json.loads(route.calls[0].request.content)
        assert body["proposal_type"] == "general"
        assert body["voting_days"] == 7


# ── List proposals ───────────────────────────────────────────────────────────

class TestListProposals:
    @respx.mock
    def test_list_array(self):
        items = [proposal_payload(), proposal_payload(title="Second")]
        respx.get(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(200, json=items)
        )
        proposals = make_client().governance.list_proposals()
        assert len(proposals) == 2
        assert all(isinstance(p, ProposalResponse) for p in proposals)

    @respx.mock
    def test_list_envelope(self):
        items = [proposal_payload()]
        respx.get(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        proposals = make_client().governance.list_proposals()
        assert len(proposals) == 1

    @respx.mock
    def test_list_with_status(self):
        route = respx.get(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().governance.list_proposals(status="passed")
        assert "status=passed" in str(route.calls[0].request.url)

    @respx.mock
    def test_list_no_status(self):
        route = respx.get(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().governance.list_proposals(status=None)
        assert "status=" not in str(route.calls[0].request.url)


# ── Vote ─────────────────────────────────────────────────────────────────────

class TestVote:
    @respx.mock
    def test_vote_yes(self):
        payload = vote_payload(vote="yes")
        route = respx.post(f"{BASE}/governance/vote").mock(
            return_value=httpx.Response(201, json=payload)
        )
        vote = make_client().governance.vote(
            proposal_id=PROPOSAL_ID, option="yes"
        )
        assert isinstance(vote, VoteResponse)
        assert vote.vote == "yes"
        assert vote.vote_power == 42.5
        body = json.loads(route.calls[0].request.content)
        assert body["proposal_id"] == PROPOSAL_ID
        assert body["vote"] == "yes"

    @respx.mock
    def test_vote_no(self):
        payload = vote_payload(vote="no")
        respx.post(f"{BASE}/governance/vote").mock(
            return_value=httpx.Response(201, json=payload)
        )
        vote = make_client().governance.vote(
            proposal_id=PROPOSAL_ID, option="no"
        )
        assert vote.vote == "no"

    @respx.mock
    def test_vote_abstain(self):
        payload = vote_payload(vote="abstain", vote_power=0.0)
        respx.post(f"{BASE}/governance/vote").mock(
            return_value=httpx.Response(201, json=payload)
        )
        vote = make_client().governance.vote(
            proposal_id=PROPOSAL_ID, option="abstain"
        )
        assert vote.vote == "abstain"


# ── Get results ──────────────────────────────────────────────────────────────

class TestGetResults:
    @respx.mock
    def test_results_array(self):
        items = [
            proposal_payload(status="passed"),
            proposal_payload(status="failed"),
            proposal_payload(status="executed"),
        ]
        respx.get(f"{BASE}/governance/results").mock(
            return_value=httpx.Response(200, json=items)
        )
        results = make_client().governance.get_results()
        assert len(results) == 3
        assert all(isinstance(r, ProposalResponse) for r in results)
        statuses = {r.status for r in results}
        assert statuses == {"passed", "failed", "executed"}

    @respx.mock
    def test_results_empty(self):
        respx.get(f"{BASE}/governance/results").mock(
            return_value=httpx.Response(200, json=[])
        )
        results = make_client().governance.get_results()
        assert results == []

    @respx.mock
    def test_results_envelope(self):
        items = [proposal_payload(status="passed")]
        respx.get(f"{BASE}/governance/results").mock(
            return_value=httpx.Response(200, json={"items": items, "total": 1})
        )
        results = make_client().governance.get_results()
        assert len(results) == 1


# ── Namespace wiring ─────────────────────────────────────────────────────────

class TestGovernanceWiring:
    def test_governance_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "governance")
        assert isinstance(client.governance, GovernanceNamespace)
