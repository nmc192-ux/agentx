"""
agentx_sdk — collectives namespace unit tests.

Uses respx to mock httpx requests, same pattern as other test modules.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, CollectivesNamespace


# -- Helpers ------------------------------------------------------------------

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
COLLECTIVE_ID = str(uuid4())
MEMBER_DID = "did:agentx:member-001"


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def collective_payload(**overrides) -> dict:
    return {
        "collective_id": COLLECTIVE_ID,
        "name": "Test Collective",
        "description": "A test collective",
        "creator_did": AGENT_DID,
        "is_public": True,
        "charter": None,
        "member_count": 1,
        "created_at": "2024-06-01T12:00:00",
        **overrides,
    }


def member_payload(**overrides) -> dict:
    return {
        "agent_did": MEMBER_DID,
        "display_name": "Member Agent",
        "role": "member",
        "joined_at": "2024-06-02T08:00:00",
        **overrides,
    }


# -- Create -------------------------------------------------------------------

class TestCreateCollective:
    @respx.mock
    def test_create_basic(self):
        payload = collective_payload()
        route = respx.post(f"{BASE}/collectives").mock(
            return_value=httpx.Response(201, json=payload)
        )
        result = make_client().collectives.create(
            name="Test Collective",
            description="A test collective",
        )
        assert result["name"] == "Test Collective"
        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "Test Collective"
        assert body["is_public"] is True

    @respx.mock
    def test_create_with_charter(self):
        payload = collective_payload(charter="Our charter text")
        route = respx.post(f"{BASE}/collectives").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().collectives.create(
            name="Test",
            description="Desc",
            charter="Our charter text",
        )
        body = json.loads(route.calls[0].request.content)
        assert body["charter"] == "Our charter text"

    @respx.mock
    def test_create_private(self):
        payload = collective_payload(is_public=False)
        route = respx.post(f"{BASE}/collectives").mock(
            return_value=httpx.Response(201, json=payload)
        )
        make_client().collectives.create(
            name="Private",
            description="Secret",
            is_public=False,
        )
        body = json.loads(route.calls[0].request.content)
        assert body["is_public"] is False


# -- List ---------------------------------------------------------------------

class TestListCollectives:
    @respx.mock
    def test_list_array(self):
        items = [collective_payload(), collective_payload(name="Second")]
        respx.get(f"{BASE}/collectives").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().collectives.list()
        assert len(result) == 2

    @respx.mock
    def test_list_envelope(self):
        items = [collective_payload()]
        respx.get(f"{BASE}/collectives").mock(
            return_value=httpx.Response(200, json={"collectives": items, "total": 1})
        )
        result = make_client().collectives.list()
        assert len(result) == 1

    @respx.mock
    def test_list_limit_param(self):
        route = respx.get(f"{BASE}/collectives").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().collectives.list(limit=10)
        assert "limit=10" in str(route.calls[0].request.url)


# -- Get ----------------------------------------------------------------------

class TestGetCollective:
    @respx.mock
    def test_get(self):
        payload = collective_payload()
        respx.get(f"{BASE}/collectives/{COLLECTIVE_ID}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = make_client().collectives.get(COLLECTIVE_ID)
        assert result["collective_id"] == COLLECTIVE_ID


# -- Members ------------------------------------------------------------------

class TestMembers:
    @respx.mock
    def test_members_array(self):
        items = [member_payload(), member_payload(agent_did="did:agentx:m2-001")]
        respx.get(f"{BASE}/collectives/{COLLECTIVE_ID}/members").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().collectives.members(COLLECTIVE_ID)
        assert len(result) == 2

    @respx.mock
    def test_members_envelope(self):
        items = [member_payload()]
        respx.get(f"{BASE}/collectives/{COLLECTIVE_ID}/members").mock(
            return_value=httpx.Response(200, json={"members": items, "total": 1})
        )
        result = make_client().collectives.members(COLLECTIVE_ID)
        assert len(result) == 1


# -- Join ---------------------------------------------------------------------

class TestJoin:
    @respx.mock
    def test_join_basic(self):
        respx.post(f"{BASE}/collectives/{COLLECTIVE_ID}/join").mock(
            return_value=httpx.Response(200, json={"status": "pending"})
        )
        result = make_client().collectives.join(COLLECTIVE_ID)
        assert result["status"] == "pending"

    @respx.mock
    def test_join_with_message(self):
        route = respx.post(f"{BASE}/collectives/{COLLECTIVE_ID}/join").mock(
            return_value=httpx.Response(200, json={"status": "pending"})
        )
        make_client().collectives.join(COLLECTIVE_ID, message="Let me in!")
        body = json.loads(route.calls[0].request.content)
        assert body["message"] == "Let me in!"


# -- Approve ------------------------------------------------------------------

class TestApprove:
    @respx.mock
    def test_approve(self):
        respx.post(
            f"{BASE}/collectives/{COLLECTIVE_ID}/members/{MEMBER_DID}/approve"
        ).mock(return_value=httpx.Response(200, json={"status": "approved"}))
        result = make_client().collectives.approve(COLLECTIVE_ID, MEMBER_DID)
        assert result["status"] == "approved"


# -- Assign Task --------------------------------------------------------------

class TestAssignTask:
    @respx.mock
    def test_assign_task(self):
        task_id = str(uuid4())
        route = respx.post(f"{BASE}/collectives/{COLLECTIVE_ID}/tasks").mock(
            return_value=httpx.Response(201, json={"task_id": task_id, "status": "assigned"})
        )
        result = make_client().collectives.assign_task(
            COLLECTIVE_ID, {"task_id": task_id}
        )
        assert result["task_id"] == task_id
        body = json.loads(route.calls[0].request.content)
        assert body["task_id"] == task_id


# -- Namespace wiring --------------------------------------------------------

class TestCollectivesWiring:
    def test_collectives_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "collectives")
        assert isinstance(client.collectives, CollectivesNamespace)
