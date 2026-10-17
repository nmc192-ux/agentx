"""Economy counters: agentx-social's ``client.stats.economy()`` / ``economy_stats()`` and
the TypeScript SDK's ``agent.stats.economy()`` / ``economyStats()``.

The parity case runs the same calls through ``AgentXClient`` / ``economy_stats``
(respx) and ``@agentx-social/sdk`` (under Node, ``fetch`` stubbed) and compares method,
path and query, and that the TS reads send no bearer. Skipped without Node >= 22.18.
"""

import json
import subprocess

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, StatsNamespace, economy_stats
from agentx_sdk.exceptions import NotFoundError, RateLimitError, ServerError

from .test_ts_parity_tasks import TS_DIR, _node, _norm

BASE = "http://test.agentx.local"
PATH = "/stats/economy"
STATS = {
    "bounties_posted": {"count": 3, "target": 10},
    "bounties_paid": {"count": 1, "target": 5},
    "collectives_by_outsiders": {"count": 0, "target": 3},
    "outside_agents_joined": {"count": 40, "target": 100},
    "outside_agents_posting": {"count": 12, "target": 100},
    "outside_agents_trusted": {"count": 1, "target": 1},
    "as_of": "2026-10-15T03:00:00+00:00",
}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


class TestClientNamespace:
    def test_namespace_type(self):
        assert isinstance(_sync().stats, StatsNamespace)

    @respx.mock
    def test_economy_returns_the_counters(self):
        route = respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, json=STATS))
        assert _sync().stats.economy() == STATS
        assert route.call_count == 1
        assert dict(route.calls.last.request.url.params) == {}

    @respx.mock
    def test_switched_off_is_a_clear_not_found(self):
        respx.get(f"{BASE}{PATH}").mock(
            return_value=httpx.Response(404, json={"detail": "Not Found"}))
        with pytest.raises(NotFoundError, match="Economy stats are not switched on"):
            _sync().stats.economy()

    @respx.mock
    def test_other_errors_pass_through(self):
        respx.get(f"{BASE}{PATH}").mock(
            return_value=httpx.Response(503, json={"detail": "Founder roster is misconfigured"}))
        with pytest.raises(ServerError, match="misconfigured"):
            _sync().stats.economy()


class TestNoClient:
    @respx.mock
    def test_economy_stats_needs_no_token(self):
        route = respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, json=STATS))
        assert economy_stats(base_url=BASE + "/") == STATS
        assert "authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_economy_stats_switched_off(self):
        respx.get(f"{BASE}{PATH}").mock(
            return_value=httpx.Response(404, json={"detail": "Not Found"}))
        with pytest.raises(NotFoundError, match="Economy stats are not switched on"):
            economy_stats(base_url=BASE)

    @respx.mock
    def test_economy_stats_rate_limited(self):
        respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(
            429, json={"detail": "Rate limit exceeded"}, headers={"Retry-After": "7"}))
        with pytest.raises(RateLimitError) as err:
            economy_stats(base_url=BASE)
        assert err.value.retry_after == 7.0


TS_SCRIPT = """
import { AgentX, economyStats, NotFoundError } from "./src/index.ts";
const STATS = %s;
const seen = [];
let status = 200;
const fetch = async (input, init = {}) => {
  const auth = new Headers(init.headers ?? {}).get("authorization");
  seen.push({ method: init.method ?? "GET", url: input, auth,
              body: init.body === undefined ? null : JSON.parse(init.body) });
  return new Response(JSON.stringify(status === 200 ? STATS : { detail: "Not Found" }),
                      { status });
};
const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas",
                       baseUrl: "http://api.test", fetch });
const one = await a.stats.economy();
const two = await economyStats({ baseUrl: "http://api.test", fetch });
status = 404;
let off = "";
try { await a.stats.economy(); } catch (e) { if (e instanceof NotFoundError) off = e.message; }
console.log(JSON.stringify({ seen, same: JSON.stringify(one) === JSON.stringify(STATS)
                             && JSON.stringify(two) === JSON.stringify(STATS), off }));
"""


def test_ts_economy_stats_match_agentx_social():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")

    py: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        py.append(_norm(request.method, str(request.url), None))
        return httpx.Response(200, json=STATS)

    c = AgentXClient(api_key="k", base_url="http://api.test")
    c._http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    c.stats.economy()
    with respx.mock:
        respx.get("http://api.test/stats/economy").mock(side_effect=handler)
        economy_stats(base_url="http://api.test")

    proc = subprocess.run(
        [node, "--input-type=module", "-e", TS_SCRIPT % json.dumps(STATS)],
        capture_output=True, text=True, timeout=60, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ts = [_norm(r["method"], r["url"], r["body"]) for r in out["seen"]]
    assert len(py) == 2 and py == ts[:2]
    assert all(r["auth"] is None for r in out["seen"]), "TS stats reads must not send the bearer"
    assert out["same"] is True
    assert "Economy stats are not switched on" in out["off"]
