"""@handles (Layer 1 S2-3): agentx-social's ``get_agent_by_handle()`` / ``set_handle()``
and the TypeScript SDK's ``agents.byHandle()`` / ``agents.setHandle()``.

The parity case runs the same calls through ``AgentXClient`` (httpx mock transport)
and ``@agentx-social/sdk`` (under Node, ``fetch`` stubbed) and compares method, path
and body. Skipped when no Node >= 22.18 is on PATH.
"""

import json
import subprocess

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient
from agentx_sdk.exceptions import AgentXError, AuthenticationError, NotFoundError
from agentx_sdk.models import AgentResponse, OnboardResult

from .test_ts_parity_tasks import TS_DIR, _node, _norm

BASE = "http://test.agentx.local"

PROFILE = {
    "agent_did": "did:agentx:nova-042", "display_name": "Nova", "handle": "nova_042",
    "agent_type": "AUTONOMOUS", "governance_role": "MEMBER", "tier": "BOOTSTRAP",
    "status": "ACTIVE", "trust_score": 0.5, "created_at": "2026-11-01T00:00:00+00:00",
}
CHANGE = {
    "agent_did": "did:agentx:nova-042", "handle": "nova", "previous_handle": "nova_042",
    "changed": True, "changed_at": "2026-11-02T00:00:00+00:00",
    "redirect_expires_at": "2026-12-02T00:00:00+00:00",
    "next_change_at": "2026-12-02T00:00:00+00:00",
}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


class TestModels:
    def test_profile_carries_the_handle(self):
        assert AgentResponse(**PROFILE).handle == "nova_042"

    def test_profile_without_a_handle_still_parses(self):
        # An older server sends no handle.
        old = {k: v for k, v in PROFILE.items() if k != "handle"}
        assert AgentResponse(**old).handle is None

    def test_onboard_result_carries_the_handle(self):
        r = OnboardResult(agent_did="did:agentx:nova-042", handle="nova_042",
                          token="t", refresh_token="r")
        assert r.handle == "nova_042"
        assert OnboardResult(agent_did="d", token="t", refresh_token="r").handle is None


class TestSyncClient:
    @respx.mock
    def test_by_handle_returns_the_profile(self):
        route = respx.get(f"{BASE}/agents/by-handle/nova_042").mock(
            return_value=httpx.Response(200, json=PROFILE))
        agent = _sync().get_agent_by_handle("nova_042")
        assert isinstance(agent, AgentResponse)
        assert agent.agent_did == "did:agentx:nova-042"
        assert agent.handle == "nova_042"
        assert route.called

    @respx.mock
    def test_by_handle_sends_a_leading_at_for_the_server_to_fold(self):
        route = respx.get(url__regex=rf"{BASE}/agents/by-handle/.*").mock(
            return_value=httpx.Response(200, json=PROFILE))
        _sync().get_agent_by_handle("@Nova_042")
        assert route.calls.last.request.url.raw_path == b"/agents/by-handle/%40Nova_042"

    @respx.mock
    def test_by_handle_unknown_is_not_found(self):
        respx.get(f"{BASE}/agents/by-handle/nobody").mock(
            return_value=httpx.Response(404, json={"detail": "No agent with handle: nobody"}))
        with pytest.raises(NotFoundError):
            _sync().get_agent_by_handle("nobody")

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "nova/../me", "a\\b"])
    @respx.mock
    def test_by_handle_cannot_choose_another_route(self, bad):
        route = respx.route(url__startswith=BASE)
        with pytest.raises(ValueError):
            _sync().get_agent_by_handle(bad)
        assert not route.called

    @respx.mock
    def test_set_handle_patches_and_returns_the_change(self):
        route = respx.patch(f"{BASE}/agents/me/handle").mock(
            return_value=httpx.Response(200, json=CHANGE))
        assert _sync().set_handle("nova") == CHANGE
        req = route.calls.last.request
        assert json.loads(req.content) == {"handle": "nova"}
        assert req.headers["authorization"] == "Bearer k"

    @pytest.mark.parametrize("status", [409, 403, 422, 400])
    @respx.mock
    def test_set_handle_refusals_raise_with_the_status(self, status):
        respx.patch(f"{BASE}/agents/me/handle").mock(
            return_value=httpx.Response(status, json={"detail": "refused"}))
        with pytest.raises(AgentXError) as info:
            _sync().set_handle("nova")
        assert info.value.status_code == status

    @respx.mock
    def test_set_handle_signed_out_is_an_authentication_error(self):
        respx.patch(f"{BASE}/agents/me/handle").mock(
            return_value=httpx.Response(401, json={"detail": "no token"}))
        with pytest.raises(AuthenticationError):
            _sync().set_handle("nova")

    @respx.mock
    def test_set_handle_cooldown_is_not_retried(self):
        # 409, not 429: a 30-day wait must never loop in a retrying client.
        route = respx.patch(f"{BASE}/agents/me/handle").mock(
            return_value=httpx.Response(409, json={"detail": "once per 30 days"}))
        c = AgentXClient(api_key="k", base_url=BASE)    # default retries on
        with pytest.raises(AgentXError, match="409"):
            c.set_handle("nova")
        assert route.call_count == 1


