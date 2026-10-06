"""The TypeScript SDK's tasks and bounties send what agentx-py sends.

The same calls are made through ``AgentXClient`` (over an httpx mock transport) and
through ``@agentx/sdk`` (under Node, with ``fetch`` stubbed); method, path, query and
JSON body of every request must match. Skipped when no Node >= 22.18 is on PATH.
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from agentx_sdk.client import AgentXClient
from agentx_sdk.models import BountyCreate

TS_DIR = Path(__file__).resolve().parents[1] / "ts"

TASK = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10"
BOUNTY = "0b7a4c3e-2f1d-4e5a-8b6c-9d0e1f2a3b4c"
SUB = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"
NOW = "2026-10-07T00:00:00Z"

# Enough fields for every response model agentx-py builds (Task, Bounty).
RECORD = {
    "task_id": TASK, "requester_agent_did": "did:agentx:atlas", "task_type": "review",
    "status": "open", "created_at": NOW, "updated_at": NOW,
    "bounty_id": BOUNTY, "creator_did": "did:agentx:atlas", "title": "t",
    "description": "d", "capability_required": "sql", "reward_pool": 10,
}


def _node() -> str | None:
    node = shutil.which("node") or shutil.which("/opt/homebrew/bin/node")
    if not node:
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(x) for x in version.strip().lstrip("v").split(".")[:2])
    return node if (major, minor) >= (22, 18) else None


def _norm(method: str, url: str, body: object) -> dict:
    parts = urlsplit(url)
    return {
        "method": method,
        "path": parts.path,
        "query": {k: v for k, v in sorted(parse_qs(parts.query).items())},
        "body": body,
    }


def _python_requests() -> list[dict]:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append(_norm(request.method, str(request.url), body))
        is_list = request.method == "GET" and (
            request.url.path in ("/tasks", "/markets/bounties")
            or request.url.path.endswith(("/results", "/submissions"))
        )
        return httpx.Response(200, json=[] if is_list else RECORD)

    c = AgentXClient(api_key="k", base_url="http://api.test")
    c._http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))

    c.act("review", {"q": 1}, executor_did="did:agentx:bruno")
    c.act("review")
    c.accept_task(TASK)
    c.submit_result(TASK, {"ok": True})
    c.list_tasks()
    c.list_tasks(status="assigned", limit=5)
    c.create_task("review", {"q": 1}, reward=25)
    c.create_task("review")
    c.bid_on_task(TASK)
    c.bid_on_task(TASK, confidence=0.4, bid_price=3)
    c.submit_marketplace_result(TASK, {"answer": 42})
    c.task_results(TASK)
    c.approve_task_result(TASK)
    c.reject_task_result(TASK)
    c.reject_task_result(TASK, "missing tests")
    c.cancel_task(TASK)

    c.create_bounty(BountyCreate(title="t", description="d", capability_required="sql",
                                 reward_pool=10))
    c.create_bounty(BountyCreate(title="t", description="d", capability_required="sql",
                                 reward_pool=10,
                                 deadline=datetime(2026, 12, 1, tzinfo=timezone.utc)))
    c.list_bounties()
    c.list_bounties(status="open", capability="sql", limit=5, offset=10)
    c.get_bounty(BOUNTY)
    c.submit_bounty_solution(BOUNTY)
    c.submit_bounty_solution(BOUNTY, {"sql": "select 1"}, summary="one line")
    c.list_bounty_submissions(BOUNTY)
    c.evaluate_bounty_submission(BOUNTY, SUB, 0.75)
    c.distribute_bounty_rewards(BOUNTY)
    c.cancel_bounty(BOUNTY)
    return seen


TS_SCRIPT = """
import { AgentX } from "./src/index.ts";
const [TASK, BOUNTY, SUB] = %s;
const seen = [];
const fetch = async (input, init = {}) => {
  seen.push({ method: init.method ?? "GET", url: input,
              body: init.body === undefined ? null : JSON.parse(init.body) });
  return new Response("{}", { status: 200 });
};
const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas",
                       baseUrl: "http://api.test", fetch });
const t = a.tasks, b = a.bounties;
await t.act("review", { data: { q: 1 }, executorDid: "did:agentx:bruno" });
await t.act("review");
await t.accept(TASK);
await t.complete(TASK, { ok: true });
await t.list();
await t.list({ status: "assigned", limit: 5 });
await t.create({ taskType: "review", payload: { q: 1 }, reward: 25 });
await t.create({ taskType: "review" });
await t.bid(TASK);
await t.bid(TASK, { confidence: 0.4, bidPrice: 3 });
await t.submitResult(TASK, { answer: 42 });
await t.results(TASK);
await t.approve(TASK);
await t.reject(TASK);
await t.reject(TASK, "missing tests");
await t.cancel(TASK);

await b.create({ title: "t", description: "d", capabilityRequired: "sql", rewardPool: 10 });
await b.create({ title: "t", description: "d", capabilityRequired: "sql", rewardPool: 10,
                 deadline: "2026-12-01T00:00:00Z" });
await b.list();
await b.list({ status: "open", capability: "sql", limit: 5, offset: 10 });
await b.get(BOUNTY);
await b.submit(BOUNTY);
await b.submit(BOUNTY, { solutionData: { sql: "select 1" }, summary: "one line" });
await b.submissions(BOUNTY);
await b.evaluate(BOUNTY, SUB, 0.75);
await b.distribute(BOUNTY);
await b.cancel(BOUNTY);
console.log(JSON.stringify(seen));
"""


def _ts_requests(node: str) -> list[dict]:
    script = TS_SCRIPT % json.dumps([TASK, BOUNTY, SUB])
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = json.loads(proc.stdout.strip().splitlines()[-1])
    return [_norm(r["method"], r["url"], r["body"]) for r in raw]


def test_ts_tasks_and_bounties_match_agentx_py():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")
    py, ts = _python_requests(), _ts_requests(node)
    assert len(py) == len(ts) == 27
    for i, (p, t) in enumerate(zip(py, ts)):
        assert p == t, f"call {i}: agentx-py {p} != @agentx/sdk {t}"
