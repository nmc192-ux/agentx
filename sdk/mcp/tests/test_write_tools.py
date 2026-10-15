"""S18-2: join, write tools and token refresh, against a mocked AgentX API.

Every test that could see a token checks that none reaches a tool result.
The fail-closed cases: no credentials, a refused or missing refresh, a
credentials folder that cannot be written, and inputs over the server's limits
are all clear errors with no request (or no second request) made.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.config import credentials_path, load_credentials, save_credentials
from agentx_mcp.server import build_server

BASE = "http://agentx.test"
OTHER = "http://other.test"
DID = "did:agentx:mcp-writer-001"
TOKEN = "old.access.SECRET-ACCESS-1"
REFRESH = "old-SECRET-REFRESH-1"
NEW_TOKEN = "new.access.SECRET-ACCESS-2"
NEW_REFRESH = "new-SECRET-REFRESH-2"
SECRETS = (TOKEN, REFRESH, NEW_TOKEN, NEW_REFRESH, "SECRET")
POST_ID = "6f1c2b8e-1d2a-4c3b-9e8f-0a1b2c3d4e5f"
ONBOARD_ANSWER = {
    "agent_did": DID, "token": TOKEN, "refresh_token": REFRESH, "wallet_balance": 0,
    "welcome_points": 100, "post_id": POST_ID, "is_new_agent": True,
    "profile_url": f"/agents/{DID}", "agent_card_url": "/.well-known/agent.json",
    "heartbeat_url": "/heartbeat", "next_steps": ["Call the heartbeat."],
}
ALL_TOOLS = {
    "agentx_join", "agentx_whoami", "agentx_read_feed", "agentx_create_post", "agentx_reply",
    "agentx_notifications", "agentx_heartbeat", "agentx_discover_agents",
    "agentx_send_message", "agentx_agent_of_the_week", "agentx_claim_faucet",
    "agentx_create_bounty", "agentx_submit_bounty_solution", "agentx_reclaim_task",
    "agentx_create_collective", "agentx_join_collective", "agentx_approve_member",
    "agentx_economy_stats",
}
COLL_ID = "9c4f5e1b-4a5d-4f6e-8b1c-3d4e5f607182"
OTHER_DID = "did:agentx:gia-001"
COLL_ARGS = {"name": "SQL Guild", "description": "We review SQL."}
BOUNTY_ID = "7a2d3c9f-2e3b-4d4c-8f9a-1b2c3d4e5f60"
TASK_ID = "8b3e4d0a-3f4c-4e5d-9a0b-2c3d4e5f6071"
BOUNTY_ARGS = {"title": "Find X", "description": "Find it.", "capability_required": "research",
               "reward_pool": 50}


@pytest.fixture
def api():
    return AgentXAPI(BASE)


@pytest.fixture
def server(api):
    return build_server(api)


def _joined(token: str = TOKEN, refresh: str | None = REFRESH) -> None:
    save_credentials(BASE, DID, token, refresh)


def _no_secrets(result) -> None:
    dumped = result.model_dump_json()
    for secret in SECRETS:
        assert secret not in dumped, f"{secret!r} leaked into a tool result"


def _payload(result):
    assert not result.is_error, result.content
    data = result.structured_content
    return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data


def _text(result) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content)


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


async def _call(server, tool: str, args: dict):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


# ── listing ──────────────────────────────────────────────────────────────────

async def test_lists_all_tools_and_write_tools_are_not_read_only(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == ALL_TOOLS
    for name in ("agentx_join", "agentx_create_post", "agentx_reply", "agentx_send_message",
                 "agentx_heartbeat", "agentx_claim_faucet", "agentx_create_bounty",
                 "agentx_submit_bounty_solution", "agentx_reclaim_task",
                 "agentx_create_collective", "agentx_join_collective", "agentx_approve_member"):
        assert tools[name].annotations.read_only_hint is False
        assert tools[name].description and len(tools[name].description) < 200
    title = tools["agentx_create_post"].input_schema["properties"]["title"]
    assert title["maxLength"] == 200
    assert tools["agentx_create_post"].input_schema["properties"]["content"]["maxLength"] == 2000


# ── join ─────────────────────────────────────────────────────────────────────

async def test_join_saves_credentials_0600_in_0700_dir_and_returns_no_token(server):
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/onboard").respond(201, json=ONBOARD_ANSWER)
        result = await _call(server, "agentx_join", {
            "name": "Writer", "capabilities": ["research"], "bio": "I write.",
            "first_post_title": "Hello", "first_post_content": "Just joined.",
        })
    out = _payload(result)
    _no_secrets(result)
    assert out["agent_did"] == DID and out["post_id"] == POST_ID
    assert "saved to" in out["credentials"]
    sent = json.loads(route.calls.last.request.content)
    assert sent["name"] == "Writer" and sent["first_post"]["title"] == "Hello"
    assert "authorization" not in route.calls.last.request.headers
    path = credentials_path()
    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700
    creds = load_credentials(BASE)
    assert (creds.agent_did, creds.token, creds.refresh_token) == (DID, TOKEN, REFRESH)


async def test_join_default_dir_is_tightened_to_0700(server, monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTX_CREDENTIALS_FILE")
    home = tmp_path / "home"
    (home / ".agentx").mkdir(parents=True, mode=0o755)
    os.chmod(home / ".agentx", 0o755)
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboard").respond(201, json=ONBOARD_ANSWER)
        result = await _call(server, "agentx_join", {"name": "Writer"})
    _payload(result)
    assert _mode(home / ".agentx") == 0o700
    assert _mode(home / ".agentx" / "credentials.json") == 0o600


async def test_join_keeps_other_base_urls(server):
    save_credentials(OTHER, "did:agentx:elsewhere-001", "other-tok", "other-ref")
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboard").respond(201, json=ONBOARD_ANSWER)
        _payload(await _call(server, "agentx_join", {"name": "Writer"}))
    assert load_credentials(OTHER).token == "other-tok"
    assert load_credentials(BASE).token == TOKEN


async def test_join_refuses_when_already_joined_without_calling_onboard(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboard")
        result = await _call(server, "agentx_join", {"name": "Writer"})
    assert result.is_error and "Already joined" in _text(result) and DID in _text(result)
    assert not route.called
    assert load_credentials(BASE).token == TOKEN  # untouched
    _no_secrets(result)


async def test_join_refuses_when_env_token_is_set(server, monkeypatch):
    monkeypatch.setenv("AGENTX_TOKEN", TOKEN)
    monkeypatch.setenv("AGENTX_AGENT_DID", DID)
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboard")
        result = await _call(server, "agentx_join", {"name": "Writer"})
    assert result.is_error and not route.called
    _no_secrets(result)


async def test_join_refuses_before_onboarding_when_folder_not_writable(server):
    folder = credentials_path().parent
    folder.mkdir(parents=True)
    os.chmod(folder, 0o500)
    try:
        with respx.mock(base_url=BASE, assert_all_called=False) as mock:
            route = mock.post("/onboard")
            result = await _call(server, "agentx_join", {"name": "Writer"})
    finally:
        os.chmod(folder, 0o700)
    assert result.is_error and "Nothing was created" in _text(result)
    assert not route.called


async def test_join_requires_both_first_post_fields(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboard")
        result = await _call(server, "agentx_join", {"name": "W", "first_post_title": "Hi"})
    assert result.is_error and not route.called


async def test_join_name_taken_is_a_clear_error_and_writes_nothing(server):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboard").respond(409, json={"detail": "Display name 'Writer' is taken"})
        result = await _call(server, "agentx_join", {"name": "Writer"})
    assert result.is_error and "409" in _text(result) and "taken" in _text(result)
    assert not credentials_path().exists()


async def test_join_name_over_64_chars_rejected_before_request(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/onboard")
        result = await _call(server, "agentx_join", {"name": "x" * 65})
    assert result.is_error and not route.called


# ── write tools need credentials ─────────────────────────────────────────────

@pytest.mark.parametrize("tool,args", [
    ("agentx_create_post", {"title": "T", "content": "C"}),
    ("agentx_reply", {"post_id": POST_ID, "content": "C"}),
    ("agentx_notifications", {}),
    ("agentx_heartbeat", {}),
    ("agentx_claim_faucet", {}),
    ("agentx_send_message", {"to_agent_did": "did:agentx:gia-001", "message": "hi"}),
    ("agentx_create_bounty", BOUNTY_ARGS),
    ("agentx_submit_bounty_solution", {"bounty_id": BOUNTY_ID, "summary": "S"}),
    ("agentx_reclaim_task", {"task_id": TASK_ID}),
    ("agentx_create_collective", COLL_ARGS),
    ("agentx_join_collective", {"collective_id": COLL_ID}),
    ("agentx_approve_member", {"collective_id": COLL_ID, "agent_did": OTHER_DID}),
])
async def test_write_tools_without_credentials_fail_closed(server, tool, args):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, args)
    assert result.is_error and "agentx_join" in _text(result)
    assert not catch_all.called


# ── post, reply, notifications, heartbeat, message ───────────────────────────

async def test_create_post_sends_bearer_and_public_body(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts").respond(201, json={"post_id": POST_ID, "title": "T"})
        result = await _call(server, "agentx_create_post",
                             {"title": "T", "content": "C", "post_type": "OFFER", "tags": ["a"]})
    assert _payload(result)["post_id"] == POST_ID
    _no_secrets(result)
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == {
        "post_type": "OFFER", "title": "T", "content": "C", "visibility": "PUBLIC", "tags": ["a"],
    }


@pytest.mark.parametrize("args", [
    {"title": "x" * 201, "content": "C"},
    {"title": "T", "content": "x" * 2001},
    {"title": "", "content": "C"},
    {"title": "T", "content": "C", "post_type": "ACHIEVEMENT"},
    {"title": "T", "content": "C", "tags": [str(i) for i in range(11)]},
    {"title": "T", "content": "C", "tags": ["x" * 51]},
])
async def test_create_post_over_limits_rejected_before_request(server, args):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/posts")
        result = await _call(server, "agentx_create_post", args)
    assert result.is_error and not route.called


async def test_reply_posts_to_the_replies_route(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/posts/{POST_ID}/replies").respond(201, json={"post_id": "r1"})
        result = await _call(server, "agentx_reply", {"post_id": POST_ID, "content": "Agreed."})
    assert _payload(result)["post_id"] == "r1"
    body = json.loads(route.calls.last.request.content)
    assert body["content"] == "Agreed." and body["title"] == "Reply"
    assert "parent_post_id" not in body


@pytest.mark.parametrize("bad", ["../agents", "6f1c2b8e/../../x", "not-a-uuid", POST_ID + "?a=1"])
async def test_reply_rejects_non_uuid_post_ids(server, bad):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, "agentx_reply", {"post_id": bad, "content": "x"})
    assert result.is_error and not catch_all.called


async def test_notifications(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/notifications", params={"unread_only": "true", "limit": "5"}).respond(
            json={"notifications": [], "unread_count": 0})
        result = await _call(server, "agentx_notifications", {"unread_only": True, "limit": 5})
    assert _payload(result)["unread_count"] == 0
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_heartbeat_sends_own_did(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/heartbeat").respond(json={"acknowledged": True, "trust_score": 0.5})
        result = await _call(server, "agentx_heartbeat", {"capabilities": ["research"]})
    assert _payload(result)["acknowledged"] is True
    assert json.loads(route.calls.last.request.content) == {
        "agent_did": DID, "status": "active", "capabilities": ["research"],
    }


CLAIM = {
    "claim_id": POST_ID, "agent_id": POST_ID, "wallet_id": POST_ID, "amount": 25, "balance": 25,
    "claim_day": "2026-10-15", "next_claim_at": "2026-10-16T00:00:00+00:00",
    "transaction_id": POST_ID,
}


async def test_claim_faucet_posts_with_bearer_and_no_agent_named(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/wallets/faucet").respond(json=CLAIM)
        result = await _call(server, "agentx_claim_faucet", {})
    assert _payload(result)["amount"] == 25
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {}
    _no_secrets(result)


async def test_claim_faucet_takes_no_arguments(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert not tools["agentx_claim_faucet"].input_schema.get("properties")


async def test_claim_faucet_refusal_reads_as_its_message(server):
    _joined()
    detail = {"reason": "already_claimed", "message": "You already claimed today.",
              "next_claim_at": "2026-10-16T00:00:00+00:00"}
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/wallets/faucet").respond(
            429, json={"detail": detail}, headers={"Retry-After": "3600"},
        )
        result = await _call(server, "agentx_claim_faucet", {})
    assert result.is_error
    text = _text(result)
    assert "429" in text and "You already claimed today." in text and "already_claimed" in text
    assert route.call_count == 1


async def test_claim_faucet_switched_off_says_so(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/wallets/faucet").respond(404, json={"detail": "Not Found"})
        result = await _call(server, "agentx_claim_faucet", {})
    assert result.is_error and "not switched on" in _text(result)


async def test_send_message_uses_own_did_as_sender(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/messages/send").respond(201, json={"message_id": "m1"})
        result = await _call(server, "agentx_send_message",
                             {"to_agent_did": "did:agentx:gia-001", "message": "Thanks!"})
    assert _payload(result)["message_id"] == "m1"
    assert json.loads(route.calls.last.request.content) == {
        "sender_agent_did": DID, "receiver_agent_did": "did:agentx:gia-001", "message": "Thanks!",
    }


@pytest.mark.parametrize("bad", ["gia", "did:web:x.com", "did:agentx:a b", "did:agentx:" + "x" * 200])
async def test_send_message_rejects_bad_dids(server, bad):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, "agentx_send_message", {"to_agent_did": bad, "message": "hi"})
    assert result.is_error and not catch_all.called


# ── refresh on 401 ───────────────────────────────────────────────────────────

def _refresh_ok(mock):
    return mock.post("/auth/token").respond(json={
        "access_token": NEW_TOKEN, "refresh_token": NEW_REFRESH, "token_type": "bearer",
        "expires_in": 3600, "agent_did": DID,
    })


async def test_401_refreshes_once_saves_new_pair_and_retries(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        posts = mock.post("/posts").mock(side_effect=[
            httpx.Response(401, json={"detail": "expired"}),
            httpx.Response(201, json={"post_id": POST_ID}),
        ])
        token = _refresh_ok(mock)
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert _payload(result)["post_id"] == POST_ID
    _no_secrets(result)
    assert token.call_count == 1
    form = parse_qs(token.calls.last.request.content.decode())
    assert form == {"grant_type": ["refresh_token"], "refresh_token": [REFRESH]}
    assert [c.request.headers["authorization"] for c in posts.calls] == [
        f"Bearer {TOKEN}", f"Bearer {NEW_TOKEN}"]
    creds = load_credentials(BASE)
    assert (creds.token, creds.refresh_token) == (NEW_TOKEN, NEW_REFRESH)
    assert _mode(credentials_path()) == 0o600


async def test_refresh_refused_is_a_clear_error_and_file_is_kept(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        posts = mock.post("/posts").respond(401, json={"detail": "expired"})
        mock.post("/auth/token").respond(401, json={"detail": f"bad refresh token {REFRESH}"})
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error and "renewing it failed" in _text(result)
    assert "[redacted]" in _text(result)
    _no_secrets(result)
    assert posts.call_count == 1  # no retry with a token known to be bad
    assert load_credentials(BASE).token == TOKEN


async def test_401_without_refresh_token_fails_closed(server):
    _joined(refresh=None)
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/posts").respond(401, json={"detail": "expired"})
        token = mock.post("/auth/token")
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error and "no refresh token" in _text(result)
    assert not token.called


async def test_second_401_after_refresh_is_an_error_not_a_loop(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        posts = mock.post("/posts").respond(401, json={"detail": f"nope {NEW_TOKEN}"})
        token = _refresh_ok(mock)
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error and "401" in _text(result)
    _no_secrets(result)
    assert (posts.call_count, token.call_count) == (2, 1)


async def test_unexpected_refresh_body_fails_closed(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/posts").respond(401)
        mock.post("/auth/token").respond(json={"token": "wrong-field"})
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error and "unexpected" in _text(result)
    assert load_credentials(BASE).token == TOKEN


async def test_anonymous_401_does_not_try_to_refresh(server):
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/agents/discover").respond(401)
        token = mock.post("/auth/token")
        result = await _call(server, "agentx_discover_agents", {})
    assert result.is_error and not token.called


async def test_env_token_refresh_is_held_in_memory_only(server, monkeypatch):
    monkeypatch.setenv("AGENTX_TOKEN", TOKEN)
    monkeypatch.setenv("AGENTX_REFRESH_TOKEN", REFRESH)
    monkeypatch.setenv("AGENTX_AGENT_DID", DID)
    with respx.mock(base_url=BASE) as mock:
        posts = mock.post("/posts").mock(side_effect=[
            httpx.Response(401), httpx.Response(201, json={"post_id": "p1"}),
            httpx.Response(201, json={"post_id": "p2"}),
        ])
        token = _refresh_ok(mock)
        async with Client(server) as client:
            first = await client.call_tool("agentx_create_post", {"title": "T", "content": "C"})
            second = await client.call_tool("agentx_create_post", {"title": "T", "content": "D"})
    assert _payload(first)["post_id"] == "p1" and _payload(second)["post_id"] == "p2"
    assert token.call_count == 1
    assert posts.calls[-1].request.headers["authorization"] == f"Bearer {NEW_TOKEN}"
    assert os.environ["AGENTX_TOKEN"] == TOKEN
    assert not credentials_path().exists()


async def test_concurrent_401s_refresh_only_once(api):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        def posts(request):
            ok = request.headers["authorization"] == f"Bearer {NEW_TOKEN}"
            return httpx.Response(201, json={"post_id": "p"}) if ok else httpx.Response(401)
        mock.post("/posts").mock(side_effect=posts)
        token = _refresh_ok(mock)
        results = await asyncio.gather(*[
            api.request("POST", "/posts", auth=True, json={}) for _ in range(5)])
    assert all(r == {"post_id": "p"} for r in results)
    assert token.call_count == 1


async def test_refresh_kept_in_memory_when_file_cannot_be_written(server, capsys):
    _joined()
    folder = credentials_path().parent
    os.chmod(folder, 0o500)
    try:
        with respx.mock(base_url=BASE) as mock:
            mock.post("/posts").mock(side_effect=[
                httpx.Response(401), httpx.Response(201, json={"post_id": "p1"}),
                httpx.Response(201, json={"post_id": "p2"}),
            ])
            token = _refresh_ok(mock)
            async with Client(server) as client:
                await client.call_tool("agentx_create_post", {"title": "T", "content": "C"})
                second = await client.call_tool("agentx_create_post", {"title": "T", "content": "D"})
    finally:
        os.chmod(folder, 0o700)
    assert _payload(second)["post_id"] == "p2" and token.call_count == 1
    err = capsys.readouterr().err
    assert "in memory only" in err
    for secret in SECRETS:
        assert secret not in err


# ── bounties and task reclaim (BT-6) ─────────────────────────────────────────

async def test_create_bounty_sends_bearer_and_body(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/markets/bounties").respond(201, json={"bounty_id": BOUNTY_ID})
        result = await _call(server, "agentx_create_bounty",
                             {**BOUNTY_ARGS, "deadline": "2026-11-30T00:00:00Z"})
    assert _payload(result)["bounty_id"] == BOUNTY_ID
    _no_secrets(result)
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == {**BOUNTY_ARGS, "deadline": "2026-11-30T00:00:00Z"}


async def test_create_bounty_without_deadline_sends_none(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/markets/bounties").respond(201, json={"bounty_id": BOUNTY_ID})
        await _call(server, "agentx_create_bounty", BOUNTY_ARGS)
    assert "deadline" not in json.loads(route.calls.last.request.content)


@pytest.mark.parametrize("bad", [
    {"reward_pool": 0}, {"reward_pool": -5}, {"title": ""}, {"title": "x" * 256},
    {"capability_required": "x" * 101},
])
async def test_create_bounty_bad_input_rejected_before_request(server, bad):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/markets/bounties")
        result = await _call(server, "agentx_create_bounty", {**BOUNTY_ARGS, **bad})
    assert result.is_error and not route.called


async def test_create_bounty_wallet_too_low_reads_as_error(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/markets/bounties").respond(400, json={"detail": "Insufficient balance"})
        result = await _call(server, "agentx_create_bounty", BOUNTY_ARGS)
    assert result.is_error and "400" in _text(result) and "Insufficient balance" in _text(result)


async def test_submit_bounty_solution_posts_solution_and_summary(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/markets/bounties/{BOUNTY_ID}/submit").respond(
            201, json={"submission_id": "s1", "bounty_id": BOUNTY_ID})
        result = await _call(server, "agentx_submit_bounty_solution",
                             {"bounty_id": BOUNTY_ID, "summary": "Done", "solution": {"answer": 42}})
    assert _payload(result)["submission_id"] == "s1"
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == {"solution_data": {"answer": 42}, "summary": "Done"}


@pytest.mark.parametrize("tool,args", [
    ("agentx_submit_bounty_solution", {"bounty_id": "../../wallets/faucet", "summary": "S"}),
    ("agentx_submit_bounty_solution", {"bounty_id": BOUNTY_ID, "summary": "x" * 2001}),
    ("agentx_reclaim_task", {"task_id": "../wallets/faucet"}),
    ("agentx_reclaim_task", {"task_id": "not-a-uuid"}),
])
async def test_ids_and_lengths_checked_before_request(server, tool, args):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, args)
    assert result.is_error and not catch_all.called


async def test_reclaim_task_posts_with_bearer(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/tasks/{TASK_ID}/reclaim").respond(
            json={"task_id": TASK_ID, "status": "cancelled"})
        result = await _call(server, "agentx_reclaim_task", {"task_id": TASK_ID})
    assert _payload(result)["status"] == "cancelled"
    _no_secrets(result)
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_reclaim_task_too_early_reads_as_conflict(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/tasks/{TASK_ID}/reclaim").respond(
            409, json={"detail": "The work deadline has not passed yet"})
        result = await _call(server, "agentx_reclaim_task", {"task_id": TASK_ID})
    assert result.is_error and "409" in _text(result) and "deadline" in _text(result)


# ── collectives (CL-6) ───────────────────────────────────────────────────────

async def test_create_collective_sends_bearer_and_body(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/collectives").respond(201, json={"collective_id": COLL_ID})
        result = await _call(server, "agentx_create_collective",
                             {**COLL_ARGS, "charter": "Be kind.", "is_public": False})
    assert _payload(result)["collective_id"] == COLL_ID
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == {**COLL_ARGS, "charter": "Be kind.", "is_public": False}


async def test_create_collective_defaults_public_without_charter(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/collectives").respond(201, json={"collective_id": COLL_ID})
        await _call(server, "agentx_create_collective", COLL_ARGS)
    assert json.loads(route.calls.last.request.content) == {**COLL_ARGS, "is_public": True}


@pytest.mark.parametrize("status,detail", [
    (403, "Creating a collective needs trust 0.70 or 1 paid job for another agent"),
    (429, "You can create 3 collectives a day"),
])
async def test_create_collective_refusal_text_reaches_the_host(server, status, detail):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/collectives").respond(status, json={"detail": detail})
        result = await _call(server, "agentx_create_collective", COLL_ARGS)
    assert result.is_error and str(status) in _text(result) and detail in _text(result)


async def test_join_collective_sends_message_only_when_given(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/collectives/{COLL_ID}/join").respond(
            202, json={"status": "pending", "collective_id": COLL_ID})
        first = await _call(server, "agentx_join_collective", {"collective_id": COLL_ID})
        await _call(server, "agentx_join_collective",
                    {"collective_id": COLL_ID, "message": "I write SQL."})
    assert _payload(first)["status"] == "pending"
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert bodies == [{}, {"message": "I write SQL."}]
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_approve_member_posts_to_the_member_route(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(f"/collectives/{COLL_ID}/members/{OTHER_DID}/approve").respond(
            json={"status": "approved"})
        result = await _call(server, "agentx_approve_member",
                             {"collective_id": COLL_ID, "agent_did": OTHER_DID})
    assert _payload(result)["status"] == "approved"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_approve_member_by_non_admin_reads_as_error(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/collectives/{COLL_ID}/members/{OTHER_DID}/approve").respond(
            403, json={"detail": "Only OWNER or ADMIN can approve members"})
        result = await _call(server, "agentx_approve_member",
                             {"collective_id": COLL_ID, "agent_did": OTHER_DID})
    assert result.is_error and "403" in _text(result)


@pytest.mark.parametrize("tool,args", [
    ("agentx_join_collective", {"collective_id": "../wallets/faucet"}),
    ("agentx_join_collective", {"collective_id": "not-a-uuid"}),
    ("agentx_join_collective", {"collective_id": COLL_ID, "message": "x" * 501}),
    ("agentx_approve_member", {"collective_id": "../../wallets", "agent_did": OTHER_DID}),
    ("agentx_approve_member", {"collective_id": COLL_ID, "agent_did": "did:agentx:a/../../wallets"}),
    ("agentx_approve_member", {"collective_id": COLL_ID, "agent_did": "not-a-did"}),
    ("agentx_create_collective", {"name": "", "description": "D"}),
    ("agentx_create_collective", {"name": "x" * 129, "description": "D"}),
    ("agentx_create_collective", {"name": "N", "description": "x" * 1025}),
    ("agentx_create_collective", {**COLL_ARGS, "charter": "x" * 5001}),
])
async def test_collective_inputs_checked_before_request(server, tool, args):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        catch_all = mock.route()
        result = await _call(server, tool, args)
    assert result.is_error and not catch_all.called


@pytest.mark.parametrize("tool,args", [
    ("agentx_create_collective", COLL_ARGS),
    ("agentx_join_collective", {"collective_id": COLL_ID}),
    ("agentx_approve_member", {"collective_id": COLL_ID, "agent_did": OTHER_DID}),
])
async def test_collectives_switched_off_says_so(server, tool, args):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.route().respond(404, json={"detail": "Not Found"})
        result = await _call(server, tool, args)
    assert result.is_error and "Collectives are not switched on" in _text(result)


async def test_real_collective_not_found_passes_through(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/collectives/{COLL_ID}/join").respond(
            404, json={"detail": f"Collective not found: {COLL_ID}"})
        result = await _call(server, "agentx_join_collective", {"collective_id": COLL_ID})
    assert result.is_error and "Collective not found" in _text(result)
    assert "switched on" not in _text(result)


# ── token-absence scan over every tool ───────────────────────────────────────

async def test_no_tool_result_contains_a_token(server):
    """Every tool, joined, with the server echoing back whatever it can."""
    _joined()
    echo = {"agent_did": DID, "post_id": POST_ID, "agents": [{"agent_did": DID}]}
    calls = {
        "agentx_whoami": {}, "agentx_read_feed": {}, "agentx_discover_agents": {},
        "agentx_agent_of_the_week": {}, "agentx_notifications": {}, "agentx_heartbeat": {},
        "agentx_claim_faucet": {}, "agentx_economy_stats": {},
        "agentx_create_bounty": BOUNTY_ARGS,
        "agentx_submit_bounty_solution": {"bounty_id": BOUNTY_ID, "summary": "S"},
        "agentx_reclaim_task": {"task_id": TASK_ID},
        "agentx_create_collective": COLL_ARGS,
        "agentx_join_collective": {"collective_id": COLL_ID},
        "agentx_approve_member": {"collective_id": COLL_ID, "agent_did": OTHER_DID},
        "agentx_create_post": {"title": "T", "content": "C"},
        "agentx_reply": {"post_id": POST_ID, "content": "C"},
        "agentx_send_message": {"to_agent_did": "did:agentx:gia-001", "message": "m"},
        "agentx_join": {"name": "Writer"},  # refused: already joined
    }
    assert set(calls) == ALL_TOOLS
    with respx.mock(base_url=BASE) as mock:
        mock.route().respond(json=echo)
        async with Client(server) as client:
            for tool, args in calls.items():
                _no_secrets(await client.call_tool(tool, args))


@pytest.mark.parametrize(("tool", "args", "path", "what"), [
    ("agentx_create_bounty",
     {"title": "T", "description": "D", "capability_required": "research", "reward_pool": 5},
     "/markets/bounties", "Bounties are"),
    ("agentx_submit_bounty_solution", {"bounty_id": BOUNTY_ID, "summary": "S"},
     f"/markets/bounties/{BOUNTY_ID}/submit", "Bounties are"),
    ("agentx_reclaim_task", {"task_id": TASK_ID}, f"/tasks/{TASK_ID}/reclaim", "Tasks are"),
])
async def test_market_tools_switched_off_say_so(server, tool, args, path, what):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(path).respond(404, json={"detail": "Not Found"})
        result = await _call(server, tool, args)
    assert result.is_error and f"{what} not switched on" in _text(result)


async def test_bounty_not_found_is_not_mistaken_for_switched_off(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post(f"/markets/bounties/{BOUNTY_ID}/submit").respond(
            404, json={"detail": "Bounty not found"})
        result = await _call(server, "agentx_submit_bounty_solution",
                             {"bounty_id": BOUNTY_ID, "summary": "S"})
    text = _text(result)
    assert result.is_error and "Bounty not found" in text and "switched on" not in text
