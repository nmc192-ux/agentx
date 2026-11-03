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


# -- Block / unblock ----------------------------------------------------------

class TestBlock:
    @respx.mock
    def test_block_posts_target_did(self):
        route = respx.post(f"{BASE}/blocks").mock(return_value=httpx.Response(204))
        assert make_client().social.block(TARGET_DID) == {}
        assert json.loads(route.calls.last.request.content) == {"target_did": TARGET_DID}

    @respx.mock
    def test_unblock_sends_delete(self):
        route = respx.delete(f"{BASE}/blocks/{TARGET_DID}").mock(
            return_value=httpx.Response(204)
        )
        assert make_client().social.unblock(TARGET_DID) == {}
        assert route.called

    @pytest.mark.parametrize("bad", ["", "a/b", "..", None])
    def test_bad_did_refused_before_sending(self, bad):
        with respx.mock(assert_all_called=False) as router:
            with pytest.raises(ValueError):
                make_client().social.block(bad)
            with pytest.raises(ValueError):
                make_client().social.unblock(bad)
        assert not router.calls

    @respx.mock
    def test_block_self_is_validation_error(self):
        from agentx_sdk.exceptions import ValidationError
        respx.post(f"{BASE}/blocks").mock(
            return_value=httpx.Response(422, json={"detail": "Cannot block yourself."})
        )
        with pytest.raises(ValidationError):
            make_client().social.block(AGENT_DID)


class TestAsyncBlock:
    @respx.mock
    async def test_block_and_unblock(self):
        from agentx_sdk import AgentClient
        post = respx.post(f"{BASE}/blocks").mock(return_value=httpx.Response(204))
        rem = respx.delete(f"{BASE}/blocks/{TARGET_DID}").mock(return_value=httpx.Response(204))
        async with AgentClient(base_url=BASE, token="t") as agent:
            assert await agent.block(TARGET_DID) == {}
            assert json.loads(post.calls.last.request.content) == {"target_did": TARGET_DID}
            assert post.calls.last.request.headers["Authorization"] == "Bearer t"
            assert await agent.unblock(TARGET_DID) == {}
            assert rem.called
            with pytest.raises(ValueError):
                await agent.block("a/b")
            with pytest.raises(ValueError):
                await agent.unblock("..")


class TestAsyncFollow:
    @respx.mock
    async def test_follow_and_unfollow_use_the_mounted_route(self):
        from agentx_sdk import AgentClient
        post = respx.post(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204))
        rem = respx.delete(f"{BASE}/agents/{TARGET_DID}/follow").mock(
            return_value=httpx.Response(204))
        async with AgentClient(base_url=BASE, token="t") as agent:
            assert await agent.follow(TARGET_DID) == {}
            assert post.calls.last.request.headers["Authorization"] == "Bearer t"
            assert await agent.unfollow(TARGET_DID) == {}
            assert rem.called
            with pytest.raises(ValueError):
                await agent.follow("a/b")
            with pytest.raises(ValueError):
                await agent.unfollow("..")
