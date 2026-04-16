"""
agentx_sdk — capabilities namespace unit tests.

Uses respx to mock httpx requests, same pattern as other test modules.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, CapabilitiesNamespace


# -- Helpers ------------------------------------------------------------------

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
CAP_ID = "infrastructure.kubernetes.basic"


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def cap_payload(**overrides) -> dict:
    return {
        "capability_id": CAP_ID,
        "name": "Kubernetes",
        "description": "Container orchestration",
        "domain": "INFRASTRUCTURE",
        "level": "BASIC",
        "requires_verification": False,
        "rep_reward": 10,
        "prerequisites": [],
        "verified_by": [],
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


def agent_cap_payload(**overrides) -> dict:
    return {
        "capability_id": CAP_ID,
        "name": "Kubernetes",
        "domain": "INFRASTRUCTURE",
        "level": "BASIC",
        "verified": False,
        "verified_by_count": 0,
        "acquired_at": "2024-06-01T12:00:00",
        **overrides,
    }


# -- List all -----------------------------------------------------------------

class TestListAll:
    @respx.mock
    def test_list_array(self):
        items = [cap_payload(), cap_payload(capability_id="data.pandas.basic")]
        respx.get(f"{BASE}/capabilities").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().capabilities.list_all()
        assert len(result) == 2

    @respx.mock
    def test_list_envelope(self):
        items = [cap_payload()]
        respx.get(f"{BASE}/capabilities").mock(
            return_value=httpx.Response(200, json={"capabilities": items, "total": 1, "page": 1, "limit": 50})
        )
        result = make_client().capabilities.list_all()
        assert len(result) == 1

    @respx.mock
    def test_list_with_domain(self):
        route = respx.get(f"{BASE}/capabilities").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().capabilities.list_all(domain="INFRASTRUCTURE")
        assert "domain=INFRASTRUCTURE" in str(route.calls[0].request.url)


# -- Register -----------------------------------------------------------------

class TestRegister:
    @respx.mock
    def test_register_basic(self):
        payload = cap_payload()
        route = respx.post(f"{BASE}/capabilities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().capabilities.register(
            name="Kubernetes",
            domain="INFRASTRUCTURE",
            description="Container orchestration",
        )
        assert result["capability_id"] == CAP_ID
        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "Kubernetes"
        assert body["domain"] == "INFRASTRUCTURE"

    @respx.mock
    def test_register_custom_id(self):
        payload = cap_payload(capability_id="security.audit.expert")
        route = respx.post(f"{BASE}/capabilities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().capabilities.register(
            name="Audit",
            domain="SECURITY",
            capability_id="security.audit.expert",
            level="EXPERT",
        )
        body = json.loads(route.calls[0].request.content)
        assert body["capability_id"] == "security.audit.expert"
        assert body["level"] == "EXPERT"


# -- Add to agent -------------------------------------------------------------

class TestAddToAgent:
    @respx.mock
    def test_add_self(self):
        payload = agent_cap_payload()
        route = respx.post(f"{BASE}/agents/{AGENT_DID}/capabilities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().capabilities.add_to_agent(CAP_ID)
        assert result["capability_id"] == CAP_ID
        body = json.loads(route.calls[0].request.content)
        assert body["capability_id"] == CAP_ID

    @respx.mock
    def test_add_explicit_did(self):
        other = "did:agentx:other-001"
        route = respx.post(f"{BASE}/agents/{other}/capabilities").mock(
            return_value=httpx.Response(201, json=agent_cap_payload())
        )
        make_client().capabilities.add_to_agent(CAP_ID, agent_did=other)
        assert route.called


# -- Remove from agent --------------------------------------------------------

class TestRemoveFromAgent:
    @respx.mock
    def test_remove_self(self):
        respx.delete(f"{BASE}/agents/{AGENT_DID}/capabilities/{CAP_ID}").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().capabilities.remove_from_agent(CAP_ID)
        assert result == {}


# -- Route by capability ------------------------------------------------------

class TestRouteByCapability:
    @respx.mock
    def test_route_array(self):
        agents = [
            {"agent_did": AGENT_DID, "display_name": "Bot", "score": 0.9,
             "capability_match_score": 1.0, "trust_score": 0.8,
             "rep_balance": 100, "missing_capabilities": []},
        ]
        respx.post(f"{BASE}/capabilities/route").mock(
            return_value=httpx.Response(200, json=agents)
        )
        result = make_client().capabilities.route_by_capability(
            required_capabilities=[CAP_ID]
        )
        assert len(result) == 1
        assert result[0]["score"] == 0.9

    @respx.mock
    def test_route_sends_body(self):
        route = respx.post(f"{BASE}/capabilities/route").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().capabilities.route_by_capability(
            required_capabilities=[CAP_ID, "data.pandas.basic"],
            limit=10,
            min_trust_score=0.5,
        )
        body = json.loads(route.calls[0].request.content)
        assert body["required_capabilities"] == [CAP_ID, "data.pandas.basic"]
        assert body["limit"] == 10
        assert body["min_trust_score"] == 0.5


# -- List agent capabilities --------------------------------------------------

class TestListAgentCapabilities:
    @respx.mock
    def test_list_self(self):
        items = [agent_cap_payload()]
        respx.get(f"{BASE}/agents/{AGENT_DID}/capabilities").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().capabilities.list_agent_capabilities()
        assert len(result) == 1

    @respx.mock
    def test_list_explicit_did(self):
        other = "did:agentx:other-001"
        route = respx.get(f"{BASE}/agents/{other}/capabilities").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().capabilities.list_agent_capabilities(agent_did=other)
        assert route.called


# -- Namespace wiring ---------------------------------------------------------

class TestCapabilitiesWiring:
    def test_capabilities_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "capabilities")
        assert isinstance(client.capabilities, CapabilitiesNamespace)
