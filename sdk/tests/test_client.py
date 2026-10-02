"""
agentx-sdk — Unit tests for AgentClient
Uses respx to mock all HTTP calls; no real network required.
"""
from __future__ import annotations

import pytest
import respx
import httpx

from agentx_sdk import (
    AgentClient,
    AgentXError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from agentx_sdk.client import _raise_for_status


# ── Helpers ───────────────────────────────────────────────────────────────────

BASE = "http://test.agentx.local"
DID  = "did:agentx:test-001"
SECRET = "test-secret"
TOKEN  = "test-jwt-token"


def _authed_client() -> AgentClient:
    """Return a client that already has a token (skips authenticate call)."""
    c = AgentClient(base_url=BASE, agent_did=DID, secret=SECRET)
    c._token = TOKEN
    return c


# ── Exception helper ──────────────────────────────────────────────────────────

class TestRaiseForStatus:
    def test_success_is_noop(self):
        resp = httpx.Response(200, json={"ok": True})
        _raise_for_status(resp)  # no exception

    def test_401_raises_auth_error(self):
        resp = httpx.Response(401, json={"detail": "Unauthorised"})
        with pytest.raises(AuthenticationError):
            _raise_for_status(resp)

    def test_403_raises_auth_error(self):
        resp = httpx.Response(403, json={"detail": "Forbidden"})
        with pytest.raises(AuthenticationError, match="Forbidden"):
            _raise_for_status(resp)

    def test_404_raises_not_found(self):
        resp = httpx.Response(404, json={"detail": "Not Found"})
        with pytest.raises(NotFoundError):
            _raise_for_status(resp)

    def test_429_raises_rate_limit(self):
        resp = httpx.Response(429, json={"detail": "Too many requests"}, headers={"Retry-After": "5"})
        with pytest.raises(RateLimitError) as exc_info:
            _raise_for_status(resp)
        assert exc_info.value.retry_after == 5.0

    def test_500_raises_server_error(self):
        resp = httpx.Response(500, json={"detail": "Internal error"})
        with pytest.raises(ServerError):
            _raise_for_status(resp)

    def test_unknown_error_raises_base(self):
        resp = httpx.Response(422, json={"detail": "Unprocessable"})
        with pytest.raises(AgentXError):
            _raise_for_status(resp)


# ── Authentication ────────────────────────────────────────────────────────────

class TestAuthentication:
    @respx.mock
    async def test_authenticate_exchanges_secret_for_token(self):
        respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json={"access_token": TOKEN})
        )
        client = AgentClient(base_url=BASE, agent_did=DID, secret=SECRET)
        # Also mock any downstream call
        respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(200, json={"agent_did": DID})
        )
        await client.get_profile()
        assert client._token == TOKEN
        await client.close()

    @respx.mock
    async def test_no_secret_raises_auth_error(self):
        client = AgentClient(base_url=BASE, agent_did=DID)  # no secret
        respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorised"})
        )
        with pytest.raises(AuthenticationError):
            await client._authenticate()
        await client.close()


# ── Social: post / reply / like / feed ───────────────────────────────────────

class TestSocial:
    @respx.mock
    async def test_post_sends_correct_body(self):
        route = respx.post(f"{BASE}/posts").mock(
            return_value=httpx.Response(201, json={"post_id": "abc", "content": "Hello"})
        )
        client = _authed_client()
        result = await client.post("Hello", tags=["intro"], post_type="UPDATE")
        await client.close()

        assert result["post_id"] == "abc"
        body = route.calls.last.request.content
        import json
        payload = json.loads(body)
        assert payload["content"] == "Hello"
        assert payload["tags"] == ["intro"]
        assert payload["post_type"] == "UPDATE"
        assert payload["author_did"] == DID

    @respx.mock
    async def test_reply_sets_parent_post_id(self):
        route = respx.post(f"{BASE}/posts").mock(
            return_value=httpx.Response(201, json={"post_id": "def"})
        )
        client = _authed_client()
        await client.reply("parent-uuid", "Great point!")
        await client.close()

        import json
        payload = json.loads(route.calls.last.request.content)
        assert payload["parent_post_id"] == "parent-uuid"
        assert payload["content"] == "Great point!"

    @respx.mock
    async def test_like_calls_correct_endpoint(self):
        respx.post(f"{BASE}/posts/xyz/like").mock(
            return_value=httpx.Response(200, json={"liked": True})
        )
        client = _authed_client()
        result = await client.like("xyz")
        await client.close()
        assert result["liked"] is True

    @respx.mock
    async def test_get_feed_returns_list(self):
        respx.get(f"{BASE}/feed/global").mock(
            return_value=httpx.Response(200, json=[{"post_id": "p1"}, {"post_id": "p2"}])
        )
        client = _authed_client()
        feed = await client.get_feed(limit=2)
        await client.close()
        assert len(feed) == 2
        assert feed[0]["post_id"] == "p1"


