"""
agentx_sdk — NotificationsNamespace unit tests.

respx-mocked verification of every method on ``client.notifications``.
"""
import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, NotificationsNamespace


BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
NOTIF_ID = "22222222-2222-2222-2222-222222222222"


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def envelope(**overrides) -> dict:
    return {
        "notifications": [],
        "unread_count":  0,
        "total":         0,
        "page":          1,
        "limit":         30,
        "has_more":      False,
        **overrides,
    }


# -- list ---------------------------------------------------------------------

class TestList:
    @respx.mock
    def test_list_default(self):
        route = respx.get(f"{BASE}/notifications").mock(
            return_value=httpx.Response(200, json=envelope(unread_count=2))
        )
        result = make_client().notifications.list()
        assert route.called
        assert result["unread_count"] == 2
        url = str(route.calls[0].request.url)
        assert "page=1" in url
        assert "limit=30" in url
        assert "unread_only=false" in url

    @respx.mock
    def test_list_unread_only(self):
        route = respx.get(f"{BASE}/notifications").mock(
            return_value=httpx.Response(200, json=envelope())
        )
        make_client().notifications.list(unread_only=True)
        assert "unread_only=true" in str(route.calls[0].request.url)

    @respx.mock
    def test_list_pagination(self):
        route = respx.get(f"{BASE}/notifications").mock(
            return_value=httpx.Response(200, json=envelope(page=3, limit=10))
        )
        make_client().notifications.list(page=3, limit=10)
        url = str(route.calls[0].request.url)
        assert "page=3" in url
        assert "limit=10" in url


# -- mark_read ----------------------------------------------------------------

class TestMarkRead:
    @respx.mock
    def test_mark_read_sends_patch(self):
        route = respx.patch(f"{BASE}/notifications/{NOTIF_ID}").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().notifications.mark_read(NOTIF_ID)
        assert route.called
        assert result == {}


# -- mark_all_read ------------------------------------------------------------

class TestMarkAllRead:
    @respx.mock
    def test_mark_all_read_sends_post(self):
        route = respx.post(f"{BASE}/notifications/read").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().notifications.mark_all_read()
        assert route.called
        assert result == {}


# -- Wiring -------------------------------------------------------------------

class TestNotificationsWiring:
    def test_notifications_namespace_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "notifications")
        assert isinstance(client.notifications, NotificationsNamespace)

    def test_legacy_get_notifications_still_works(self):
        # Backwards-compat: the old top-level helper must coexist
        client = make_client()
        assert callable(client.get_notifications)
