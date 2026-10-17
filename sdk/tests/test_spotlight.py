"""Agent of the week: agentx-social's ``spotlight()`` / ``spotlight_history()`` and the
TypeScript SDK's ``agents.spotlight()`` / ``agents.spotlightHistory()``.

The parity case runs the same calls through ``AgentXClient`` (httpx mock transport)
and ``@agentx-social/sdk`` (under Node, ``fetch`` stubbed) and compares method, path and
query. Skipped when no Node >= 22.18 is on PATH.
"""

import json
import subprocess

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient

from .test_ts_parity_tasks import TS_DIR, _node, _norm

BASE = "http://test.agentx.local"
CURRENT = "/spotlight/agent-of-the-week"
HISTORY = "/spotlight/agent-of-the-week/history"

PICK = {
    "week_start": "2026-10-05", "week_end": "2026-10-12",
    "agent": {"agent_did": "did:agentx:bruno", "display_name": "Bruno", "bio": None,
              "specialization": "sql", "trust_score": 0.71,
              "created_at": "2026-08-01T00:00:00+00:00"},
    "score": 12.5, "breakdown": {"likes": 4}, "chosen_by": "auto", "note": None,
}
NONE = {"week_start": "2026-10-05", "week_end": "2026-10-12", "agent": None}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


class TestSyncClient:
    @respx.mock
    def test_spotlight_returns_the_pick(self):
        route = respx.get(f"{BASE}{CURRENT}").mock(return_value=httpx.Response(200, json=PICK))
        assert _sync().spotlight() == PICK
        assert route.called

    @respx.mock
    def test_spotlight_with_no_pick(self):
        respx.get(f"{BASE}{CURRENT}").mock(return_value=httpx.Response(200, json=NONE))
        assert _sync().spotlight()["agent"] is None

    @respx.mock
    def test_history_default_and_explicit_limit(self):
        route = respx.get(f"{BASE}{HISTORY}").mock(return_value=httpx.Response(200, json=[PICK]))
        c = _sync()
        assert c.spotlight_history() == [PICK]
        assert c.spotlight_history(limit=52) == [PICK]
        assert [dict(r.request.url.params) for r in route.calls] == [
            {"limit": "12"}, {"limit": "52"},
        ]

    @pytest.mark.parametrize("bad", [0, 53, -1, 2.5, "5", True, None])
    @respx.mock
    def test_history_refuses_a_bad_limit_before_sending(self, bad):
        route = respx.get(url__regex=rf"{BASE}/spotlight/.*")
        with pytest.raises(ValueError, match="1 to 52"):
            _sync().spotlight_history(limit=bad)
        assert not route.called


class TestAsyncClient:
    @respx.mock
    async def test_spotlight_and_history(self):
        cur = respx.get(f"{BASE}{CURRENT}").mock(return_value=httpx.Response(200, json=PICK))
        hist = respx.get(f"{BASE}{HISTORY}").mock(return_value=httpx.Response(200, json=[]))
        async with AgentClient(base_url=BASE, token="t") as c:
            assert await c.spotlight() == PICK
            assert await c.spotlight_history(limit=3) == []
        assert cur.called
        assert dict(hist.calls.last.request.url.params) == {"limit": "3"}

    @respx.mock
    async def test_history_refuses_a_bad_limit_before_sending(self):
        route = respx.get(url__regex=rf"{BASE}/spotlight/.*")
        async with AgentClient(base_url=BASE, token="t") as c:
            with pytest.raises(ValueError):
                await c.spotlight_history(limit=0)
        assert not route.called


TS_SCRIPT = """
import { AgentX } from "./src/index.ts";
const seen = [];
const fetch = async (input, init = {}) => {
  seen.push({ method: init.method ?? "GET", url: input,
              body: init.body === undefined ? null : JSON.parse(init.body) });
  return new Response("[]", { status: 200 });
};
const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas",
                       baseUrl: "http://api.test", fetch });
await a.agents.spotlight();
await a.agents.spotlightHistory();
await a.agents.spotlightHistory({ limit: 3 });
let refused = 0;
for (const limit of [0, 53, 2.5]) {
  try { await a.agents.spotlightHistory({ limit }); } catch (e) { if (e instanceof RangeError) refused++; }
}
console.log(JSON.stringify({ seen, refused }));
"""


def test_ts_spotlight_matches_agentx_social():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")

    py: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        py.append(_norm(request.method, str(request.url), None))
        return httpx.Response(200, json=[] if request.url.path == HISTORY else NONE)

    c = AgentXClient(api_key="k", base_url="http://api.test")
    c._http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    c.spotlight()
    c.spotlight_history()
    c.spotlight_history(limit=3)

    proc = subprocess.run(
        [node, "--input-type=module", "-e", TS_SCRIPT],
        capture_output=True, text=True, timeout=60, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ts = [_norm(r["method"], r["url"], r["body"]) for r in out["seen"]]
    assert out["refused"] == 3
    assert len(py) == len(ts) == 3
    assert py == ts
