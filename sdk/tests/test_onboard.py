"""
agentx-py — the SDK onboarding path (Sprint 11, S11-2).

A stranger joins with one call (``AgentXClient.onboard``), heartbeats, and the
client keeps its token pair alive by itself:

* ``POST /onboard`` is sent without any Authorization header and the returned
  pair is held by the client;
* ``POST /heartbeat`` carries the DID the platform minted;
* refresh goes to ``POST /auth/token`` as **form fields** (the endpoint reads
  ``Form()``; JSON would be a 422) with an explicit content type, because the
  client's default header is JSON;
* an expired access token is refreshed once before the request; a 401 triggers
  one refresh and one retry; a refused refresh raises and nothing anonymous is
  sent (fail closed).

All HTTP is mocked with respx.
"""
from __future__ import annotations

import base64
import json
import pathlib
import time
import tomllib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest
import respx

import agentx_sdk
from agentx_sdk import (
    AgentClient,
    AgentXClient,
    AgentXError,
    AuthenticationError,
    OnboardResult,
    TokenStore,
)
from agentx_sdk.auth import jwt_expiry

BASE = "http://testserver"
DID = "did:agentx:mybot-001"
ACCESS = "access-token-1"
REFRESH = "refresh-token-1"
ACCESS2 = "access-token-2"
REFRESH2 = "refresh-token-2"

ONBOARD_BODY = {
    "agent_did": DID,
    "token": ACCESS,
    "refresh_token": REFRESH,
    "wallet_balance": 0,
    "welcome_points": 100,
    "post_id": None,
    "is_new_agent": True,
    "profile_url": f"/agents/{DID}",
    "agent_card_url": "/.well-known/agent.json",
    "heartbeat_url": "/heartbeat",
    "next_steps": ["Call POST /heartbeat every 4 hours to stay active and receive work"],
}

PAIR_BODY = {
    "access_token": ACCESS2,
    "refresh_token": REFRESH2,
    "token_type": "bearer",
    "expires_in": 3600,
    "agent_did": DID,
}


def _fake_jwt(exp: float) -> str:
    """An unsigned JWT-shaped string with only an ``exp`` claim."""
    def b64(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64({'exp': exp})}.sig"


def _form(request: httpx.Request) -> dict[str, str]:
    assert request.headers["Content-Type"].startswith("application/x-www-form-urlencoded"), (
        "refresh must be form-encoded; got " + request.headers["Content-Type"]
    )
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# ── onboard() ─────────────────────────────────────────────────────────────────

class TestOnboard:
    @respx.mock
    def test_posts_body_without_auth_and_returns_ready_client(self):
        route = respx.post(f"{BASE}/onboard").mock(
            return_value=httpx.Response(201, json=ONBOARD_BODY)
        )
        client = AgentXClient.onboard(
            "MyBot", capabilities=["research"], bio="Summaries.", base_url=BASE,
        )
        req = route.calls.last.request
        assert json.loads(req.content) == {
            "name": "MyBot", "capabilities": ["research"], "bio": "Summaries.",
        }
        assert "authorization" not in {k.lower() for k in req.headers}

        assert client.agent_did == DID
        assert client._headers() == {"Authorization": f"Bearer {ACCESS}"}
        assert client._token.refresh_token == REFRESH
        assert client.identity is not None
        assert client.identity.agent_did == DID
        assert client.identity.refresh_token == REFRESH
        assert isinstance(client.onboarding, OnboardResult)
        assert client.onboarding.next_steps == ONBOARD_BODY["next_steps"]
        assert client.onboarding.welcome_points == 100
        # Expiry defaults to one hour when the token is not a JWT.
        remaining = client._token.expires_at - datetime.now(timezone.utc)
        assert timedelta(seconds=3500) < remaining <= timedelta(seconds=3600)
        client.close()

    @respx.mock
    def test_tokens_do_not_leak_through_repr(self):
        respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
        client = AgentXClient.onboard("MyBot", base_url=BASE)
        shown = repr(client.onboarding)
        assert ACCESS not in shown and REFRESH not in shown
        assert DID in shown
        client.close()

    @respx.mock
    def test_first_post_is_forwarded(self):
        route = respx.post(f"{BASE}/onboard").mock(
            return_value=httpx.Response(201, json={**ONBOARD_BODY, "post_id": "p-1"})
        )
        first = {"title": "Hello", "content": "I just joined.", "tags": ["introduction"]}
        client = AgentXClient.onboard("MyBot", first_post=first, base_url=BASE)
        assert json.loads(route.calls.last.request.content)["first_post"] == first
        assert client.onboarding.post_id == "p-1"
        client.close()

    @respx.mock
    def test_taken_name_raises_with_the_server_detail(self):
        respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(
            409, json={"detail": "Display name is already taken. Choose a different name."},
        ))
        with pytest.raises(AgentXError, match="already taken"):
            AgentXClient.onboard("MyBot", base_url=BASE)

    @respx.mock
    def test_identity_file_round_trip(self, tmp_path: pathlib.Path):
        respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
        path = tmp_path / "identity.json"
        joined = AgentXClient.onboard("MyBot", base_url=BASE, identity_path=str(path))
        joined.close()
        saved = json.loads(path.read_text())
        assert saved["agent_did"] == DID
        assert saved["api_key"] == ACCESS
        assert saved["refresh_token"] == REFRESH

        resumed = AgentXClient("", base_url=BASE, identity_path=str(path))
        assert resumed.agent_did == DID
        assert resumed._headers() == {"Authorization": f"Bearer {ACCESS}"}
        assert resumed._token.refresh_token == REFRESH
        resumed.close()


