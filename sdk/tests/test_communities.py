"""
agentx_sdk — communities namespace unit tests.

Uses respx to mock httpx requests, same pattern as other test modules.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, CommunitiesNamespace


# -- Helpers ------------------------------------------------------------------

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
COMMUNITY_ID = str(uuid4())


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def community_payload(**overrides) -> dict:
    return {
        "community_id": COMMUNITY_ID,
        "name": "Python Devs",
        "slug": "python-devs",
        "description": "A community for Python developers",
        "creator_did": AGENT_DID,
        "visibility": "PUBLIC",
        "status": "ACTIVE",
        "member_count": 1,
        "metadata": {},
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


def member_payload(**overrides) -> dict:
    return {
        "community_id": COMMUNITY_ID,
        "agent_did": AGENT_DID,
        "role": "ADMIN",
        "joined_at": "2024-06-01T12:00:00",
        **overrides,
    }


# -- Create -------------------------------------------------------------------

class TestCreateCommunity:
    @respx.mock
    def test_create_basic(self):
        payload = community_payload()
        route = respx.post(f"{BASE}/communities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().communities.create(
            name="Python Devs",
            description="A community for Python developers",
        )
        assert result["name"] == "Python Devs"
        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "Python Devs"
        assert body["slug"] == "python-devs"
        assert body["visibility"] == "PUBLIC"

    @respx.mock
    def test_create_with_slug(self):
        payload = community_payload(slug="py-community")
        route = respx.post(f"{BASE}/communities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().communities.create(
            name="Python Devs",
            slug="py-community",
        )
        body = json.loads(route.calls[0].request.content)
        assert body["slug"] == "py-community"

    @respx.mock
    def test_create_private(self):
        payload = community_payload(visibility="PRIVATE")
        route = respx.post(f"{BASE}/communities").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().communities.create(
            name="Secret Club",
            visibility="PRIVATE",
        )
        body = json.loads(route.calls[0].request.content)
        assert body["visibility"] == "PRIVATE"


# -- List ---------------------------------------------------------------------

class TestListCommunities:
    @respx.mock
    def test_list_array(self):
        items = [community_payload(), community_payload(name="Rust Devs")]
        respx.get(f"{BASE}/communities").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().communities.list()
        assert len(result) == 2

    @respx.mock
    def test_list_envelope(self):
        items = [community_payload()]
        respx.get(f"{BASE}/communities").mock(
            return_value=httpx.Response(200, json={"communities": items, "total": 1})
        )
        result = make_client().communities.list()
        assert len(result) == 1

    @respx.mock
    def test_list_with_params(self):
        route = respx.get(f"{BASE}/communities").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().communities.list(limit=10, status="ARCHIVED")
        url = str(route.calls[0].request.url)
        assert "limit=10" in url
        assert "status=ARCHIVED" in url


# -- Get ----------------------------------------------------------------------

class TestGetCommunity:
    @respx.mock
    def test_get(self):
        payload = community_payload()
        respx.get(f"{BASE}/communities/{COMMUNITY_ID}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = make_client().communities.get(COMMUNITY_ID)
        assert result["community_id"] == COMMUNITY_ID
        assert result["name"] == "Python Devs"


# -- Join ---------------------------------------------------------------------

class TestJoinCommunity:
    @respx.mock
    def test_join(self):
        payload = member_payload()
        respx.post(f"{BASE}/communities/{COMMUNITY_ID}/join").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = make_client().communities.join(COMMUNITY_ID)
        assert result["community_id"] == COMMUNITY_ID
        assert result["agent_did"] == AGENT_DID


# -- Leave --------------------------------------------------------------------

class TestLeaveCommunity:
    @respx.mock
    def test_leave(self):
        respx.post(f"{BASE}/communities/{COMMUNITY_ID}/leave").mock(
            return_value=httpx.Response(200, json={"status": "left"})
        )
        result = make_client().communities.leave(COMMUNITY_ID)
        assert result["status"] == "left"


# -- Namespace wiring ---------------------------------------------------------

class TestCommunitiesWiring:
    def test_communities_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "communities")
        assert isinstance(client.communities, CommunitiesNamespace)
