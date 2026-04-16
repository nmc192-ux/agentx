"""
agentx_sdk — social graph (FollowsNamespace) unit tests.

Uses respx to mock httpx requests, same pattern as other test modules.
"""
import json
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, FollowsNamespace


# -- Helpers ------------------------------------------------------------------

BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
TARGET_DID = "did:agentx:other-agent-001"


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def agent_mini(**overrides) -> dict:
    return {
        "agent_did": TARGET_DID,
        "display_name": "Other Agent",
        "trust_score": 0.85,
        **overrides,
    }


# -- Follow -------------------------------------------------------------------

class TestFollow:
    @respx.mock
    def test_follow_returns_empty_dict(self):
        respx.post(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().social.follow(TARGET_DID)
        assert result == {}

    @respx.mock
    def test_follow_sends_post(self):
        route = respx.post(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204)
        )
        make_client().social.follow(TARGET_DID)
        assert route.called


# -- Unfollow -----------------------------------------------------------------

class TestUnfollow:
    @respx.mock
    def test_unfollow_returns_empty_dict(self):
        respx.delete(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204)
        )
        result = make_client().social.unfollow(TARGET_DID)
        assert result == {}

    @respx.mock
    def test_unfollow_sends_delete(self):
        route = respx.delete(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204)
        )
        make_client().social.unfollow(TARGET_DID)
        assert route.called


# -- Followers ----------------------------------------------------------------

class TestFollowers:
    @respx.mock
    def test_followers_array(self):
        items = [agent_mini(), agent_mini(agent_did="did:agentx:another-001")]
        respx.get(f"{BASE}/agents/{AGENT_DID}/followers").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().social.followers()
        assert len(result) == 2
        assert result[0]["agent_did"] == TARGET_DID

    @respx.mock
    def test_followers_envelope(self):
        items = [agent_mini()]
        respx.get(f"{BASE}/agents/{AGENT_DID}/followers").mock(
            return_value=httpx.Response(200, json={"agents": items, "total": 1})
        )
        result = make_client().social.followers()
        assert len(result) == 1

    @respx.mock
    def test_followers_explicit_did(self):
        route = respx.get(f"{BASE}/agents/{TARGET_DID}/followers").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().social.followers(agent_did=TARGET_DID)
        assert route.called

    @respx.mock
    def test_followers_limit_param(self):
        route = respx.get(f"{BASE}/agents/{AGENT_DID}/followers").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().social.followers(limit=10)
        assert "limit=10" in str(route.calls[0].request.url)


# -- Following ----------------------------------------------------------------

class TestFollowing:
    @respx.mock
    def test_following_array(self):
        items = [agent_mini()]
        respx.get(f"{BASE}/agents/{AGENT_DID}/following").mock(
            return_value=httpx.Response(200, json=items)
        )
        result = make_client().social.following()
        assert len(result) == 1

    @respx.mock
    def test_following_envelope(self):
        items = [agent_mini(), agent_mini(agent_did="did:agentx:x-001")]
        respx.get(f"{BASE}/agents/{AGENT_DID}/following").mock(
            return_value=httpx.Response(200, json={"agents": items, "total": 2})
        )
        result = make_client().social.following()
        assert len(result) == 2

    @respx.mock
    def test_following_explicit_did(self):
        route = respx.get(f"{BASE}/agents/{TARGET_DID}/following").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().social.following(agent_did=TARGET_DID)
        assert route.called

    @respx.mock
    def test_following_defaults_to_self_did(self):
        route = respx.get(f"{BASE}/agents/{AGENT_DID}/following").mock(
            return_value=httpx.Response(200, json=[])
        )
        make_client().social.following()
        assert AGENT_DID in str(route.calls[0].request.url)


# -- Namespace wiring --------------------------------------------------------

class TestSocialWiring:
    def test_social_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "social")
        assert isinstance(client.social, FollowsNamespace)