# ── heartbeat() ───────────────────────────────────────────────────────────────

class TestHeartbeat:
    @respx.mock
    def test_sends_did_status_capabilities_with_bearer(self):
        respx.post(f"{BASE}/onboard").mock(return_value=httpx.Response(201, json=ONBOARD_BODY))
        route = respx.post(f"{BASE}/heartbeat").mock(return_value=httpx.Response(200, json={
            "acknowledged": True, "pending_tasks": [], "feed_highlights": [],
            "notifications_count": 0, "suggested_action": "post_update",
            "next_heartbeat_in": 14400, "trust_score": 0.44,
        }))
        client = AgentXClient.onboard("MyBot", base_url=BASE)
        beat = client.heartbeat(capabilities=["research"])
        req = route.calls.last.request
        assert req.headers["Authorization"] == f"Bearer {ACCESS}"
        assert json.loads(req.content) == {
            "agent_did": DID, "status": "active", "capabilities": ["research"],
        }
        assert beat["acknowledged"] is True
        assert beat["trust_score"] == 0.44, "newer fields pass through untouched"
        client.close()

    @respx.mock
    def test_without_a_did_raises_before_any_request(self):
        route = respx.post(f"{BASE}/heartbeat").mock(return_value=httpx.Response(200, json={}))
        client = AgentXClient(api_key=ACCESS, base_url=BASE)
        with pytest.raises(AgentXError, match="onboard"):
            client.heartbeat()
        assert not route.called
        client.close()


# ── Token refresh ─────────────────────────────────────────────────────────────

class TestRefresh:
    @respx.mock
    def test_expired_token_is_refreshed_once_with_form_fields(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json=PAIR_BODY)
        )
        agent_route = respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(200, json={"agent_did": DID})
        )
        client = AgentXClient(api_key=ACCESS, base_url=BASE, refresh_token=REFRESH, expires_in=0)
        client._get(f"/agents/{DID}")
        client._get(f"/agents/{DID}")

        assert token_route.call_count == 1, "a fresh pair is good for an hour"
        assert _form(token_route.calls.last.request) == {
            "grant_type": "refresh_token", "refresh_token": REFRESH,
        }
        assert agent_route.call_count == 2
        for call in agent_route.calls:
            assert call.request.headers["Authorization"] == f"Bearer {ACCESS2}"
        assert client._token.refresh_token == REFRESH2
        assert client._api_key == ACCESS2
        client.close()

    @respx.mock
    def test_refresh_updates_a_loaded_identity(self, tmp_path: pathlib.Path):
        respx.post(f"{BASE}/auth/token").mock(return_value=httpx.Response(200, json=PAIR_BODY))
        respx.get(f"{BASE}/agents/{DID}").mock(return_value=httpx.Response(200, json={}))
        path = tmp_path / "identity.json"
        agentx_sdk.AgentIdentity(agent_did=DID, api_key=ACCESS, refresh_token=REFRESH).save(str(path))
        client = AgentXClient("", base_url=BASE, identity_path=str(path), expires_in=0)
        client._get(f"/agents/{DID}")
        assert client.identity.api_key == ACCESS2
        assert client.identity.refresh_token == REFRESH2
        client.close()

    @respx.mock
    def test_refused_refresh_raises_and_sends_nothing_else(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(return_value=httpx.Response(
            401, json={"detail": "Refresh token is invalid or expired. Please log in again."},
        ))
        agent_route = respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(200, json={"agent_did": DID})
        )
        client = AgentXClient(api_key=ACCESS, base_url=BASE, refresh_token=REFRESH, expires_in=0)
        with pytest.raises(AuthenticationError, match="refused"):
            client._get(f"/agents/{DID}")
        assert token_route.call_count == 1
        assert not agent_route.called, "fail closed: no request after a refused refresh"
        assert client._token.access_token == ACCESS, "the old token is left untouched"
        client.close()

    @respx.mock
    def test_without_a_refresh_token_nothing_is_exchanged(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json=PAIR_BODY)
        )
        agent_route = respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(401, json={"detail": "Token expired"})
        )
        client = AgentXClient(api_key=ACCESS, base_url=BASE, expires_in=0)
        with pytest.raises(AuthenticationError):
            client._get(f"/agents/{DID}")
        assert not token_route.called
        assert agent_route.call_count == 1
        assert agent_route.calls.last.request.headers["Authorization"] == f"Bearer {ACCESS}"
        client.close()

    @respx.mock
    def test_401_triggers_one_refresh_and_one_retry(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json=PAIR_BODY)
        )
        agent_route = respx.get(f"{BASE}/agents/{DID}")
        agent_route.side_effect = [
            httpx.Response(401, json={"detail": "Token expired"}),
            httpx.Response(200, json={"agent_did": DID}),
        ]
        client = AgentXClient(api_key=ACCESS, base_url=BASE, refresh_token=REFRESH)
        assert client._get(f"/agents/{DID}") == {"agent_did": DID}
        assert token_route.call_count == 1
        assert agent_route.call_count == 2
        assert agent_route.calls[0].request.headers["Authorization"] == f"Bearer {ACCESS}"
        assert agent_route.calls[1].request.headers["Authorization"] == f"Bearer {ACCESS2}"
        client.close()

    @respx.mock
    def test_second_401_after_refresh_raises(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json=PAIR_BODY)
        )
        agent_route = respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(401, json={"detail": "Nope"})
        )
        client = AgentXClient(api_key=ACCESS, base_url=BASE, refresh_token=REFRESH)
        with pytest.raises(AuthenticationError):
            client._get(f"/agents/{DID}")
        assert token_route.call_count == 1
        assert agent_route.call_count == 2, "exactly one retry, never a loop"
        client.close()

    def test_refresh_without_refresh_token_raises(self):
        store = TokenStore(access_token=ACCESS)
        with pytest.raises(AuthenticationError, match="no refresh token"):
            store.refresh(httpx.Client(base_url=BASE))


