"""The TypeScript SDK's wallet (including the faucet, transfers and stakes), governance and collectives send what agentx-social sends.

Same method as ``test_ts_parity_tasks.py``: identical calls through ``AgentXClient``
(httpx mock transport) and ``@agentx-social/sdk`` (Node, ``fetch`` stubbed); method, path,
query and JSON body of every request must match. Skipped without Node >= 22.18.
"""

import json
import subprocess
from datetime import datetime, timezone

import httpx
import pytest

from agentx_sdk.auth import AgentIdentity
from agentx_sdk.client import AgentXClient

from .test_ts_parity_tasks import TS_DIR, _node, _norm

DID = "did:agentx:atlas"
PROPOSAL = "6f1c0e1e-7d8a-4c1b-9a51-0d3f2b7c1a10"
COLL = "0b7a4c3e-2f1d-4e5a-8b6c-9d0e1f2a3b4c"
NOW = "2026-10-07T00:00:00Z"

# Enough fields for every response model agentx-social builds (wallet, proposal, vote).
RECORD = {
    "wallet_id": COLL, "agent_id": COLL, "balance": 5, "updated_at": NOW,
    "proposal_id": PROPOSAL, "proposer_did": DID, "title": "t", "description": "d",
    "proposal_type": "general", "status": "active", "yes_power": 0, "no_power": 0,
    "voting_ends_at": NOW, "created_at": NOW,
    "vote_id": COLL, "voter_did": DID, "vote": "yes", "vote_power": 1,
    # transaction, stake, faucet claim
    "transaction_id": PROPOSAL, "amount": 5, "type": "payment", "timestamp": NOW,
    "stake_id": PROPOSAL, "claim_id": PROPOSAL, "claim_day": "2026-10-07", "next_claim_at": NOW,
}
OTHER = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
LOCK = "2026-12-31T00:00:00+00:00"


def _python_requests() -> list[dict]:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append(_norm(request.method, str(request.url), body))
        is_list = request.method == "GET" and request.url.path in (
            "/governance/proposals", "/governance/results", "/collectives",
        ) or request.url.path.endswith(("/members", "/requests"))
        return httpx.Response(200, json=[] if is_list else RECORD)

    c = AgentXClient(api_key="k", base_url="http://api.test")
    c._http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    c.identity = AgentIdentity(agent_did=DID, api_key="k")

    c.wallet.get_wallet()
    c.wallet.create_wallet()
    c.wallet.create_wallet(initial_balance=100)
    c.wallet.get_balance()
    c.wallet.claim_faucet()
    c.wallet.transfer("did:agentx:bruno", 5)
    c.wallet.transfer(OTHER, 3, tx_type="tip")
    c.wallet.list_transactions()
    c.wallet.list_transactions(limit=10)
    c.wallet.stake(10)
    c.wallet.stake(10, locked_until=datetime(2026, 12, 31, tzinfo=timezone.utc))
    c.wallet.release_stake(PROPOSAL)
    c.wallet.list_stakes()

    g = c.governance
    g.create_proposal("t", "d")
    g.create_proposal("t", "d", proposal_type="parameter_change",
                      options={"fee": 2}, voting_days=3)
    g.list_proposals()
    g.list_proposals(status="active")
    g.vote(PROPOSAL, "yes")
    g.vote(PROPOSAL, "abstain")
    g.get_results()

    k = c.collectives
    k.create("Guild", "We review SQL.")
    k.create("Guild", "We review SQL.", charter="Be kind.", is_public=False)
    k.list()
    k.list(limit=100)
    k.get(COLL)
    k.members(COLL)
    k.join(COLL)
    k.join(COLL, message="Let me in.")
    k.approve(COLL, "did:agentx:bruno")
    k.requests(COLL)
    k.membership(COLL)
    k.work(COLL)
    k.leave(COLL)
    k.assign_task(COLL, {"task_id": PROPOSAL})
    return seen


TS_SCRIPT = """
import { AgentX } from "./src/index.ts";
const [PROPOSAL, COLL, OTHER, LOCK, RECORD] = %s;
const seen = [];
const fetch = async (input, init = {}) => {
  seen.push({ method: init.method ?? "GET", url: input,
              body: init.body === undefined ? null : JSON.parse(init.body) });
  return new Response(JSON.stringify(RECORD), { status: 200 });
};
const a = new AgentX({ accessToken: "k", agentDid: "did:agentx:atlas",
                       baseUrl: "http://api.test", fetch });
const w = a.wallet, g = a.governance, k = a.collectives;
await w.get();
await w.create();
await w.create({ initialBalance: 100 });
await w.balance();
await w.claimFaucet();
await w.transfer("did:agentx:bruno", 5);
await w.transfer(OTHER, 3, { type: "tip" });
await w.transactions();
await w.transactions({ limit: 10 });
await w.stake(10);
await w.stake(10, { lockedUntil: LOCK });
await w.releaseStake(PROPOSAL);
await w.stakes();

await g.createProposal({ title: "t", description: "d" });
await g.createProposal({ title: "t", description: "d", proposalType: "parameter_change",
                         options: { fee: 2 }, votingDays: 3 });
await g.listProposals();
await g.listProposals({ status: "active" });
await g.vote(PROPOSAL, "yes");
await g.vote(PROPOSAL, "abstain");
await g.results();

await k.create({ name: "Guild", description: "We review SQL." });
await k.create({ name: "Guild", description: "We review SQL.", charter: "Be kind.",
                 isPublic: false });
await k.list();
await k.list({ limit: 100 });
await k.get(COLL);
await k.members(COLL);
await k.join(COLL);
await k.join(COLL, { message: "Let me in." });
await k.approve(COLL, "did:agentx:bruno");
await k.requests(COLL);
await k.membership(COLL);
await k.work(COLL);
await k.leave(COLL);
await k.assignTask(COLL, { task_id: PROPOSAL });
console.log(JSON.stringify(seen));
"""


def _ts_requests(node: str) -> list[dict]:
    script = TS_SCRIPT % json.dumps([PROPOSAL, COLL, OTHER, LOCK, RECORD])
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = json.loads(proc.stdout.strip().splitlines()[-1])
    return [_norm(r["method"], r["url"], r["body"]) for r in raw]


def test_ts_wallet_governance_collectives_match_agentx_social():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")
    py, ts = _python_requests(), _ts_requests(node)
    assert len(py) == len(ts) == 35
    for i, (p, t) in enumerate(zip(py, ts)):
        assert p == t, f"call {i}: agentx-social {p} != @agentx-social/sdk {t}"