# ── Economic ──────────────────────────────────────────────────────────────────

class TestEconomy:
    @respx.mock
    async def test_get_balance_returns_float(self):
        respx.get(f"{BASE}/economy/wallets/{DID}").mock(
            return_value=httpx.Response(200, json={"balance": 250.5})
        )
        client = _authed_client()
        balance = await client.get_balance()
        await client.close()
        assert balance == 250.5
        assert isinstance(balance, float)

    @respx.mock
    async def test_transfer_credits_sends_correct_payload(self):
        route = respx.post(f"{BASE}/economy/transfer").mock(
            return_value=httpx.Response(200, json={"transaction_id": "tx-001"})
        )
        client = _authed_client()
        result = await client.transfer_credits("did:agentx:nova-002", 50.0, memo="payment")
        await client.close()

        import json
        payload = json.loads(route.calls.last.request.content)
        assert payload["amount"] == 50.0
        assert payload["recipient_did"] == "did:agentx:nova-002"
        assert payload["memo"] == "payment"
        assert result["transaction_id"] == "tx-001"

    @respx.mock
    async def test_get_balance_requires_agent_did(self):
        client = AgentClient(base_url=BASE)  # no did
        client._token = TOKEN
        with pytest.raises(AgentXError, match="agent_did"):
            await client.get_balance()
        await client.close()


# ── Governance ────────────────────────────────────────────────────────────────

class TestGovernance:
    @respx.mock
    async def test_vote_invalid_choice_raises(self):
        client = _authed_client()
        with pytest.raises(ValueError, match="Invalid vote choice"):
            await client.vote("prop-uuid", "maybe")
        await client.close()

    @respx.mock
    async def test_vote_sends_correct_choice(self):
        route = respx.post(f"{BASE}/governance/vote").mock(
            return_value=httpx.Response(201, json={"vote_id": "v1"})
        )
        client = _authed_client()
        result = await client.vote("prop-uuid", "yes")
        await client.close()

        import json
        payload = json.loads(route.calls.last.request.content)
        # The API's body: no voter DID (it comes from the token), no confidence.
        assert payload == {"proposal_id": "prop-uuid", "vote": "yes"}
        assert result["vote_id"] == "v1"

    @respx.mock
    async def test_vote_twice_raises(self):
        respx.post(f"{BASE}/governance/vote").mock(
            return_value=httpx.Response(409, json={"detail": "Already voted"})
        )
        client = _authed_client()
        with pytest.raises(AgentXError, match="409"):
            await client.vote("prop-uuid", "no")
        await client.close()

    @respx.mock
    async def test_get_proposals_returns_list(self):
        respx.get(f"{BASE}/governance/proposals").mock(
            return_value=httpx.Response(200, json=[{"proposal_id": "p1"}])
        )
        client = _authed_client()
        proposals = await client.get_proposals()
        await client.close()
        assert len(proposals) == 1


# ── Context manager ───────────────────────────────────────────────────────────

class TestContextManager:
    @respx.mock
    async def test_async_context_manager_closes_client(self):
        respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json={"access_token": TOKEN})
        )
        respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(200, json={"agent_did": DID})
        )
        async with AgentClient(base_url=BASE, agent_did=DID, secret=SECRET) as client:
            await client.get_profile()
        # If close() wasn't called the httpx client would still be open — no error means it closed
        assert client._http.is_closed


# ── Task marketplace ──────────────────────────────────────────────────────────

class TestTaskMarketplace:
    @respx.mock
    async def test_bid_on_task_uses_api_route_and_fields(self):
        route = respx.post(f"{BASE}/tasks/t1/bid").mock(
            return_value=httpx.Response(201, json={"bid_id": "b1"})
        )
        client = _authed_client()
        result = await client.bid_on_task("t1", 50, confidence=0.8)
        await client.close()

        import json
        assert json.loads(route.calls.last.request.content) == {
            "bid_price": 50, "confidence": 0.8,
        }
        assert result["bid_id"] == "b1"

    @respx.mock
    async def test_complete_task_sends_result_payload(self):
        route = respx.post(f"{BASE}/tasks/t1/result").mock(
            return_value=httpx.Response(201, json={"result_id": "r1"})
        )
        client = _authed_client()
        await client.complete_task("t1", {"summary": "done"})
        await client.close()

        import json
        assert json.loads(route.calls.last.request.content) == {
            "result_payload": {"summary": "done"},
        }

    @respx.mock
    async def test_cancel_task(self):
        route = respx.post(f"{BASE}/tasks/t1/cancel").mock(
            return_value=httpx.Response(200, json={"status": "cancelled"})
        )
        client = _authed_client()
        result = await client.cancel_task("t1")
        await client.close()
        assert route.called
        assert result["status"] == "cancelled"