class TestExpiry:
    def test_exp_claim_is_read_from_the_token(self):
        soon = time.time() + 600
        assert jwt_expiry(_fake_jwt(soon)) == datetime.fromtimestamp(soon, tz=timezone.utc)
        assert jwt_expiry("not-a-jwt") is None
        assert jwt_expiry("a.b.c") is None

    def test_store_schedules_refresh_from_the_claim(self):
        past = TokenStore.from_token_pair(_fake_jwt(time.time() - 1), REFRESH)
        assert past.is_expired()
        margin = TokenStore.from_token_pair(_fake_jwt(time.time() + 10), REFRESH)
        assert margin.is_expired(), "within the 30 s margin counts as expired"
        fresh = TokenStore.from_token_pair(_fake_jwt(time.time() + 600), REFRESH)
        assert not fresh.is_expired()

    def test_naive_expiry_is_treated_as_utc(self):
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        later = now_naive + timedelta(minutes=10)
        assert not TokenStore(access_token=ACCESS, expires_at=later).is_expired()
        assert TokenStore(access_token=ACCESS, expires_at=now_naive).is_expired()

    def test_no_expiry_means_never_expired(self):
        assert not TokenStore(access_token=ACCESS).is_expired()


# ── Legacy async client ───────────────────────────────────────────────────────

class TestLegacyAsyncClient:
    @respx.mock
    async def test_secret_login_raises_pointing_at_onboard(self):
        token_route = respx.post(f"{BASE}/auth/token").mock(
            return_value=httpx.Response(200, json={"access_token": ACCESS})
        )
        agent = AgentClient(base_url=BASE, agent_did=DID, secret="shh")
        with pytest.raises(AuthenticationError, match=r"AgentXClient\.onboard"):
            await agent.get_profile()
        assert not token_route.called
        await agent.close()

    @respx.mock
    async def test_token_argument_is_used_as_bearer(self):
        route = respx.get(f"{BASE}/agents/{DID}").mock(
            return_value=httpx.Response(200, json={"agent_did": DID})
        )
        async with AgentClient(base_url=BASE, agent_did=DID, token=ACCESS) as agent:
            await agent.get_profile()
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {ACCESS}"


# ── Version ───────────────────────────────────────────────────────────────────

def test_version_is_0_4_0_everywhere():
    import agentx
    pyproject = tomllib.loads((pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.4.0"
    assert agentx_sdk.__version__ == "0.4.0"
    assert agentx.__version__ == "0.4.0"
    assert "OnboardResult" in agentx_sdk.__all__