class TestAsyncClient:
    @respx.mock
    async def test_by_handle_and_set_handle(self):
        get = respx.get(f"{BASE}/agents/by-handle/nova_042").mock(
            return_value=httpx.Response(200, json=PROFILE))
        patch = respx.patch(f"{BASE}/agents/me/handle").mock(
            return_value=httpx.Response(200, json=CHANGE))
        async with AgentClient(base_url=BASE, token="t") as c:
            assert (await c.get_agent_by_handle("nova_042"))["handle"] == "nova_042"
            assert (await c.set_handle("nova"))["changed"] is True
        assert get.called
        assert json.loads(patch.calls.last.request.content) == {"handle": "nova"}

    @respx.mock
    async def test_by_handle_refuses_a_path(self):
        route = respx.route(url__startswith=BASE)
        async with AgentClient(base_url=BASE, token="t") as c:
            with pytest.raises(ValueError):
                await c.get_agent_by_handle("../me")
        assert not route.called


TS_SCRIPT = """
import { AgentX, ConflictError, NotFoundError } from "./src/index.ts";
const seen = [];
const answers = [
  [200, %(profile)s], [200, %(change)s], [409, { detail: "taken" }], [404, { detail: "no" }],
];
const fetch = async (input, init = {}) => {
  seen.push({ method: init.method ?? "GET", url: input,
              body: init.body === undefined ? null : JSON.parse(init.body) });
  const [status, body] = answers.shift();
  return new Response(JSON.stringify(body), { status,
    headers: { "content-type": "application/json" } });
};
const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:nova-042",
                       baseUrl: "http://api.test", fetch });
const profile = await a.agents.byHandle("nova_042");
const change = await a.agents.setHandle("nova");
let conflict = false, missing = false, refused = 0;
try { await a.agents.setHandle("atlas"); } catch (e) { conflict = e instanceof ConflictError; }
try { await a.agents.byHandle("nobody"); } catch (e) { missing = e instanceof NotFoundError; }
for (const bad of ["", "..", "a/b"]) {
  try { await a.agents.byHandle(bad); } catch (e) { refused++; }
}
console.log(JSON.stringify({ seen, handle: profile.handle, changed: change.changed,
                             conflict, missing, refused }));
"""


def test_ts_handles_match_agentx_social():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")

    py: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        py.append(_norm(request.method, str(request.url), body))
        return httpx.Response(200, json=PROFILE if request.method == "GET" else CHANGE)

    c = AgentXClient(api_key="k", base_url="http://api.test")
    c._http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    c.get_agent_by_handle("nova_042")
    c.set_handle("nova")
    c.set_handle("atlas")
    c.get_agent_by_handle("nobody")

    script = TS_SCRIPT % {"profile": json.dumps(PROFILE), "change": json.dumps(CHANGE)}
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ts = [_norm(r["method"], r["url"], r["body"]) for r in out["seen"]]
    assert out["handle"] == "nova_042"
    assert out["changed"] is True
    assert out["conflict"] and out["missing"]
    assert out["refused"] == 3                  # refused before any request
    assert len(py) == len(ts) == 4
    assert py == ts
