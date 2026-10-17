"""S18-10 sprint-close security review: trying to get a token out of the server.

The MCP library returns `str(exc)` of *any* exception to the host, so every
error path is checked for tokens: server error bodies that echo the bearer
token (JSON and plain text), a server answer of the wrong shape (an
unexpected exception), a redirect (never followed with the token), extra
fields in the /onboard answer, a credentials file with loose permissions, and
a credentials path that is a symlink.
"""
from __future__ import annotations

import json
import os
import stat

import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.config import credentials_path, load_credentials, save_credentials
from agentx_mcp.server import build_server
from tests.test_write_tools import (
    BASE,
    BOUNTY_ARGS,
    BOUNTY_ID,
    DID,
    NEW_REFRESH,
    NEW_TOKEN,
    ONBOARD_ANSWER,
    POST_ID,
    REFRESH,
    TASK_ID,
    TOKEN,
    _call,
    _joined,
    _mode,
    _no_secrets,
    _payload,
    _text,
)


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


@pytest.mark.parametrize("body", [
    {"json": {"detail": f"token {TOKEN} is not valid for {DID}"}},
    {"json": {"detail": {"error": "bad", "echo": {"authorization": f"Bearer {TOKEN}"}}}},
    {"text": f"<html>Bearer {TOKEN} refused</html>"},
    {"text": TOKEN},
])
async def test_error_bodies_that_echo_the_bearer_token_are_redacted(server, body):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/posts").respond(400, **body)
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error
    assert "[redacted]" in _text(result)
    _no_secrets(result)


async def test_error_body_after_a_refresh_redacts_the_new_pair_too(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.post("/posts").mock(side_effect=[
            respx.MockResponse(401, json={"detail": "expired"}),
            respx.MockResponse(400, json={"detail": f"no: {NEW_TOKEN} / {NEW_REFRESH} / {TOKEN}"}),
        ])
        mock.post("/auth/token").respond(json={"access_token": NEW_TOKEN, "refresh_token": NEW_REFRESH})
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error
    # The old access token was already rejected by the server; the live pair never shows.
    text = _text(result)
    assert NEW_TOKEN not in text and NEW_REFRESH not in text


async def test_an_unexpected_server_shape_is_an_error_without_a_token(server):
    """A list where a dict is expected raises inside the tool: the host sees str(exc)."""
    _joined()
    with respx.mock(base_url=BASE) as mock:
        mock.get("/agents").respond(json=[{"agent_did": DID, "token": TOKEN}])
        result = await _call(server, "agentx_whoami", {})
    assert result.is_error
    _no_secrets(result)


async def test_a_redirect_is_an_error_and_is_never_followed_with_the_token(server):
    _joined()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE}/posts").respond(302, headers={"Location": "http://evil.test/posts"})
        evil = mock.post("http://evil.test/posts").respond(json={"post_id": POST_ID})
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert result.is_error and "redirect" in _text(result)
    assert evil.call_count == 0
    _no_secrets(result)


async def test_join_drops_unknown_fields_from_the_onboard_answer(server):
    """Only the allow-listed fields reach the host, whatever else the server adds."""
    answer = {**ONBOARD_ANSWER, "access_token": TOKEN, "credentials": {"refresh": REFRESH},
              "debug": f"issued {TOKEN}"}
    with respx.mock(base_url=BASE) as mock:
        mock.post("/onboard").respond(201, json=answer)
        result = await _call(server, "agentx_join", {"name": "Writer"})
    _no_secrets(result)
    data = _payload(result)
    assert data["agent_did"] == DID
    assert "access_token" not in data and "debug" not in data
    assert data["credentials"].startswith("saved to ")


async def test_a_loose_credentials_file_is_tightened_on_the_next_save(server):
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "accounts": {
        BASE: {"agent_did": DID, "token": TOKEN, "refresh_token": REFRESH}}}))
    os.chmod(path, 0o644)
    with respx.mock(base_url=BASE) as mock:
        mock.post("/posts").mock(side_effect=[
            respx.MockResponse(401, json={"detail": "expired"}),
            respx.MockResponse(201, json={"post_id": POST_ID}),
        ])
        mock.post("/auth/token").respond(json={"access_token": NEW_TOKEN, "refresh_token": NEW_REFRESH})
        result = await _call(server, "agentx_create_post", {"title": "T", "content": "C"})
    assert not result.is_error
    assert _mode(path) == 0o600
    assert load_credentials(BASE).token == NEW_TOKEN


def test_saving_through_a_symlinked_credentials_path_does_not_write_the_target(tmp_path):
    victim = tmp_path / "victim.json"
    victim.write_text('{"accounts": {"http://victim.test": {"token": "VICTIM"}}}')
    os.chmod(victim, 0o644)
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(victim)
    save_credentials(BASE, DID, TOKEN, REFRESH)
    assert not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode)
    assert _mode(path) == 0o600
    assert victim.read_text() == '{"accounts": {"http://victim.test": {"token": "VICTIM"}}}'
    assert load_credentials(BASE).token == TOKEN


async def test_env_token_never_appears_in_any_error_or_result(server, monkeypatch):
    """The env pair (no file) through every error path the tools have."""
    monkeypatch.setenv("AGENTX_TOKEN", TOKEN)
    monkeypatch.setenv("AGENTX_REFRESH_TOKEN", REFRESH)
    monkeypatch.setenv("AGENTX_AGENT_DID", DID)
    with respx.mock(base_url=BASE) as mock:
        mock.route().respond(500, text=f"boom {TOKEN} {REFRESH}")
        async with Client(server) as client:
            for tool, args in {
                "agentx_whoami": {}, "agentx_read_feed": {}, "agentx_notifications": {},
                "agentx_heartbeat": {}, "agentx_claim_faucet": {},
                "agentx_create_bounty": BOUNTY_ARGS,
                "agentx_submit_bounty_solution": {"bounty_id": BOUNTY_ID, "summary": "S"},
                "agentx_reclaim_task": {"task_id": TASK_ID},
                "agentx_create_collective": {"name": "G", "description": "D"},
                "agentx_join_collective": {"collective_id": TASK_ID},
                "agentx_approve_member": {"collective_id": TASK_ID, "agent_did": "did:agentx:gia-001"},
                "agentx_create_post": {"title": "T", "content": "C"},
                "agentx_reply": {"post_id": POST_ID, "content": "C"},
                "agentx_send_message": {"to_agent_did": "did:agentx:gia-001", "message": "m"},
                "agentx_join": {"name": "Writer"},
            }.items():
                result = await client.call_tool(tool, args)
                assert result.is_error, tool
                _no_secrets(result)
